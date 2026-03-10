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

async function createAssignment(app: ReturnType<typeof buildAssignmentsServiceApp>, title: string, contentCompleted: string) {
  const response = await app.inject({
    method: 'POST',
    url: '/internal/v1/assignments/scan',
    payload: {
      title,
      content_original: 'I walk',
      content_completed: contentCompleted,
    },
  })
  expect(response.statusCode).toBe(200)
  return response.json()
}

describe('assignments-service', () => {
  it('owns assignments CRUD, scan, quick-add and stats', async () => {
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
          title: 'Essay 1',
          content_original: 'I walk',
          content_completed: 'I run daily',
        },
      })
      expect(scan.statusCode).toBe(200)
      const scanPayload = scan.json()
      expect(scanPayload.assignment_id).toBeTypeOf('number')
      expect(scanPayload.word_count).toBe(3)
      expect(scanPayload.matches[0].term).toBe('run')

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
          assignment_id: scanPayload.assignment_id,
        },
      })
      expect(quickAdd.statusCode).toBe(200)
      expect(quickAdd.json().status).toBe('added')

      const update = await app.inject({
        method: 'PUT',
        url: `/internal/v1/assignments/${scanPayload.assignment_id}/update`,
        payload: {
          title: 'Essay 1',
          content_original: 'I walk',
          content_completed: 'I run',
        },
      })
      expect(update.statusCode).toBe(200)
      expect(update.json().assignment_id).toBe(scanPayload.assignment_id)

      const secondScan = await app.inject({
        method: 'POST',
        url: '/internal/v1/assignments/scan',
        payload: {
          title: 'Essay 2',
          content_original: 'I walk',
          content_completed: 'I run daily',
        },
      })
      expect(secondScan.statusCode).toBe(200)

      fetchMock.mockClear()
      const bulkRescan = await app.inject({
        method: 'POST',
        url: '/internal/v1/assignments/bulk-rescan',
        payload: {
          assignment_ids: [scanPayload.assignment_id, secondScan.json().assignment_id],
        },
      })
      expect(bulkRescan.statusCode).toBe(200)
      expect(bulkRescan.json().success_count).toBe(2)
      expect(
        fetchMock.mock.calls.filter(([input]) => String(input).includes('/internal/v1/lexicon/search')),
      ).toHaveLength(1)

      const stats = await app.inject({ method: 'GET', url: '/internal/v1/assignments/statistics' })
      expect(stats.statusCode).toBe(200)
      expect(stats.json().total_assignments).toBe(2)
    } finally {
      await app.close()
    }
  })

  it('bulk-delete returns correct counts', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'assignments-service-'))
    tempDirs.push(dir)
    configureAssignmentsEnv(dir)
    stubAssignmentsFetch([
      { id: 1, category: 'Verb', value: 'run', normalized: 'run', source: 'manual', status: 'approved' },
    ])

    const app = buildAssignmentsServiceApp()
    try {
      const first = await createAssignment(app, 'Essay 1', 'I run')
      const second = await createAssignment(app, 'Essay 2', 'I run daily')

      const bulkDelete = await app.inject({
        method: 'POST',
        url: '/assignments/bulk-delete',
        payload: { assignment_ids: [first.assignment_id, second.assignment_id, 999] },
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

  it('statistics computes average coverage correctly', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'assignments-service-'))
    tempDirs.push(dir)
    configureAssignmentsEnv(dir)
    stubAssignmentsFetch([
      { id: 1, category: 'Verb', value: 'run', normalized: 'run', source: 'manual', status: 'approved' },
      { id: 2, category: 'Adverb', value: 'daily', normalized: 'daily', source: 'manual', status: 'approved' },
    ])

    const app = buildAssignmentsServiceApp()
    try {
      await createAssignment(app, 'Full', 'run daily')
      await createAssignment(app, 'Half', 'run cat dog daily')

      const stats = await app.inject({ method: 'GET', url: '/internal/v1/assignments/statistics' })

      expect(stats.statusCode).toBe(200)
      expect(stats.json().average_assignment_coverage).toBe(75)
      expect(stats.json().total_assignments).toBe(2)
    } finally {
      await app.close()
    }
  })

  it('update re-runs scan with new content', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'assignments-service-'))
    tempDirs.push(dir)
    configureAssignmentsEnv(dir)
    stubAssignmentsFetch([
      { id: 1, category: 'Verb', value: 'run', normalized: 'run', source: 'manual', status: 'approved' },
    ])

    const app = buildAssignmentsServiceApp()
    try {
      const created = await createAssignment(app, 'Essay', 'jump high')
      expect(created.lexicon_coverage_percent).toBe(0)

      const updated = await app.inject({
        method: 'PUT',
        url: `/internal/v1/assignments/${created.assignment_id}/update`,
        payload: {
          title: 'Essay',
          content_original: 'I walk',
          content_completed: 'run',
        },
      })

      expect(updated.statusCode).toBe(200)
      expect(updated.json().lexicon_coverage_percent).toBe(100)
      expect(updated.json().assignment_status).toBe('COMPLETED')
    } finally {
      await app.close()
    }
  })
})
