import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildGatewayApp } from '../../services/api-gateway/src/app.js'

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
})
