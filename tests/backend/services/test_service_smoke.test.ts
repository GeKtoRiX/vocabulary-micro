import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildGatewayApp } from '../../../backend/services/api-gateway/src/app.js'

const tempDirs: string[] = []

afterEach(async () => {
  vi.resetModules()
  vi.restoreAllMocks()
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true })
  }
  delete process.env.GATEWAY_SERVE_STATIC
  delete process.env.GATEWAY_STATIC_DIR
})

function mockOwnerServiceRepositories() {
  class MockLexiconRepository {
    async close() {}
  }

  class MockAssignmentsRepository {
    async close() {}
  }

  vi.doMock('../../../backend/services/lexicon-service/src/postgres_repository.js', () => ({
    PostgresLexiconRepository: MockLexiconRepository,
  }))
  vi.doMock('../../../backend/services/assignments-service/src/postgres_repository.js', () => ({
    PostgresAssignmentsRepository: MockAssignmentsRepository,
  }))
}

describe('service smoke', () => {
  it('lexicon-service health', async () => {
    mockOwnerServiceRepositories()

    const { buildLexiconServiceApp } = await import('../../../backend/services/lexicon-service/src/app.js')
    const app = buildLexiconServiceApp()
    try {
      const result = await app.inject({ method: 'GET', url: '/health' })
      expect(result.statusCode).toBe(200)
      expect(result.json()).toEqual({
        status: 'ok',
        storage_backend: 'postgres',
      })
    } finally {
      await app.close()
    }
  })

  it('assignments-service health', async () => {
    mockOwnerServiceRepositories()

    const { buildAssignmentsServiceApp } = await import('../../../backend/services/assignments-service/src/app.js')
    const app = buildAssignmentsServiceApp()
    try {
      const result = await app.inject({ method: 'GET', url: '/health' })
      expect(result.statusCode).toBe(200)
      expect(result.json()).toEqual({
        status: 'ok',
        storage_backend: 'postgres',
      })
    } finally {
      await app.close()
    }
  })

  it('api-gateway health', async () => {
    process.env.GATEWAY_SERVE_STATIC = '0'

    const app = buildGatewayApp()
    try {
      const result = await app.inject({ method: 'GET', url: '/api/system/health' })
      expect(result.statusCode).toBe(200)
      expect(result.json()).toEqual({ status: 'ok' })
    } finally {
      await app.close()
    }
  })

  it('api-gateway serves frontend shell from root path when static assets are enabled', async () => {
    const staticDir = fs.mkdtempSync(path.join(os.tmpdir(), 'gateway-static-'))
    tempDirs.push(staticDir)
    fs.writeFileSync(path.join(staticDir, 'index.html'), '<!doctype html><html><body><div id="root"></div></body></html>')
    process.env.GATEWAY_SERVE_STATIC = '1'
    process.env.GATEWAY_STATIC_DIR = staticDir

    const app = buildGatewayApp()
    try {
      const result = await app.inject({ method: 'GET', url: '/' })
      expect(result.statusCode).toBe(200)
      expect(result.body).toContain('<div id="root"></div>')

      const head = await app.inject({ method: 'HEAD', url: '/' })
      expect(head.statusCode).toBe(200)
    } finally {
      await app.close()
    }
  })
})
