import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildGatewayApp } from '../../../backend/services/api-gateway/src/app.js'

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  delete process.env.GATEWAY_SERVE_STATIC
  delete process.env.GATEWAY_STATISTICS_BACKEND
  delete process.env.LEXICON_SERVICE_HOST
  delete process.env.LEXICON_SERVICE_PORT
  delete process.env.ASSIGNMENTS_SERVICE_HOST
  delete process.env.ASSIGNMENTS_SERVICE_PORT
})

describe('gateway statistics', () => {
  it('composes statistics from both services', async () => {
    process.env.GATEWAY_SERVE_STATIC = '0'
    process.env.GATEWAY_STATISTICS_BACKEND = 'composed'
    process.env.LEXICON_SERVICE_HOST = 'lexicon-service'
    process.env.LEXICON_SERVICE_PORT = '4011'
    process.env.ASSIGNMENTS_SERVICE_HOST = 'assignments-service'
    process.env.ASSIGNMENTS_SERVICE_PORT = '4012'

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/lexicon/statistics')) {
        return jsonResponse({
          total_entries: 42,
          counts_by_status: { approved: 10, pending_review: 2 },
          counts_by_source: { manual: 30, auto: 12 },
          categories: [{ name: 'Verb', count: 12 }],
        })
      }
      if (url.includes('/internal/v1/assignments/statistics')) {
        return jsonResponse({
          units: [{ unit_code: 'Unit05', subunit_count: 4, created_at: '2026-03-10T00:00:00.000Z' }],
          total_units: 5,
          total_subunits: 19,
          average_subunits_per_unit: 3.8,
        })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const result = await app.inject({ method: 'GET', url: '/api/statistics' })

      expect(result.statusCode).toBe(200)
      expect(result.json()).toMatchObject({
        total_entries: 42,
        units: [{ unit_code: 'Unit05', subunit_count: 4, created_at: '2026-03-10T00:00:00.000Z' }],
        overview: {
          total_units: 5,
          total_subunits: 19,
          average_subunits_per_unit: 3.8,
        },
      })
    } finally {
      await app.close()
    }
  })

  it('returns 502 when lexicon-service is down during statistics aggregation', async () => {
    process.env.GATEWAY_SERVE_STATIC = '0'
    process.env.GATEWAY_STATISTICS_BACKEND = 'composed'
    process.env.LEXICON_SERVICE_HOST = 'lexicon-service'
    process.env.LEXICON_SERVICE_PORT = '4011'
    process.env.ASSIGNMENTS_SERVICE_HOST = 'assignments-service'
    process.env.ASSIGNMENTS_SERVICE_PORT = '4012'

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/lexicon/statistics')) {
        throw new Error('connect ECONNREFUSED lexicon-service')
      }
      if (url.includes('/internal/v1/assignments/statistics')) {
        return jsonResponse({
          units: [],
          total_units: 0,
          total_subunits: 0,
          average_subunits_per_unit: 0,
        })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const result = await app.inject({ method: 'GET', url: '/api/statistics' })

      expect(result.statusCode).toBe(502)
      expect(result.json().detail).toContain('ECONNREFUSED lexicon-service')
    } finally {
      await app.close()
    }
  })
})
