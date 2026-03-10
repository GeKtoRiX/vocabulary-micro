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

  it('supports bulk-status, delete entries, category guards, and index building', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lexicon-service-'))
    tempDirs.push(dir)
    process.env.LEXICON_DB_PATH = path.join(dir, 'lexicon.sqlite3')

    const app = buildLexiconServiceApp()
    try {
      await app.inject({ method: 'POST', url: '/lexicon/categories', payload: { name: 'Verb' } })
      await app.inject({ method: 'POST', url: '/lexicon/categories', payload: { name: 'Phrasal Verb' } })

      await app.inject({
        method: 'POST',
        url: '/lexicon/entries',
        payload: { category: 'Verb', value: 'Run', source: 'manual', confidence: 0.9 },
      })
      await app.inject({
        method: 'POST',
        url: '/lexicon/entries',
        payload: { category: 'Verb', value: 'Jump', source: 'manual', confidence: 0.9 },
      })
      await app.inject({
        method: 'POST',
        url: '/lexicon/entries',
        payload: { category: 'Phrasal Verb', value: 'Fill In', source: 'manual', confidence: 0.9 },
      })

      const index = await app.inject({
        method: 'GET',
        url: '/internal/v1/lexicon/index',
      })
      expect(index.statusCode).toBe(200)
      expect(index.json().single_word_index.run).toContain('Verb')
      expect(index.json().multi_word_index['fill in']).toContain('Phrasal Verb')

      const search = await app.inject({
        method: 'GET',
        url: '/lexicon/entries?status=all&limit=20&offset=0&sort_by=id&sort_direction=asc',
      })
      const rows = search.json().rows
      const runId = rows.find((row: { normalized: string }) => row.normalized === 'run')?.id
      const jumpId = rows.find((row: { normalized: string }) => row.normalized === 'jump')?.id
      const fillInId = rows.find((row: { normalized: string }) => row.normalized === 'fill in')?.id

      const bulkStatus = await app.inject({
        method: 'POST',
        url: '/lexicon/entries/bulk-status',
        payload: {
          entry_ids: [runId, jumpId],
          status: 'rejected',
          query: { status: 'all', limit: 20, offset: 0 },
        },
      })
      expect(bulkStatus.statusCode).toBe(200)
      expect(bulkStatus.json().message).toContain("Updated 2 of 2 entries to 'rejected'")
      const updatedRows = bulkStatus.json().rows
      expect(updatedRows.find((row: { id: number }) => row.id === runId)?.status).toBe('rejected')
      expect(updatedRows.find((row: { id: number }) => row.id === jumpId)?.status).toBe('rejected')

      const deleteCategoryBlocked = await app.inject({
        method: 'DELETE',
        url: '/lexicon/categories/Verb',
      })
      expect(deleteCategoryBlocked.statusCode).toBe(200)
      expect(deleteCategoryBlocked.json().message).toContain("Delete category skipped: 'Verb' is used by 2 entries.")

      const deleteEntries = await app.inject({
        method: 'DELETE',
        url: '/lexicon/entries',
        payload: {
          entry_ids: [runId, jumpId],
          query: { status: 'all', limit: 20, offset: 0 },
        },
      })
      expect(deleteEntries.statusCode).toBe(200)
      expect(deleteEntries.json().rows.some((row: { id: number }) => row.id === runId)).toBe(false)
      expect(deleteEntries.json().rows.some((row: { id: number }) => row.id === jumpId)).toBe(false)
      expect(deleteEntries.json().rows.some((row: { id: number }) => row.id === fillInId)).toBe(true)

      const deleteCategoryAllowed = await app.inject({
        method: 'DELETE',
        url: '/lexicon/categories/Verb',
      })
      expect(deleteCategoryAllowed.statusCode).toBe(200)
      expect(deleteCategoryAllowed.json().message).toBe("Deleted category 'Verb'.")
      expect(deleteCategoryAllowed.json().categories).not.toContain('Verb')
    } finally {
      await app.close()
    }
  })
})
