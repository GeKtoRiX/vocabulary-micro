import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildGatewayApp } from '../../../backend/services/api-gateway/src/app.js'

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
  delete process.env.GATEWAY_ASSIGNMENTS_BACKEND
  delete process.env.GATEWAY_EXPORT_BACKEND
  delete process.env.GATEWAY_SERVE_STATIC
  delete process.env.NLP_SERVICE_HOST
  delete process.env.NLP_SERVICE_PORT
  delete process.env.ASSIGNMENTS_SERVICE_HOST
  delete process.env.ASSIGNMENTS_SERVICE_PORT
  delete process.env.EXPORT_SERVICE_HOST
  delete process.env.EXPORT_SERVICE_PORT
})

describe('api-gateway failure modes', () => {
  it('returns 502 when export-service is unavailable', async () => {
    process.env.GATEWAY_EXPORT_BACKEND = 'service'
    process.env.EXPORT_SERVICE_HOST = 'export-service'
    process.env.EXPORT_SERVICE_PORT = '8768'
    process.env.GATEWAY_SERVE_STATIC = '0'

    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('connect ECONNREFUSED export-service')
    }))

    const app = buildGatewayApp()
    try {
      const response = await app.inject({ method: 'GET', url: '/api/lexicon/export' })
      expect(response.statusCode).toBe(502)
      expect(response.json().detail).toContain('ECONNREFUSED')
    } finally {
      await app.close()
    }
  })

  it('emits an SSE error event when nlp-service parse backend is unavailable', async () => {
    process.env.GATEWAY_PARSE_BACKEND = 'nlp'
    process.env.NLP_SERVICE_HOST = 'nlp-service'
    process.env.NLP_SERVICE_PORT = '8767'
    process.env.GATEWAY_SERVE_STATIC = '0'

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/nlp/parse')) {
        throw new Error('connect ECONNREFUSED nlp-service')
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const start = await app.inject({
        method: 'POST',
        url: '/api/parse',
        payload: { text: 'I run daily.' },
      })
      expect(start.statusCode).toBe(200)
      const { job_id } = start.json() as { job_id: string }
      expect(job_id).toBeTruthy()

      const stream = await app.inject({
        method: 'GET',
        url: `/api/parse/jobs/${job_id}/stream`,
      })
      expect(stream.statusCode).toBe(200)
      const frames = parseSseFrames(stream.body)
      expect(frames[0]).toMatchObject({ type: 'progress', message: 'Parsing...' })
      expect(frames.some((frame) => frame.type === 'error')).toBe(true)
      expect(JSON.stringify(frames)).toContain('ECONNREFUSED nlp-service')
    } finally {
      await app.close()
    }
  })

  it('keeps parse result when third-pass request fails', async () => {
    process.env.GATEWAY_PARSE_BACKEND = 'nlp'
    process.env.NLP_SERVICE_HOST = 'nlp-service'
    process.env.NLP_SERVICE_PORT = '8767'
    process.env.GATEWAY_SERVE_STATIC = '0'

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/nlp/parse')) {
        return new Response(JSON.stringify({
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
        }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/internal/v1/nlp/third-pass')) {
        throw new Error('connect ECONNREFUSED llm-service')
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const start = await app.inject({
        method: 'POST',
        url: '/api/parse',
        payload: { text: 'run', third_pass_enabled: true },
      })
      expect(start.statusCode).toBe(200)
      const { job_id } = start.json() as { job_id: string }

      const stream = await app.inject({
        method: 'GET',
        url: `/api/parse/jobs/${job_id}/stream`,
      })
      const frames = parseSseFrames(stream.body)

      expect(frames).toContainEqual({ type: 'stage_progress', stage: 'nlp', status: 'done' })
      expect(frames).toContainEqual({
        type: 'stage_progress',
        stage: 'llm',
        status: 'error',
        message: 'connect ECONNREFUSED llm-service',
      })
      expect(frames.some((frame) => frame.type === 'result')).toBe(true)
      expect(frames[frames.length - 1]).toMatchObject({ type: 'done' })
    } finally {
      await app.close()
    }
  })

  it('marks llm stage as error when third-pass returns failed summary', async () => {
    process.env.GATEWAY_PARSE_BACKEND = 'nlp'
    process.env.NLP_SERVICE_HOST = 'nlp-service'
    process.env.NLP_SERVICE_PORT = '8767'
    process.env.GATEWAY_SERVE_STATIC = '0'

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/nlp/parse')) {
        return new Response(JSON.stringify({
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
        }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/internal/v1/nlp/third-pass')) {
        return new Response(JSON.stringify({
          status: 'failed',
          reason: 'third_pass_request_failed',
          stage_statuses: [
            {
              stage: 'llm_extract',
              status: 'failed',
              reason: 'third_pass_request_failed',
              metadata: {
                error: "Failed to call LLM endpoint 'http://127.0.0.1:8000/v1/chat/completions': timed out",
              },
            },
          ],
        }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const start = await app.inject({
        method: 'POST',
        url: '/api/parse',
        payload: { text: 'run', third_pass_enabled: true },
      })
      expect(start.statusCode).toBe(200)
      const { job_id } = start.json() as { job_id: string }

      const stream = await app.inject({
        method: 'GET',
        url: `/api/parse/jobs/${job_id}/stream`,
      })
      const frames = parseSseFrames(stream.body)

      expect(frames).toContainEqual({ type: 'stage_progress', stage: 'nlp', status: 'done' })
      expect(frames).toContainEqual({
        type: 'stage_progress',
        stage: 'llm',
        status: 'error',
        message: "Failed to call LLM endpoint 'http://127.0.0.1:8000/v1/chat/completions': timed out",
        llm_summary: {
          status: 'failed',
          reason: 'third_pass_request_failed',
          stage_statuses: [
            {
              stage: 'llm_extract',
              status: 'failed',
              reason: 'third_pass_request_failed',
              metadata: {
                error: "Failed to call LLM endpoint 'http://127.0.0.1:8000/v1/chat/completions': timed out",
              },
            },
          ],
        },
      })
      const resultFrame = frames.find((frame) => frame.type === 'result')
      expect(resultFrame).toBeTruthy()
      expect((resultFrame as { summary: Record<string, unknown> }).summary).toMatchObject({
        third_pass_summary: {
          status: 'failed',
          reason: 'third_pass_request_failed',
        },
      })
      expect(frames[frames.length - 1]).toMatchObject({ type: 'done' })
    } finally {
      await app.close()
    }
  })

  it('emits an SSE error event when assignments-service scan backend is unavailable', async () => {
    process.env.GATEWAY_ASSIGNMENTS_BACKEND = 'service'
    process.env.ASSIGNMENTS_SERVICE_HOST = 'assignments-service'
    process.env.ASSIGNMENTS_SERVICE_PORT = '4012'
    process.env.GATEWAY_SERVE_STATIC = '0'

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/assignments/scan')) {
        throw new Error('connect ECONNREFUSED assignments-service')
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const start = await app.inject({
        method: 'POST',
        url: '/api/assignments/scan',
        payload: {
          title: 'Failure smoke',
          content_original: 'I walk',
          content_completed: 'I run quickly',
        },
      })
      expect(start.statusCode).toBe(200)
      const { job_id } = start.json() as { job_id: string }
      expect(job_id).toBeTruthy()

      const stream = await app.inject({
        method: 'GET',
        url: `/api/assignments/scan/jobs/${job_id}/stream`,
      })
      expect(stream.statusCode).toBe(200)
      const frames = parseSseFrames(stream.body)
      expect(frames[0]).toMatchObject({ type: 'progress', message: 'Scanning assignment...' })
      expect(frames.some((frame) => frame.type === 'error')).toBe(true)
      expect(JSON.stringify(frames)).toContain('ECONNREFUSED assignments-service')
    } finally {
      await app.close()
    }
  })

  it('defaults statistics average coverage to 0 when assignments-service omits it', async () => {
    process.env.GATEWAY_ASSIGNMENTS_BACKEND = 'service'
    process.env.ASSIGNMENTS_SERVICE_HOST = 'assignments-service'
    process.env.ASSIGNMENTS_SERVICE_PORT = '4012'
    process.env.GATEWAY_SERVE_STATIC = '0'
    process.env.LEXICON_SERVICE_HOST = 'lexicon-service'
    process.env.LEXICON_SERVICE_PORT = '4011'

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/lexicon/statistics')) {
        return new Response(JSON.stringify({
          total_entries: 10,
          counts_by_status: { approved: 3, pending_review: 2 },
          counts_by_source: { manual: 10 },
          categories: [{ name: 'Verb', count: 4 }],
        }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/internal/v1/assignments/statistics')) {
        return new Response(JSON.stringify({
          units: [],
          total_units: 0,
          total_subunits: 0,
          average_subunits_per_unit: null,
        }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const response = await app.inject({ method: 'GET', url: '/api/statistics' })
      expect(response.statusCode).toBe(200)
      expect(response.json().overview.average_subunits_per_unit).toBe(0)
    } finally {
      await app.close()
    }
  })
})
