import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  assertCategoryMutationResultContract,
  assertExportSnapshotContract,
  assertLexiconIndexContract,
  assertLexiconSearchResultContract,
  assertLexiconStatisticsContract,
  assertMweExpressionMutationContract,
  assertMweSenseMutationContract,
  assertRowSyncResultContract,
} from '../../../backend/services/shared/src/contracts.js'

afterEach(() => {
  vi.resetModules()
  vi.restoreAllMocks()
})

function createLexiconSearchPayload() {
  return {
    rows: [
      {
        id: 1,
        category: 'Verb',
        value: 'Run',
        normalized: 'run',
        source: 'manual',
        confidence: 1,
        first_seen_at: null,
        request_id: null,
        status: 'approved',
        created_at: null,
        reviewed_at: null,
        reviewed_by: null,
        review_note: null,
      },
    ],
    total_rows: 1,
    filtered_rows: 1,
    counts_by_status: { approved: 1 },
    available_categories: ['Verb'],
    message: 'ok',
  }
}

describe('lexicon-service', () => {
  it('serves Postgres-backed lexicon endpoints through the repository contract', async () => {
    const calls = {
      createCategory: vi.fn(async () => ({
        categories: ['Verb'],
        message: "Created category 'Verb'.",
      })),
      addEntry: vi.fn(async () => ({
        message: "Entry 'Run' added to 'Verb'.",
      })),
      searchEntries: vi.fn(async () => createLexiconSearchPayload()),
      syncRow: vi.fn(async () => ({
        status: 'added',
        value: 'walk',
        category: 'Verb',
        request_id: 'req-1',
        message: "Added 'walk'.",
        category_fallback_used: false,
      })),
      getStatistics: vi.fn(async () => ({
        total_entries: 1,
        counts_by_status: { approved: 1 },
        counts_by_source: { manual: 1 },
        categories: [{ name: 'Verb', count: 1 }],
      })),
      buildIndex: vi.fn(async () => ({
        single_word_index: { run: ['Verb'] },
        multi_word_index: { 'fill in': ['Phrasal Verb'] },
        total_rows: 2,
        lexicon_version: 1,
      })),
      exportSnapshot: vi.fn(async () => ({
        tables: [
          {
            name: 'lexicon_entries',
            columns: ['id'],
            rows: [[1]],
          },
        ],
      })),
      upsertMweExpression: vi.fn(async () => ({ expression_id: 7 })),
      upsertMweSense: vi.fn(async () => ({ sense_id: 9 })),
      close: vi.fn(async () => {}),
    }

    class MockPostgresLexiconRepository {
      searchEntries = calls.searchEntries
      addEntry = calls.addEntry
      addEntries = vi.fn()
      updateEntry = vi.fn()
      deleteEntries = vi.fn()
      bulkUpdateStatus = vi.fn()
      createCategory = calls.createCategory
      deleteCategory = vi.fn(async () => ({
        categories: [],
        message: "Deleted category 'Verb'.",
      }))
      listCategories = vi.fn(async () => ['Verb'])
      getStatistics = calls.getStatistics
      buildIndex = calls.buildIndex
      exportSnapshot = calls.exportSnapshot
      upsertMweExpression = calls.upsertMweExpression
      upsertMweSense = calls.upsertMweSense
      syncRow = calls.syncRow
      close = calls.close
    }

    vi.doMock('../../../backend/services/lexicon-service/src/postgres_repository.js', () => ({
      PostgresLexiconRepository: MockPostgresLexiconRepository,
    }))

    const { buildLexiconServiceApp } = await import('../../../backend/services/lexicon-service/src/app.js')
    const app = buildLexiconServiceApp()
    try {
      const createCategory = await app.inject({
        method: 'POST',
        url: '/internal/v1/lexicon/categories',
        payload: { name: 'Verb' },
      })
      expect(createCategory.statusCode).toBe(200)
      expect(() => assertCategoryMutationResultContract(createCategory.json())).not.toThrow()

      const addEntry = await app.inject({
        method: 'POST',
        url: '/internal/v1/lexicon/entries',
        payload: { category: 'Verb', value: 'Run', source: 'manual', confidence: 1 },
      })
      expect(addEntry.statusCode).toBe(200)

      const search = await app.inject({
        method: 'GET',
        url: '/internal/v1/lexicon/search?status=all&limit=20&offset=0',
      })
      expect(search.statusCode).toBe(200)
      expect(() => assertLexiconSearchResultContract(search.json())).not.toThrow()

      const sync = await app.inject({
        method: 'POST',
        url: '/internal/v1/lexicon/sync-row',
        payload: {
          token: 'walked',
          normalized: 'walk',
          lemma: 'walk',
          categories: 'Verb',
        },
      })
      expect(sync.statusCode).toBe(200)
      expect(() => assertRowSyncResultContract(sync.json())).not.toThrow()

      const stats = await app.inject({
        method: 'GET',
        url: '/internal/v1/lexicon/statistics',
      })
      expect(stats.statusCode).toBe(200)
      expect(() => assertLexiconStatisticsContract(stats.json())).not.toThrow()

      const index = await app.inject({
        method: 'GET',
        url: '/internal/v1/lexicon/index',
      })
      expect(index.statusCode).toBe(200)
      expect(() => assertLexiconIndexContract(index.json())).not.toThrow()

      const snapshot = await app.inject({
        method: 'GET',
        url: '/internal/v1/lexicon/export-snapshot',
      })
      expect(snapshot.statusCode).toBe(200)
      expect(() => assertExportSnapshotContract(snapshot.json())).not.toThrow()

      const expression = await app.inject({
        method: 'POST',
        url: '/internal/v1/lexicon/mwe/expression',
        payload: {
          canonical_form: 'fill in',
          expression_type: 'phrasal_verb',
        },
      })
      expect(expression.statusCode).toBe(200)
      expect(() => assertMweExpressionMutationContract(expression.json())).not.toThrow()

      const sense = await app.inject({
        method: 'POST',
        url: '/internal/v1/lexicon/mwe/sense',
        payload: {
          expression_id: 7,
          sense_key: 'fill_in_1',
          gloss: 'complete a form',
          usage_label: 'neutral',
        },
      })
      expect(sense.statusCode).toBe(200)
      expect(() => assertMweSenseMutationContract(sense.json())).not.toThrow()

      expect(calls.createCategory).toHaveBeenCalledWith({ name: 'Verb' })
      expect(calls.addEntry).toHaveBeenCalledWith({
        category: 'Verb',
        value: 'Run',
        source: 'manual',
        confidence: 1,
      })
      expect(calls.syncRow).toHaveBeenCalledWith({
        token: 'walked',
        normalized: 'walk',
        lemma: 'walk',
        categories: 'Verb',
      })
    } finally {
      await app.close()
    }

    expect(calls.close).toHaveBeenCalledTimes(1)
  })
})
