import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  assertAssignmentScanResultContract,
  assertAssignmentsStatisticsContract,
  assertCategoryMutationResultContract,
  assertExportSnapshotContract,
  assertLexiconIndexContract,
  assertLexiconSearchResultContract,
  assertLexiconStatisticsContract,
  assertParseResultContract,
  assertRowSyncResultContract,
  assertWarmupStatusContract,
} from '../../../backend/services/shared/src/contracts.js'

afterEach(() => {
  vi.resetModules()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  delete process.env.LEXICON_SERVICE_HOST
  delete process.env.LEXICON_SERVICE_PORT
  delete process.env.NLP_SERVICE_HOST
  delete process.env.NLP_SERVICE_PORT
})

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

describe('internal contract validators', () => {
  it('validate lexicon-service internal payloads', async () => {
    class MockPostgresLexiconRepository {
      async searchEntries() {
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

      async addEntry() {
        return { message: 'ok' }
      }

      async updateEntry() {
        return { message: 'ok' }
      }

      async deleteEntries() {
        return { rows: [], message: 'ok' }
      }

      async bulkUpdateStatus() {
        return { rows: [], message: 'ok' }
      }

      async createCategory() {
        return { categories: ['Verb', 'Noun'], message: 'ok' }
      }

      async deleteCategory() {
        return { categories: ['Verb'], message: 'ok' }
      }

      async listCategories() {
        return ['Verb', 'Noun']
      }

      async syncRow() {
        return {
          status: 'added',
          value: 'walk',
          category: 'Verb',
          request_id: 'req-1',
          message: 'ok',
          category_fallback_used: false,
        }
      }

      async getStatistics() {
        return {
          total_entries: 1,
          counts_by_status: { approved: 1 },
          counts_by_source: { manual: 1 },
          categories: [{ name: 'Verb', count: 1 }],
        }
      }

      async buildIndex() {
        return {
          single_word_index: { run: ['Verb'] },
          multi_word_index: { 'fill in': ['Phrasal Verb'] },
          total_rows: 2,
          lexicon_version: 1,
        }
      }

      async exportSnapshot() {
        return {
          tables: [
            { name: 'lexicon_entries', columns: ['id'], rows: [[1]] },
          ],
        }
      }

      async upsertMweExpression() {
        return { expression_id: 1 }
      }

      async upsertMweSense() {
        return { sense_id: 1 }
      }

      async addEntries() {
        return { inserted_count: 1, message: 'ok' }
      }

      async close() {}
    }

    vi.doMock('../../../backend/services/lexicon-service/src/postgres_repository.js', () => ({
      PostgresLexiconRepository: MockPostgresLexiconRepository,
    }))

    const { buildLexiconServiceApp } = await import('../../../backend/services/lexicon-service/src/app.js')
    const app = buildLexiconServiceApp()
    try {
      await app.inject({ method: 'POST', url: '/internal/v1/lexicon/categories', payload: { name: 'Verb' } })
      await app.inject({
        method: 'POST',
        url: '/internal/v1/lexicon/entries',
        payload: { category: 'Verb', value: 'Run', source: 'manual', confidence: 1 },
      })

      const search = await app.inject({ method: 'GET', url: '/internal/v1/lexicon/search?status=all&limit=20&offset=0' })
      expect(() => assertLexiconSearchResultContract(search.json())).not.toThrow()

      const sync = await app.inject({
        method: 'POST',
        url: '/internal/v1/lexicon/sync-row',
        payload: { token: 'walked', normalized: 'walk', lemma: 'walk', categories: 'Verb' },
      })
      expect(() => assertRowSyncResultContract(sync.json())).not.toThrow()

      const stats = await app.inject({ method: 'GET', url: '/internal/v1/lexicon/statistics' })
      expect(() => assertLexiconStatisticsContract(stats.json())).not.toThrow()

      const index = await app.inject({ method: 'GET', url: '/internal/v1/lexicon/index' })
      expect(() => assertLexiconIndexContract(index.json())).not.toThrow()

      const snapshot = await app.inject({ method: 'GET', url: '/internal/v1/lexicon/export-snapshot' })
      expect(() => assertExportSnapshotContract(snapshot.json())).not.toThrow()

      const categories = await app.inject({ method: 'POST', url: '/internal/v1/lexicon/categories', payload: { name: 'Noun' } })
      expect(() => assertCategoryMutationResultContract(categories.json())).not.toThrow()
    } finally {
      await app.close()
    }
  })

  it('validate assignments-service internal payloads', async () => {
    process.env.LEXICON_SERVICE_HOST = 'lexicon-service'
    process.env.LEXICON_SERVICE_PORT = '4011'
    process.env.NLP_SERVICE_HOST = 'nlp-service'
    process.env.NLP_SERVICE_PORT = '8767'

    class MockPostgresAssignmentsRepository {
      async createUnit() {
        throw new Error('not used')
      }

      async listAssignments() {
        return []
      }

      async getAssignmentById() {
        return null
      }

      async getAssignmentsByIds() {
        return []
      }

      async updateAssignment() {
        return null
      }

      async deleteAssignment() {
        return false
      }

      async bulkDelete() {
        return { deleted: [], not_found: [] }
      }

      async getAssignmentsStatistics() {
        return {
          units: [],
          total_units: 0,
          total_subunits: 0,
          average_subunits_per_unit: null,
        }
      }

      async exportSnapshot() {
        return { tables: [] }
      }

      async isEmpty() {
        return true
      }

      async close() {}
    }

    vi.doMock('../../../backend/services/assignments-service/src/postgres_repository.js', () => ({
      PostgresAssignmentsRepository: MockPostgresAssignmentsRepository,
    }))

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/lexicon/search')) {
        return jsonResponse({
          rows: [
            {
              id: 1,
              category: 'Verb',
              value: 'run',
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
        })
      }
      if (url.includes('/internal/v1/nlp/extract-sentence')) {
        return jsonResponse({ sentence: 'I run every day.' })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }))

    const { buildAssignmentsServiceApp } = await import('../../../backend/services/assignments-service/src/app.js')
    const app = buildAssignmentsServiceApp()
    try {
      const scan = await app.inject({
        method: 'POST',
        url: '/internal/v1/assignments/scan',
        payload: {
          title: 'Essay',
          content_original: 'I walk',
          content_completed: 'I run',
        },
      })
      expect(() => assertAssignmentScanResultContract(scan.json())).not.toThrow()

      const stats = await app.inject({ method: 'GET', url: '/internal/v1/assignments/statistics' })
      expect(() => assertAssignmentsStatisticsContract(stats.json())).not.toThrow()
    } finally {
      await app.close()
    }
  })

  it('validate gateway-facing warmup and parse payload shapes', () => {
    const warmupPayload = {
      running: false,
      ready: true,
      failed: false,
      error_message: '',
      elapsed_sec: 1.2,
    }
    const parsePayload = {
      rows: [
        {
          index: 1,
          token: 'run',
          normalized: 'run',
          lemma: 'run',
          categories: 'Verb',
          source: 'manual',
          matched_form: 'run',
          confidence: '1.0',
          known: 'true',
        },
      ],
      summary: { total_tokens: 1 },
      status_message: 'ok',
      error_message: '',
    }

    expect(() => assertWarmupStatusContract(warmupPayload)).not.toThrow()
    expect(() => assertParseResultContract(parsePayload)).not.toThrow()
  })
})
