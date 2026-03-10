import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildGatewayApp } from '../../services/api-gateway/src/app.js'

afterEach(() => {
  vi.unstubAllGlobals()
  delete process.env.GATEWAY_EXPORT_BACKEND
  delete process.env.EXPORT_SERVICE_HOST
  delete process.env.EXPORT_SERVICE_PORT
  delete process.env.GATEWAY_SERVE_STATIC
})

describe('api-gateway export proxy', () => {
  it('preserves binary headers from export-service', async () => {
    process.env.GATEWAY_EXPORT_BACKEND = 'service'
    process.env.EXPORT_SERVICE_HOST = 'export-service'
    process.env.EXPORT_SERVICE_PORT = '8768'
    process.env.GATEWAY_SERVE_STATIC = '0'

    vi.stubGlobal('fetch', vi.fn(async () => {
      return new Response(new Uint8Array([0x50, 0x4b, 0x03, 0x04]), {
        status: 200,
        headers: {
          'content-type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          'content-disposition': 'attachment; filename="lexicon_export.xlsx"',
        },
      })
    }))

    const app = buildGatewayApp()
    try {
      const response = await app.inject({ method: 'GET', url: '/api/lexicon/export' })
      expect(response.statusCode).toBe(200)
      expect(response.headers['content-type']).toBe(
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      )
      expect(response.headers['content-disposition']).toBe(
        'attachment; filename="lexicon_export.xlsx"',
      )
      expect(Buffer.from(response.rawPayload)).toEqual(Buffer.from([0x50, 0x4b, 0x03, 0x04]))
    } finally {
      await app.close()
    }
  })
})
