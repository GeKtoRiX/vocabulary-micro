import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildAssignmentsServiceApp } from '../../services/assignments-service/src/app.js'

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

describe('assignments-service', () => {
  it('owns assignments CRUD, scan, quick-add and stats', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'assignments-service-'))
    tempDirs.push(dir)
    process.env.ASSIGNMENTS_DB_PATH = path.join(dir, 'assignments.db')
    process.env.LEXICON_SERVICE_HOST = 'lexicon-service'
    process.env.LEXICON_SERVICE_PORT = '4011'
    process.env.NLP_SERVICE_HOST = 'nlp-service'
    process.env.NLP_SERVICE_PORT = '8767'

    const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/internal/v1/lexicon/search')) {
        return new Response(JSON.stringify({
          rows: [
            { id: 1, category: 'Verb', value: 'run', normalized: 'run', source: 'manual', status: 'approved' },
          ],
          available_categories: ['Auto Added', 'Verb'],
        }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/lexicon/entries')) {
        return new Response(JSON.stringify({ message: 'ok' }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/internal/v1/nlp/extract-sentence')) {
        return new Response(JSON.stringify({ sentence: 'I run every day.' }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      throw new Error(`Unexpected fetch: ${url} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)

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

      const stats = await app.inject({ method: 'GET', url: '/internal/v1/assignments/statistics' })
      expect(stats.statusCode).toBe(200)
      expect(stats.json().total_assignments).toBe(1)
    } finally {
      await app.close()
    }
  })
})
