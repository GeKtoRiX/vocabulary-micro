import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildGatewayApp } from '../../services/api-gateway/src/app.js'

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
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
  delete process.env.GATEWAY_SERVE_STATIC
  delete process.env.GATEWAY_PARSE_BACKEND
  delete process.env.GATEWAY_LEXICON_BACKEND
  delete process.env.GATEWAY_ASSIGNMENTS_BACKEND
  delete process.env.LEXICON_SERVICE_HOST
  delete process.env.LEXICON_SERVICE_PORT
  delete process.env.NLP_SERVICE_HOST
  delete process.env.NLP_SERVICE_PORT
  delete process.env.ASSIGNMENTS_SERVICE_HOST
  delete process.env.ASSIGNMENTS_SERVICE_PORT
})

describe('api-gateway public parity', () => {
  it('keeps system health payload identical to legacy shape', async () => {
    process.env.GATEWAY_SERVE_STATIC = '0'

    const app = buildGatewayApp()
    try {
      const response = await app.inject({ method: 'GET', url: '/api/system/health' })
      expect(response.statusCode).toBe(200)
      expect(response.json()).toEqual({ status: 'ok' })
    } finally {
      await app.close()
    }
  })

  it('does not surface request_id in parse SSE frames when using nlp-service', async () => {
    process.env.GATEWAY_SERVE_STATIC = '0'
    process.env.GATEWAY_PARSE_BACKEND = 'nlp'
    process.env.NLP_SERVICE_HOST = 'nlp-service'
    process.env.NLP_SERVICE_PORT = '8767'

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/nlp/parse')) {
        return jsonResponse({
          rows: [
            {
              index: 1,
              token: 'run',
              normalized: 'run',
              lemma: 'run',
              categories: 'Verb',
              source: 'manual',
              matched_form: 'run',
              confidence: '1.0',
              known: 'true',
            },
          ],
          summary: { total_tokens: 1 },
          status_message: 'ok',
          error_message: '',
        })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const start = await app.inject({ method: 'POST', url: '/api/parse', payload: { text: 'run' } })
      const { job_id } = start.json() as { job_id: string }

      const stream = await app.inject({ method: 'GET', url: `/api/parse/jobs/${job_id}/stream` })
      const frames = parseSseFrames(stream.body)

      expect(frames).toEqual([
        { type: 'progress', message: 'Parsing...' },
        {
          type: 'result',
          rows: [
            {
              index: 1,
              token: 'run',
              normalized: 'run',
              lemma: 'run',
              categories: 'Verb',
              source: 'manual',
              matched_form: 'run',
              confidence: '1.0',
              known: 'true',
            },
          ],
          summary: { total_tokens: 1 },
          status_message: 'ok',
          error_message: '',
        },
        { type: 'done' },
      ])
    } finally {
      await app.close()
    }
  })

  it('does not surface request_id in assignments SSE frames when using assignments-service', async () => {
    process.env.GATEWAY_SERVE_STATIC = '0'
    process.env.GATEWAY_ASSIGNMENTS_BACKEND = 'service'
    process.env.ASSIGNMENTS_SERVICE_HOST = 'assignments-service'
    process.env.ASSIGNMENTS_SERVICE_PORT = '4012'

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/assignments/scan')) {
        return jsonResponse({
          assignment_id: 1,
          title: 'Essay',
          content_original: 'I walk',
          content_completed: 'I run',
          word_count: 2,
          known_token_count: 1,
          unknown_token_count: 1,
          lexicon_coverage_percent: 50,
          assignment_status: 'PENDING',
          message: 'Assignment scan completed.',
          duration_ms: 1.5,
          matches: [
            {
              entry_id: 1,
              term: 'run',
              category: 'Verb',
              source: 'manual',
              occurrences: 1,
            },
          ],
          missing_words: [
            {
              term: 'i',
              occurrences: 1,
              example_usage: 'I run',
            },
          ],
          diff_chunks: [
            {
              operation: 'replace',
              original_text: 'walk',
              completed_text: 'run',
            },
          ],
        })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const start = await app.inject({
        method: 'POST',
        url: '/api/assignments/scan',
        payload: {
          title: 'Essay',
          content_original: 'I walk',
          content_completed: 'I run',
        },
      })
      const { job_id } = start.json() as { job_id: string }

      const stream = await app.inject({ method: 'GET', url: `/api/assignments/scan/jobs/${job_id}/stream` })
      const frames = parseSseFrames(stream.body)

      expect(frames[0]).toEqual({ type: 'progress', message: 'Scanning assignment...' })
      expect(frames[1]).toMatchObject({
        type: 'result',
        data: {
          assignment_id: 1,
          title: 'Essay',
          content_completed: 'I run',
        },
      })
      expect('request_id' in frames[0]).toBe(false)
      expect('request_id' in frames[1]).toBe(false)
      expect(frames[2]).toEqual({ type: 'done' })
    } finally {
      await app.close()
    }
  })

  it('does not force content-type for empty-body delete category requests', async () => {
    process.env.GATEWAY_SERVE_STATIC = '0'
    process.env.GATEWAY_LEXICON_BACKEND = 'service'
    process.env.LEXICON_SERVICE_HOST = 'lexicon-service'
    process.env.LEXICON_SERVICE_PORT = '4011'

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/lexicon/categories/Manual%20E2E')) {
        expect(init?.method).toBe('DELETE')
        expect(init?.body).toBeUndefined()
        expect(new Headers(init?.headers).get('content-type')).toBeNull()
        return jsonResponse({
          categories: ['Auto Added'],
          message: "Deleted category 'Manual E2E'.",
        })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const response = await app.inject({
        method: 'DELETE',
        url: '/api/lexicon/categories/Manual%20E2E',
      })
      expect(response.statusCode).toBe(200)
      expect(response.json()).toEqual({
        categories: ['Auto Added'],
        message: "Deleted category 'Manual E2E'.",
      })
    } finally {
      await app.close()
    }
  })
})
