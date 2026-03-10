import { afterEach, describe, expect, it } from 'vitest'
import path from 'node:path'
import { loadConfig } from '../../services/shared/src/config.js'

const originalCwd = process.cwd()
const repoRoot = path.basename(originalCwd) === 'services' ? path.dirname(originalCwd) : originalCwd

afterEach(() => {
  process.chdir(originalCwd)
  delete process.env.OWNER_SERVICES_STORAGE_BACKEND
  delete process.env.OWNER_SERVICES_POSTGRES_URL
  delete process.env.OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE
  delete process.env.LEXICON_POSTGRES_SCHEMA
  delete process.env.LEXICON_STORAGE_BACKEND
  delete process.env.LEXICON_POSTGRES_URL
  delete process.env.LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE
  delete process.env.ASSIGNMENTS_POSTGRES_SCHEMA
  delete process.env.ASSIGNMENTS_STORAGE_BACKEND
  delete process.env.ASSIGNMENTS_POSTGRES_URL
  delete process.env.ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE
})

describe('shared config owner-service storage fallbacks', () => {
  it('supports generic postgres runtime toggles with per-service overrides', () => {
    process.env.OWNER_SERVICES_STORAGE_BACKEND = 'postgres'
    process.env.OWNER_SERVICES_POSTGRES_URL = 'postgresql://generic/generic'
    process.env.OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE = '1'
    process.env.LEXICON_STORAGE_BACKEND = 'sqlite'
    process.env.LEXICON_POSTGRES_SCHEMA = 'lexicon_custom'
    process.env.ASSIGNMENTS_POSTGRES_URL = 'postgresql://assignments/override'
    process.env.ASSIGNMENTS_POSTGRES_SCHEMA = 'assignments_custom'

    const config = loadConfig()

    expect(config.lexiconService.storageBackend).toBe('sqlite')
    expect(config.lexiconService.postgresUrl).toBe('postgresql://generic/generic')
    expect(config.lexiconService.bootstrapFromSqlite).toBe(true)
    expect(config.lexiconService.schemaName).toBe('lexicon_custom')

    expect(config.assignmentsService.storageBackend).toBe('postgres')
    expect(config.assignmentsService.postgresUrl).toBe('postgresql://assignments/override')
    expect(config.assignmentsService.bootstrapFromSqlite).toBe(true)
    expect(config.assignmentsService.schemaName).toBe('assignments_custom')
  })

  it('detects project root correctly when launched from a workspace package directory', () => {
    process.chdir(path.join(repoRoot, 'services', 'api-gateway'))

    const config = loadConfig()

    expect(config.gateway.staticDir).toBe(path.join(repoRoot, 'web', 'dist'))
    expect(config.lexiconDbPath).toBe(path.join(repoRoot, 'infrastructure', 'persistence', 'data', 'lexicon.sqlite3'))
    expect(config.assignmentsDbPath).toBe(path.join(repoRoot, 'infrastructure', 'persistence', 'data', 'assignments.db'))
  })
})
