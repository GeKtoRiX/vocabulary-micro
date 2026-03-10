import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.resetModules()
  vi.restoreAllMocks()
  delete process.env.LEXICON_STORAGE_BACKEND
  delete process.env.LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE
  delete process.env.LEXICON_POSTGRES_URL
  delete process.env.LEXICON_DB_PATH
})

function createSearchPayload() {
  return {
    rows: [],
    total_rows: 0,
    filtered_rows: 0,
    counts_by_status: {},
    available_categories: [],
    message: 'ok',
  }
}

describe('lexicon bootstrap', () => {
  it('retries bootstrap after failure', async () => {
    const importSnapshot = vi.fn(async () => {
      if (importSnapshot.mock.calls.length === 1) {
        throw new Error('bootstrap failed once')
      }
    })

    class MockPostgresLexiconRepository {
      async isEmpty() {
        return true
      }
      async importSnapshot(snapshot: unknown) {
        return importSnapshot(snapshot)
      }
      async searchEntries() {
        return createSearchPayload()
      }
      async close() {}
    }

    class MockLexiconRepository {
      exportSnapshot() {
        return { tables: [] }
      }
      close() {}
    }

    vi.doMock('../../services/lexicon-service/src/postgres_repository.js', () => ({
      PostgresLexiconRepository: MockPostgresLexiconRepository,
    }))
    vi.doMock('../../services/lexicon-service/src/repository.js', async () => {
      const actual = await vi.importActual<typeof import('../../services/lexicon-service/src/repository.js')>(
        '../../services/lexicon-service/src/repository.js',
      )
      return {
        ...actual,
        LexiconRepository: MockLexiconRepository,
      }
    })

    process.env.LEXICON_STORAGE_BACKEND = 'postgres'
    process.env.LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE = '1'
    process.env.LEXICON_POSTGRES_URL = 'postgresql://unused'
    process.env.LEXICON_DB_PATH = '/tmp/unused.sqlite3'

    const { buildLexiconServiceApp } = await import('../../services/lexicon-service/src/app.js')
    const app = buildLexiconServiceApp()
    try {
      const first = await app.inject({ method: 'GET', url: '/lexicon/entries?status=all&limit=20&offset=0' })
      const second = await app.inject({ method: 'GET', url: '/lexicon/entries?status=all&limit=20&offset=0' })

      expect(first.statusCode).toBe(500)
      expect(second.statusCode).toBe(200)
      expect(importSnapshot).toHaveBeenCalledTimes(2)
    } finally {
      await app.close()
    }
  })

  it('runs bootstrap exactly once under concurrent load', async () => {
    const importSnapshot = vi.fn(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10))
    })

    class MockPostgresLexiconRepository {
      async isEmpty() {
        return true
      }
      async importSnapshot(snapshot: unknown) {
        return importSnapshot(snapshot)
      }
      async searchEntries() {
        return createSearchPayload()
      }
      async close() {}
    }

    class MockLexiconRepository {
      exportSnapshot() {
        return { tables: [] }
      }
      close() {}
    }

    vi.doMock('../../services/lexicon-service/src/postgres_repository.js', () => ({
      PostgresLexiconRepository: MockPostgresLexiconRepository,
    }))
    vi.doMock('../../services/lexicon-service/src/repository.js', async () => {
      const actual = await vi.importActual<typeof import('../../services/lexicon-service/src/repository.js')>(
        '../../services/lexicon-service/src/repository.js',
      )
      return {
        ...actual,
        LexiconRepository: MockLexiconRepository,
      }
    })

    process.env.LEXICON_STORAGE_BACKEND = 'postgres'
    process.env.LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE = '1'
    process.env.LEXICON_POSTGRES_URL = 'postgresql://unused'
    process.env.LEXICON_DB_PATH = '/tmp/unused.sqlite3'

    const { buildLexiconServiceApp } = await import('../../services/lexicon-service/src/app.js')
    const app = buildLexiconServiceApp()
    try {
      const responses = await Promise.all([
        app.inject({ method: 'GET', url: '/lexicon/entries?status=all&limit=20&offset=0' }),
        app.inject({ method: 'GET', url: '/lexicon/entries?status=all&limit=20&offset=0' }),
        app.inject({ method: 'GET', url: '/lexicon/entries?status=all&limit=20&offset=0' }),
        app.inject({ method: 'GET', url: '/lexicon/entries?status=all&limit=20&offset=0' }),
        app.inject({ method: 'GET', url: '/lexicon/entries?status=all&limit=20&offset=0' }),
      ])

      expect(responses.map((response) => response.statusCode)).toEqual([200, 200, 200, 200, 200])
      expect(importSnapshot).toHaveBeenCalledTimes(1)
    } finally {
      await app.close()
    }
  })
})
