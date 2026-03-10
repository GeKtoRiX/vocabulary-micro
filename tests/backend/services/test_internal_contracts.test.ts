import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
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
import { buildAssignmentsServiceApp } from '../../../backend/services/assignments-service/src/app.js'
import { buildLexiconServiceApp } from '../../../backend/services/lexicon-service/src/app.js'

const tempDirs: string[] = []

function mkTempDb(prefix: string, filename: string): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix))
  tempDirs.push(dir)
  return path.join(dir, filename)
}

afterEach(() => {
  vi.unstubAllGlobals()
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true })
  }
  delete process.env.LEXICON_DB_PATH
  delete process.env.ASSIGNMENTS_DB_PATH
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
    process.env.LEXICON_DB_PATH = mkTempDb('lexicon-contract-', 'lexicon.sqlite3')

    const app = buildLexiconServiceApp()
    try {
      await app.inject({ method: 'POST', url: '/internal/v1/lexicon/categories', payload: { name: 'Verb' } })
      await app.inject({
        method: 'POST',
        url: '/internal/v1/lexicon/entries',
        payload: { category: 'Verb', value: 'Run', source: 'manual', confidence: 1 },
      })

      const search = await app.inject({ method: 'GET', url: '/internal/v1/lexicon/search?status=all&limit=20&offset=0' })
      const searchPayload = search.json()
      expect(() => assertLexiconSearchResultContract(searchPayload)).not.toThrow()

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
    process.env.ASSIGNMENTS_DB_PATH = mkTempDb('assignments-contract-', 'assignments.db')
    process.env.LEXICON_SERVICE_HOST = 'lexicon-service'
    process.env.LEXICON_SERVICE_PORT = '4011'
    process.env.NLP_SERVICE_HOST = 'nlp-service'
    process.env.NLP_SERVICE_PORT = '8767'

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
