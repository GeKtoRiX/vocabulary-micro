import { afterEach, describe, expect, it } from 'vitest'
import path from 'node:path'
import { loadConfig } from '../../../backend/services/shared/src/config.js'

const originalCwd = process.cwd()
const repoRoot = path.basename(originalCwd) === 'services'
  ? path.dirname(path.dirname(originalCwd))
  : originalCwd

afterEach(() => {
  process.chdir(originalCwd)
  delete process.env.OWNER_SERVICES_POSTGRES_URL
  delete process.env.LEXICON_POSTGRES_SCHEMA
  delete process.env.LEXICON_POSTGRES_URL
  delete process.env.ASSIGNMENTS_POSTGRES_SCHEMA
  delete process.env.ASSIGNMENTS_POSTGRES_URL
})

describe('shared config owner-service storage', () => {
  it('uses Postgres defaults with per-service overrides', () => {
    process.env.OWNER_SERVICES_POSTGRES_URL = 'postgresql://generic/generic'
    process.env.LEXICON_POSTGRES_SCHEMA = 'lexicon_custom'
    process.env.ASSIGNMENTS_POSTGRES_URL = 'postgresql://assignments/override'
    process.env.ASSIGNMENTS_POSTGRES_SCHEMA = 'assignments_custom'

    const config = loadConfig()

    expect(config.lexiconService.storageBackend).toBe('postgres')
    expect(config.lexiconService.postgresUrl).toBe('postgresql://generic/generic')
    expect(config.lexiconService.schemaName).toBe('lexicon_custom')

    expect(config.assignmentsService.storageBackend).toBe('postgres')
    expect(config.assignmentsService.postgresUrl).toBe('postgresql://assignments/override')
    expect(config.assignmentsService.schemaName).toBe('assignments_custom')
  })

  it('detects project root correctly when launched from a workspace package directory', () => {
    process.chdir(path.join(repoRoot, 'backend', 'services', 'api-gateway'))

    const config = loadConfig()

    expect(config.gateway.staticDir).toBe(path.join(repoRoot, 'frontend', 'dist'))
    expect(config.lexiconService.storageBackend).toBe('postgres')
    expect(config.assignmentsService.storageBackend).toBe('postgres')
  })
})
