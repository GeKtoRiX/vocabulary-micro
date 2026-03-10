import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { buildLexiconServiceApp } from '../../services/lexicon-service/src/app.js'

const tempDirs: string[] = []

afterEach(async () => {
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true })
  }
  delete process.env.LEXICON_DB_PATH
})

describe('lexicon-service', () => {
  it('supports direct CRUD and sync-row against sqlite', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lexicon-service-'))
    tempDirs.push(dir)
    process.env.LEXICON_DB_PATH = path.join(dir, 'lexicon.sqlite3')

    const app = buildLexiconServiceApp()
    try {
      const createCategory = await app.inject({
        method: 'POST',
        url: '/lexicon/categories',
        payload: { name: 'Verb' },
      })
      expect(createCategory.statusCode).toBe(200)

      const addEntry = await app.inject({
        method: 'POST',
        url: '/lexicon/entries',
        payload: { category: 'Verb', value: 'Run', source: 'manual', confidence: 0.9 },
      })
      expect(addEntry.statusCode).toBe(200)

      const search = await app.inject({
        method: 'GET',
        url: '/lexicon/entries?status=all&limit=20&offset=0',
      })
      expect(search.statusCode).toBe(200)
      const searchPayload = search.json()
      expect(searchPayload.rows).toHaveLength(1)
      expect(searchPayload.rows[0].value).toBe('Run')
      expect(searchPayload.rows[0].normalized).toBe('run')

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
      expect(sync.json().status).toBe('added')

      const stats = await app.inject({
        method: 'GET',
        url: '/internal/v1/lexicon/statistics',
      })
      expect(stats.statusCode).toBe(200)
      expect(stats.json().total_entries).toBe(2)

      const snapshot = await app.inject({
        method: 'GET',
        url: '/internal/v1/lexicon/export-snapshot',
      })
      expect(snapshot.statusCode).toBe(200)
      expect(snapshot.json().tables.map((table: { name: string }) => table.name)).toEqual([
        'lexicon_entries',
        'lexicon_categories',
        'lexicon_meta',
        'mwe_expressions',
        'mwe_senses',
        'mwe_meta',
      ])

      const internalCategories = await app.inject({
        method: 'GET',
        url: '/internal/v1/lexicon/categories',
      })
      expect(internalCategories.statusCode).toBe(200)
      expect(internalCategories.json().categories).toContain('Verb')

      const mweExpression = await app.inject({
        method: 'POST',
        url: '/internal/v1/lexicon/mwe/expression',
        payload: {
          canonical_form: 'fill in',
          expression_type: 'phrasal_verb',
          is_separable: true,
          max_gap_tokens: 4,
          base_lemma: 'fill',
          particle: 'in',
        },
      })
      expect(mweExpression.statusCode).toBe(200)
      const expressionId = mweExpression.json().expression_id
      expect(expressionId).toBeTypeOf('number')

      const mweSense = await app.inject({
        method: 'POST',
        url: '/internal/v1/lexicon/mwe/sense',
        payload: {
          expression_id: expressionId,
          sense_key: 'fill_in_1',
          gloss: 'complete a form',
          usage_label: 'idiomatic',
          example: 'Fill in the form.',
          priority: 10,
        },
      })
      expect(mweSense.statusCode).toBe(200)
      expect(mweSense.json().sense_id).toBeTypeOf('number')

      const updatedSearch = await app.inject({
        method: 'GET',
        url: '/lexicon/entries?status=all&limit=20&offset=0&sort_by=id&sort_direction=asc',
      })
      const rows = updatedSearch.json().rows
      const syncRow = rows.find((row: { normalized: string }) => row.normalized === 'walk')
      expect(syncRow.status).toBe('pending_review')

      const update = await app.inject({
        method: 'PATCH',
        url: `/lexicon/entries/${syncRow.id}`,
        payload: {
          status: 'approved',
          category: 'Verb',
          value: 'walk',
          query: { status: 'all', limit: 20, offset: 0 },
        },
      })
      expect(update.statusCode).toBe(200)
      expect(update.json().message).toBe(`Updated entry id=${syncRow.id}.`)
    } finally {
      await app.close()
    }
  })
})
