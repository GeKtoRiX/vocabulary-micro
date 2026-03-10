import { afterEach, describe, expect, it } from 'vitest'
import { loadConfig } from '../../services/shared/src/config.js'

afterEach(() => {
  delete process.env.OWNER_SERVICES_STORAGE_BACKEND
  delete process.env.OWNER_SERVICES_POSTGRES_URL
  delete process.env.OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE
  delete process.env.LEXICON_STORAGE_BACKEND
  delete process.env.LEXICON_POSTGRES_URL
  delete process.env.LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE
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
    process.env.ASSIGNMENTS_POSTGRES_URL = 'postgresql://assignments/override'

    const config = loadConfig()

    expect(config.lexiconService.storageBackend).toBe('sqlite')
    expect(config.lexiconService.postgresUrl).toBe('postgresql://generic/generic')
    expect(config.lexiconService.bootstrapFromSqlite).toBe(true)

    expect(config.assignmentsService.storageBackend).toBe('postgres')
    expect(config.assignmentsService.postgresUrl).toBe('postgresql://assignments/override')
    expect(config.assignmentsService.bootstrapFromSqlite).toBe(true)
  })
})
