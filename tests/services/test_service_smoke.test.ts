import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { buildGatewayApp } from '../../services/api-gateway/src/app.js'
import { buildAssignmentsServiceApp } from '../../services/assignments-service/src/app.js'
import { buildLexiconServiceApp } from '../../services/lexicon-service/src/app.js'

const tempDirs: string[] = []

function mkTempDb(prefix: string, filename: string): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix))
  tempDirs.push(dir)
  return path.join(dir, filename)
}

afterEach(async () => {
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true })
  }
  delete process.env.LEXICON_DB_PATH
  delete process.env.ASSIGNMENTS_DB_PATH
  delete process.env.GATEWAY_SERVE_STATIC
})

describe('service smoke', () => {
  it('lexicon-service health', async () => {
    process.env.LEXICON_DB_PATH = mkTempDb('lexicon-smoke-', 'lexicon.sqlite3')

    const app = buildLexiconServiceApp()
    try {
      const result = await app.inject({ method: 'GET', url: '/health' })
      expect(result.statusCode).toBe(200)
      expect(result.json().status).toBe('ok')
    } finally {
      await app.close()
    }
  })

  it('assignments-service health', async () => {
    process.env.ASSIGNMENTS_DB_PATH = mkTempDb('assignments-smoke-', 'assignments.db')

    const app = buildAssignmentsServiceApp()
    try {
      const result = await app.inject({ method: 'GET', url: '/health' })
      expect(result.statusCode).toBe(200)
      expect(result.json().status).toBe('ok')
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
      expect(result.json().status).toBe('ok')
    } finally {
      await app.close()
    }
  })
})
