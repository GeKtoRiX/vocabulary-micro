import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildAssignmentsServiceApp } from '../../../backend/services/assignments-service/src/app.js'

const tempDirs: string[] = []

afterEach(async () => {
  vi.unstubAllGlobals()
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true })
  }
  delete process.env.ASSIGNMENTS_DB_PATH
  delete process.env.ASSIGNMENTS_STORAGE_BACKEND
  delete process.env.ASSIGNMENTS_POSTGRES_URL
  delete process.env.ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE
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

function configureAssignmentsEnv(dir: string): void {
  process.env.ASSIGNMENTS_DB_PATH = path.join(dir, 'assignments.db')
  process.env.LEXICON_SERVICE_HOST = 'lexicon-service'
  process.env.LEXICON_SERVICE_PORT = '4011'
  process.env.NLP_SERVICE_HOST = 'nlp-service'
  process.env.NLP_SERVICE_PORT = '8767'
}

function makeLexiconRow(row: Record<string, unknown>): Record<string, unknown> {
  return {
    confidence: 1,
    first_seen_at: null,
    request_id: null,
    created_at: null,
    reviewed_at: null,
    reviewed_by: null,
    review_note: null,
    ...row,
  }
}

function stubAssignmentsFetch(lexiconRows: Array<Record<string, unknown>>) {
  const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/internal/v1/lexicon/search')) {
      return jsonResponse({
        rows: lexiconRows.map((row) => makeLexiconRow(row)),
        available_categories: ['Auto Added', 'Verb', 'Adverb', 'Noun', 'Phrasal Verb'],
        total_rows: lexiconRows.length,
        filtered_rows: lexiconRows.length,
        counts_by_status: { approved: lexiconRows.length },
        message: 'ok',
      })
    }
    if (url.includes('/lexicon/entries')) {
      return jsonResponse({ message: 'ok' })
    }
    if (url.includes('/internal/v1/nlp/extract-sentence')) {
      return jsonResponse({ sentence: 'I run every day.' })
    }
    throw new Error(`Unexpected fetch: ${url} ${init?.method ?? 'GET'}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function createUnit(app: ReturnType<typeof buildAssignmentsServiceApp>, subunits: string[]) {
  const response = await app.inject({
    method: 'POST',
    url: '/assignments',
    payload: {
      subunits: subunits.map((content) => ({ content })),
    },
  })
  expect(response.statusCode).toBe(201)
  return response.json()
}

describe('assignments-service', () => {
  it('owns unit CRUD, quick-add and unit statistics', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'assignments-service-'))
    tempDirs.push(dir)
    configureAssignmentsEnv(dir)
    stubAssignmentsFetch([
      { id: 1, category: 'Verb', value: 'run', normalized: 'run', source: 'manual', status: 'approved' },
    ])

    const app = buildAssignmentsServiceApp()
    try {
      const created = await createUnit(app, ['Unit 1A text', 'Unit 1B text'])
      expect(created.unit_code).toBe('Unit01')
      expect(created.subunits.map((item: { subunit_code: string }) => item.subunit_code)).toEqual(['1A', '1B'])

      const list = await app.inject({ method: 'GET', url: '/assignments' })
      expect(list.statusCode).toBe(200)
      expect(list.json()).toHaveLength(1)

      const suggestion = await app.inject({
        method: 'POST',
        url: '/assignments/suggest-category',
        payload: {
          term: 'running',
          content_completed: 'I run every day.',
          available_categories: ['Verb', 'Auto Added'],
        },
      })
      expect(suggestion.statusCode).toBe(200)
      expect(suggestion.json().recommended_category).toBe('Verb')

      const quickAdd = await app.inject({
        method: 'POST',
        url: '/assignments/quick-add',
        payload: {
          term: 'swiftly',
          content_completed: 'I run every day.',
          category: 'Verb',
          assignment_id: created.id,
        },
      })
      expect(quickAdd.statusCode).toBe(200)
      expect(quickAdd.json().status).toBe('added')

      const updated = await app.inject({
        method: 'PUT',
        url: `/assignments/${created.id}`,
        payload: {
          subunits: [{ content: 'Updated 1A' }, { content: 'Updated 1B' }, { content: 'Updated 1C' }],
        },
      })
      expect(updated.statusCode).toBe(200)
      expect(updated.json().subunits.map((item: { subunit_code: string }) => item.subunit_code)).toEqual(['1A', '1B', '1C'])

      await createUnit(app, ['Unit 2A text'])

      const stats = await app.inject({ method: 'GET', url: '/internal/v1/assignments/statistics' })
      expect(stats.statusCode).toBe(200)
      expect(stats.json()).toMatchObject({
        total_units: 2,
        total_subunits: 4,
        average_subunits_per_unit: 2,
      })
    } finally {
      await app.close()
    }
  })

  it('bulk-delete returns correct counts for units', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'assignments-service-'))
    tempDirs.push(dir)
    configureAssignmentsEnv(dir)
    stubAssignmentsFetch([
      { id: 1, category: 'Verb', value: 'run', normalized: 'run', source: 'manual', status: 'approved' },
    ])

    const app = buildAssignmentsServiceApp()
    try {
      const first = await createUnit(app, ['One'])
      const second = await createUnit(app, ['Two', 'Three'])

      const bulkDelete = await app.inject({
        method: 'POST',
        url: '/assignments/bulk-delete',
        payload: { assignment_ids: [first.id, second.id, 999] },
      })

      expect(bulkDelete.statusCode).toBe(200)
      expect(bulkDelete.json()).toMatchObject({
        success_count: 2,
        failed_count: 1,
      })

      const list = await app.inject({ method: 'GET', url: '/assignments' })
      expect(list.json()).toEqual([])
    } finally {
      await app.close()
    }
  })

  it('scan endpoint still returns contract payload without persisting units', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'assignments-service-'))
    tempDirs.push(dir)
    configureAssignmentsEnv(dir)
    const fetchMock = stubAssignmentsFetch([
      { id: 1, category: 'Verb', value: 'run', normalized: 'run', source: 'manual', status: 'approved' },
    ])

    const app = buildAssignmentsServiceApp()
    try {
      const scan = await app.inject({
        method: 'POST',
        url: '/internal/v1/assignments/scan',
        payload: {
          title: 'Legacy scan',
          content_original: 'I walk',
          content_completed: 'I run daily',
        },
      })

      expect(scan.statusCode).toBe(200)
      expect(scan.json().assignment_id).toBeNull()
      expect(scan.json().matches[0].term).toBe('run')

      const list = await app.inject({ method: 'GET', url: '/assignments' })
      expect(list.json()).toEqual([])

      const bulkRescan = await app.inject({
        method: 'POST',
        url: '/internal/v1/assignments/bulk-rescan',
        payload: { assignment_ids: [1, 2] },
      })
      expect(bulkRescan.json()).toMatchObject({ success_count: 0, failed_count: 2 })
      expect(
        fetchMock.mock.calls.filter(([input]) => String(input).includes('/internal/v1/lexicon/search')),
      ).toHaveLength(1)
    } finally {
      await app.close()
    }
  })
})
