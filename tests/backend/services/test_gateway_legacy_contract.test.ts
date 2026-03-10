import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildGatewayApp } from '../../../backend/services/api-gateway/src/app.js'

function jsonResponse(payload: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(payload), {
    status: init.status ?? 200,
    headers: {
      'content-type': 'application/json',
      ...(init.headers ?? {}),
    },
  })
}

function sseResponse(events: Array<Record<string, unknown>>): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
      }
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
  })
}

function parseSseFrames(raw: string): Array<Record<string, unknown>> {
  return raw
    .split('\n\n')
    .map((frame) => frame.trim())
    .filter(Boolean)
    .map((frame) => frame.replace(/^data:\s*/, ''))
    .map((frame) => JSON.parse(frame) as Record<string, unknown>)
}

afterEach(() => {
  vi.unstubAllGlobals()
  delete process.env.GATEWAY_PARSE_BACKEND
  delete process.env.GATEWAY_LEXICON_BACKEND
  delete process.env.GATEWAY_ASSIGNMENTS_BACKEND
  delete process.env.GATEWAY_STATISTICS_BACKEND
  delete process.env.GATEWAY_SERVE_STATIC
  delete process.env.LEGACY_BACKEND_BASE_URL
})

describe('api-gateway legacy contract parity', () => {
  it('preserves legacy warmup and statistics payloads', async () => {
    process.env.GATEWAY_PARSE_BACKEND = 'legacy'
    process.env.GATEWAY_STATISTICS_BACKEND = 'legacy'
    process.env.GATEWAY_SERVE_STATIC = '0'
    process.env.LEGACY_BACKEND_BASE_URL = 'http://legacy-backend:8766'

    const warmupPayload = {
      running: false,
      ready: true,
      failed: false,
      error_message: '',
      elapsed_sec: 1.23,
    }
    const statisticsPayload = {
      total_entries: 3,
      counts_by_status: { approved: 2, pending_review: 1 },
      counts_by_source: { manual: 2, auto: 1 },
      categories: [{ name: 'Verb', count: 2 }],
      assignment_coverage: [{ title: 'Essay', coverage_pct: 50, created_at: '2026-03-10T00:00:00Z' }],
      overview: {
        total_assignments: 1,
        average_assignment_coverage: 50,
        pending_review_count: 1,
        approved_count: 2,
        low_coverage_count: 1,
        top_category: { name: 'Verb', count: 2 },
      },
    }

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.endsWith('/api/system/warmup')) {
        return jsonResponse(warmupPayload)
      }
      if (url.endsWith('/api/statistics')) {
        return jsonResponse(statisticsPayload)
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const warmup = await app.inject({ method: 'GET', url: '/api/system/warmup' })
      expect(warmup.statusCode).toBe(200)
      expect(warmup.json()).toEqual(warmupPayload)

      const statistics = await app.inject({ method: 'GET', url: '/api/statistics' })
      expect(statistics.statusCode).toBe(200)
      expect(statistics.json()).toEqual(statisticsPayload)
    } finally {
      await app.close()
    }
  })

  it('bridges legacy parse SSE without losing result payload fields', async () => {
    process.env.GATEWAY_PARSE_BACKEND = 'legacy'
    process.env.GATEWAY_SERVE_STATIC = '0'
    process.env.LEGACY_BACKEND_BASE_URL = 'http://legacy-backend:8766'

    const parseResult = {
      rows: [
        {
          index: 1,
          token: 'run',
          normalized: 'run',
          lemma: 'run',
          categories: 'Verb',
          source: 'manual',
          matched_form: 'run',
          confidence: 0.99,
          known: true,
        },
      ],
      summary: { total_tokens: 1, known_tokens: 1 },
      status_message: 'ok',
      error_message: '',
    }

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/parse') && init?.method === 'POST') {
        return jsonResponse({ job_id: 'legacy-parse-job' })
      }
      if (url.endsWith('/api/parse/jobs/legacy-parse-job/stream') && init?.method === 'GET') {
        return sseResponse([
          { type: 'progress', message: 'Parsing...' },
          { type: 'result', ...parseResult },
          { type: 'done' },
        ])
      }
      throw new Error(`Unexpected fetch: ${url} ${init?.method ?? 'GET'}`)
    }))

    const app = buildGatewayApp()
    try {
      const start = await app.inject({
        method: 'POST',
        url: '/api/parse',
        payload: { text: 'run' },
      })
      expect(start.statusCode).toBe(200)
      const { job_id } = start.json() as { job_id: string }

      const stream = await app.inject({
        method: 'GET',
        url: `/api/parse/jobs/${job_id}/stream`,
      })
      expect(stream.statusCode).toBe(200)
      const frames = parseSseFrames(stream.body)
      expect(frames[0]).toMatchObject({ type: 'progress', message: 'Parsing...' })
      const resultFrame = frames.find((frame) => frame.type === 'result')
      expect(resultFrame).toBeTruthy()
      expect(resultFrame).toMatchObject({
        type: 'result',
        rows: parseResult.rows,
        summary: parseResult.summary,
        status_message: 'ok',
        error_message: '',
      })
      expect(frames[frames.length - 1]).toMatchObject({ type: 'done' })
    } finally {
      await app.close()
    }
  })

  it('bridges legacy assignments scan SSE and proxies lexicon routes compatibly', async () => {
    process.env.GATEWAY_ASSIGNMENTS_BACKEND = 'legacy'
    process.env.GATEWAY_LEXICON_BACKEND = 'legacy'
    process.env.GATEWAY_SERVE_STATIC = '0'
    process.env.LEGACY_BACKEND_BASE_URL = 'http://legacy-backend:8766'

    const lexiconSearchPayload = {
      rows: [
        {
          id: 7,
          category: 'Verb',
          value: 'run',
          normalized: 'run',
          source: 'manual',
          confidence: 1,
          first_seen_at: '2026-03-10T00:00:00Z',
          request_id: null,
          status: 'approved',
          created_at: '2026-03-10T00:00:00Z',
          reviewed_at: null,
          reviewed_by: null,
          review_note: null,
        },
      ],
      total_rows: 1,
      filtered_rows: 1,
      counts_by_status: { approved: 1 },
      available_categories: ['Verb'],
      message: '',
    }

    const assignmentResult = {
      data: {
        assignment_id: 11,
        title: 'Essay',
        content_original: 'I walk',
        content_completed: 'I run',
        word_count: 2,
        known_token_count: 1,
        unknown_token_count: 1,
        lexicon_coverage_percent: 50,
        assignment_status: 'PENDING',
        message: 'Assignment scan completed.',
        duration_ms: 4.2,
        matches: [{ entry_id: 7, term: 'run', category: 'Verb', source: 'manual', occurrences: 1 }],
        missing_words: [{ term: 'i', occurrences: 1, example_usage: 'I run' }],
        diff_chunks: [{ operation: 'replace', original_text: 'walk', completed_text: 'run' }],
      },
    }

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/api/lexicon/entries') && init?.method === 'GET') {
        return jsonResponse(lexiconSearchPayload)
      }
      if (url.endsWith('/api/assignments/scan') && init?.method === 'POST') {
        return jsonResponse({ job_id: 'legacy-assignment-job' })
      }
      if (url.endsWith('/api/assignments/scan/jobs/legacy-assignment-job/stream') && init?.method === 'GET') {
        return sseResponse([
          { type: 'progress', message: 'Scanning assignment...' },
          { type: 'result', ...assignmentResult },
          { type: 'done' },
        ])
      }
      throw new Error(`Unexpected fetch: ${url} ${init?.method ?? 'GET'}`)
    }))

    const app = buildGatewayApp()
    try {
      const lexicon = await app.inject({
        method: 'GET',
        url: '/api/lexicon/entries?status=all&limit=20&offset=0',
      })
      expect(lexicon.statusCode).toBe(200)
      expect(lexicon.json()).toEqual(lexiconSearchPayload)

      const start = await app.inject({
        method: 'POST',
        url: '/api/assignments/scan',
        payload: {
          title: 'Essay',
          content_original: 'I walk',
          content_completed: 'I run',
        },
      })
      expect(start.statusCode).toBe(200)
      const { job_id } = start.json() as { job_id: string }

      const stream = await app.inject({
        method: 'GET',
        url: `/api/assignments/scan/jobs/${job_id}/stream`,
      })
      expect(stream.statusCode).toBe(200)
      const frames = parseSseFrames(stream.body)
      expect(frames[0]).toMatchObject({ type: 'progress', message: 'Scanning assignment...' })
      const resultFrame = frames.find((frame) => frame.type === 'result')
      expect(resultFrame).toBeTruthy()
      expect(resultFrame).toMatchObject({
        type: 'result',
        data: assignmentResult.data,
      })
      expect(frames[frames.length - 1]).toMatchObject({ type: 'done' })
    } finally {
      await app.close()
    }
  })
})
