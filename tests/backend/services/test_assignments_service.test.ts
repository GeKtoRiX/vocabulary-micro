import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  assertAssignmentScanResultContract,
  assertAssignmentsStatisticsContract,
  assertQuickAddSuggestionContract,
  assertRowSyncResultContract,
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

function configureAssignmentsEnv() {
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
    if (url.includes('/internal/v1/lexicon/entries')) {
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

describe('assignments-service', () => {
  it('serves unit CRUD, quick-add, and scan flows through the Postgres repository contract', async () => {
    configureAssignmentsEnv()
    const fetchMock = stubAssignmentsFetch([
      { id: 1, category: 'Verb', value: 'run', normalized: 'run', source: 'manual', status: 'approved' },
    ])

    class MockPostgresAssignmentsRepository {
      private units: Array<{
        id: number
        unit_code: string
        unit_number: number
        subunit_count: number
        subunits: Array<{
          id: number
          unit_id: number
          subunit_code: string
          position: number
          content: string
          created_at: string
          updated_at: string
        }>
        created_at: string
        updated_at: string
      }> = []

      private nextId = 1

      async createUnit(input: { subunits: Array<{ content: string }> }) {
        const id = this.nextId++
        const createdAt = new Date('2026-03-11T00:00:00.000Z').toISOString()
        const unit = {
          id,
          unit_code: `Unit${String(id).padStart(2, '0')}`,
          unit_number: id,
          subunit_count: input.subunits.length,
          subunits: input.subunits.map((subunit, index) => ({
            id: index + 1,
            unit_id: id,
            subunit_code: `${id}${String.fromCharCode(65 + index)}`,
            position: index + 1,
            content: subunit.content,
            created_at: createdAt,
            updated_at: createdAt,
          })),
          created_at: createdAt,
          updated_at: createdAt,
        }
        this.units.unshift(unit)
        return unit
      }

      async listAssignments() {
        return this.units
      }

      async getAssignmentById(id: number) {
        return this.units.find((unit) => unit.id === id) ?? null
      }

      async getAssignmentsByIds(ids: number[]) {
        return this.units.filter((unit) => ids.includes(unit.id))
      }

      async updateAssignment(input: { assignment_id: number; subunits: Array<{ content: string }> }) {
        const unit = this.units.find((entry) => entry.id === input.assignment_id)
        if (!unit) {
          return null
        }
        unit.subunit_count = input.subunits.length
        unit.subunits = input.subunits.map((subunit, index) => ({
          id: index + 1,
          unit_id: unit.id,
          subunit_code: `${unit.unit_number}${String.fromCharCode(65 + index)}`,
          position: index + 1,
          content: subunit.content,
          created_at: unit.created_at,
          updated_at: unit.updated_at,
        }))
        return unit
      }

      async deleteAssignment(id: number) {
        const before = this.units.length
        this.units = this.units.filter((unit) => unit.id !== id)
        return this.units.length !== before
      }

      async bulkDelete(ids: number[]) {
        const deleted = this.units.filter((unit) => ids.includes(unit.id)).map((unit) => unit.id)
        this.units = this.units.filter((unit) => !ids.includes(unit.id))
        return {
          deleted,
          not_found: ids.filter((id) => !deleted.includes(id)),
        }
      }

      async getAssignmentsStatistics() {
        const totalUnits = this.units.length
        const totalSubunits = this.units.reduce((sum, unit) => sum + unit.subunit_count, 0)
        return {
          units: this.units.map((unit) => ({
            unit_code: unit.unit_code,
            subunit_count: unit.subunit_count,
            created_at: unit.created_at,
          })),
          total_units: totalUnits,
          total_subunits: totalSubunits,
          average_subunits_per_unit: totalUnits ? totalSubunits / totalUnits : null,
        }
      }

      async exportSnapshot() {
        return { tables: [] }
      }

      async isEmpty() {
        return this.units.length === 0
      }

      async close() {}
    }

    vi.doMock('../../../backend/services/assignments-service/src/postgres_repository.js', () => ({
      PostgresAssignmentsRepository: MockPostgresAssignmentsRepository,
    }))

    const { buildAssignmentsServiceApp } = await import('../../../backend/services/assignments-service/src/app.js')
    const app = buildAssignmentsServiceApp()
    try {
      const created = await app.inject({
        method: 'POST',
        url: '/assignments',
        payload: {
          subunits: [{ content: 'Unit 1A text' }, { content: 'Unit 1B text' }],
        },
      })
      expect(created.statusCode).toBe(201)
      expect(created.json().unit_code).toBe('Unit01')

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
      expect(() => assertQuickAddSuggestionContract(suggestion.json())).not.toThrow()

      const quickAdd = await app.inject({
        method: 'POST',
        url: '/assignments/quick-add',
        payload: {
          term: 'swiftly',
          content_completed: 'I run every day.',
          category: 'Verb',
          assignment_id: 1,
        },
      })
      expect(quickAdd.statusCode).toBe(200)
      expect(() => assertRowSyncResultContract(quickAdd.json())).not.toThrow()

      const updated = await app.inject({
        method: 'PUT',
        url: '/assignments/1',
        payload: {
          subunits: [{ content: 'Updated 1A' }, { content: 'Updated 1B' }, { content: 'Updated 1C' }],
        },
      })
      expect(updated.statusCode).toBe(200)
      expect(updated.json().subunits).toHaveLength(3)

      await app.inject({
        method: 'POST',
        url: '/assignments',
        payload: {
          subunits: [{ content: 'Unit 2A text' }],
        },
      })

      const stats = await app.inject({ method: 'GET', url: '/internal/v1/assignments/statistics' })
      expect(stats.statusCode).toBe(200)
      expect(() => assertAssignmentsStatisticsContract(stats.json())).not.toThrow()

      const scan = await app.inject({
        method: 'POST',
        url: '/internal/v1/assignments/scan',
        payload: {
          title: 'Essay',
          content_original: 'I walk',
          content_completed: 'I run every day.',
        },
      })
      expect(scan.statusCode).toBe(200)
      expect(() => assertAssignmentScanResultContract(scan.json())).not.toThrow()

      expect(
        fetchMock.mock.calls.filter(([input]) => String(input).includes('/internal/v1/lexicon/search')).length,
      ).toBeGreaterThan(0)
    } finally {
      await app.close()
    }
  })
})
