/**
 * Комплексный E2E тест всех публичных маршрутов api-gateway.
 *
 * Каждый тест использует Fastify-инъекцию (app.inject) — реальный код gateway
 * запускается в памяти, downstream-сервисы замокированы через global fetch.
 *
 * Покрытые маршруты (те, что не дублируются в других test-файлах):
 *   GET  /api/system/warmup
 *   POST /api/parse/sync-row
 *   GET  /api/lexicon/entries          (с query-параметрами)
 *   POST /api/lexicon/entries
 *   PATCH /api/lexicon/entries/:id
 *   DELETE /api/lexicon/entries
 *   POST /api/lexicon/entries/bulk-status
 *   POST /api/lexicon/categories
 *   GET  /api/lexicon/export           (успешный путь)
 *   GET  /api/assignments
 *   GET  /api/assignments/:id
 *   DELETE /api/assignments/:id
 *   POST /api/assignments/bulk-delete
 *   POST /api/assignments/quick-add
 *   POST /api/assignments/suggest-category
 *   PUT  /api/assignments/:id          (SSE update-stream)
 *   POST /api/assignments/bulk-rescan  (SSE stream)
 *   GET  /api/parse/jobs/:id/stream    (несуществующий jobId)
 *   Заголовок x-request-id пробрасывается вниз
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildGatewayApp } from '../../../backend/services/api-gateway/src/app.js'

// ─── helpers ─────────────────────────────────────────────────────────────────

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function parseSseFrames(raw: string): Array<Record<string, unknown>> {
  return raw
    .split('\n\n')
    .map((f) => f.trim())
    .filter(Boolean)
    .map((f) => f.replace(/^data:\s*/, ''))
    .map((f) => JSON.parse(f) as Record<string, unknown>)
}

// Переменные окружения, нужные каждому тесту
const ENV_KEYS = [
  'GATEWAY_SERVE_STATIC',
  'GATEWAY_PARSE_BACKEND',
  'GATEWAY_LEXICON_BACKEND',
  'GATEWAY_ASSIGNMENTS_BACKEND',
  'GATEWAY_STATISTICS_BACKEND',
  'GATEWAY_EXPORT_BACKEND',
  'NLP_SERVICE_HOST', 'NLP_SERVICE_PORT',
  'LEXICON_SERVICE_HOST', 'LEXICON_SERVICE_PORT',
  'ASSIGNMENTS_SERVICE_HOST', 'ASSIGNMENTS_SERVICE_PORT',
  'EXPORT_SERVICE_HOST', 'EXPORT_SERVICE_PORT',
]

function setupEnv(overrides: Record<string, string> = {}) {
  const defaults: Record<string, string> = {
    GATEWAY_SERVE_STATIC: '0',
    GATEWAY_PARSE_BACKEND: 'nlp',
    GATEWAY_LEXICON_BACKEND: 'service',
    GATEWAY_ASSIGNMENTS_BACKEND: 'service',
    GATEWAY_STATISTICS_BACKEND: 'composed',
    GATEWAY_EXPORT_BACKEND: 'service',
    NLP_SERVICE_HOST: 'nlp-host', NLP_SERVICE_PORT: '8767',
    LEXICON_SERVICE_HOST: 'lexicon-host', LEXICON_SERVICE_PORT: '4011',
    ASSIGNMENTS_SERVICE_HOST: 'assignments-host', ASSIGNMENTS_SERVICE_PORT: '4012',
    EXPORT_SERVICE_HOST: 'export-host', EXPORT_SERVICE_PORT: '8768',
  }
  Object.assign(process.env, { ...defaults, ...overrides })
}

afterEach(() => {
  vi.unstubAllGlobals()
  for (const key of ENV_KEYS) delete process.env[key]
})

// ─── данные-фикстуры ──────────────────────────────────────────────────────────

const WARMUP_OK = { running: false, ready: true, failed: false, error_message: '', elapsed_sec: 1.5 }

const PARSE_RESULT = {
  rows: [
    { index: 1, token: 'run', normalized: 'run', lemma: 'run',
      categories: 'Verb', source: 'lexicon-service', matched_form: 'run',
      confidence: '1.0', known: 'true' },
    { index: 2, token: 'fast', normalized: 'fast', lemma: 'fast',
      categories: '-', source: 'none', matched_form: '',
      confidence: '', known: 'false' },
  ],
  summary: { total_tokens: 2 },
  status_message: 'Parse complete.',
  error_message: '',
}

const SYNC_ROW_RESULT = {
  status: 'added',
  value: 'run',
  category: 'Verb',
  request_id: 'req-123',
  message: "Row sync added 'run' to category 'Verb'.",
  category_fallback_used: false,
}

const LEXICON_ENTRY_LIST = {
  rows: [
    { id: 1, category: 'Verb', value: 'run', normalized: 'run',
      source: 'manual', confidence: 1.0, first_seen_at: null,
      request_id: null, status: 'approved', created_at: '2026-01-01T00:00:00.000Z',
      reviewed_at: null, reviewed_by: null, review_note: null },
  ],
  total_rows: 1,
  filtered_rows: 1,
  counts_by_status: { approved: 1 },
  available_categories: ['Verb'],
  message: 'ok',
}

const ASSIGNMENT_SCAN_RESULT = {
  assignment_id: 7,
  title: 'Essay',
  content_original: 'I walk',
  content_completed: 'I run',
  word_count: 2,
  known_token_count: 1,
  unknown_token_count: 1,
  lexicon_coverage_percent: 50.0,
  assignment_status: 'PENDING',
  message: 'Scan complete.',
  duration_ms: 10.0,
  matches: [{ entry_id: 1, term: 'run', category: 'Verb', source: 'manual', occurrences: 1 }],
  missing_words: [{ term: 'i', occurrences: 1, example_usage: 'I run' }],
  diff_chunks: [{ operation: 'replace', original_text: 'walk', completed_text: 'run' }],
}

const BULK_RESCAN_RESULT = {
  success_count: 2,
  failed_count: 0,
  message: 'Bulk rescan completed: 2 succeeded, 0 failed.',
}

// ─── тесты: система ──────────────────────────────────────────────────────────

describe('api-gateway e2e: system', () => {
  it('GET /api/system/warmup forwards to NLP service and returns warmup shape', async () => {
    setupEnv()
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/system/warmup')) {
        return jsonResponse(WARMUP_OK)
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({ method: 'GET', url: '/api/system/warmup' })
      expect(res.statusCode).toBe(200)
      const body = res.json()
      expect(body.ready).toBe(true)
      expect(body.failed).toBe(false)
      expect(typeof body.elapsed_sec).toBe('number')
    } finally {
      await app.close()
    }
  })

  it('GET /api/system/warmup returns 502 when NLP service unreachable', async () => {
    setupEnv()
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('connect ECONNREFUSED nlp-host')
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({ method: 'GET', url: '/api/system/warmup' })
      expect(res.statusCode).toBe(502)
      expect(res.json().detail).toContain('ECONNREFUSED')
    } finally {
      await app.close()
    }
  })
})

// ─── тесты: parse ─────────────────────────────────────────────────────────────

describe('api-gateway e2e: parse', () => {
  it('POST /api/parse → SSE stream contains progress, result with categories, and done', async () => {
    setupEnv()
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      if (String(input).includes('/internal/v1/nlp/parse')) {
        return jsonResponse(PARSE_RESULT)
      }
      throw new Error(`Unexpected: ${String(input)}`)
    }))

    const app = buildGatewayApp()
    try {
      const start = await app.inject({
        method: 'POST',
        url: '/api/parse',
        payload: { text: 'run fast' },
      })
      expect(start.statusCode).toBe(200)
      const { job_id } = start.json() as { job_id: string }
      expect(typeof job_id).toBe('string')
      expect(job_id.length).toBeGreaterThan(0)

      const stream = await app.inject({
        method: 'GET',
        url: `/api/parse/jobs/${job_id}/stream`,
      })
      expect(stream.statusCode).toBe(200)
      const frames = parseSseFrames(stream.body)

      // Обязательная последовательность: progress → stage_progress → result → done
      expect(frames[0]).toMatchObject({ type: 'progress' })
      expect(frames[1]).toMatchObject({ type: 'stage_progress', stage: 'nlp', status: 'done' })
      const resultFrame = frames.find((f) => f.type === 'result')
      expect(resultFrame).toBeDefined()
      expect(Array.isArray((resultFrame as { rows: unknown[] }).rows)).toBe(true)
      const rows = (resultFrame as { rows: Array<{ categories: string }> }).rows
      expect(rows[0].categories).toBe('Verb')
      expect(frames[frames.length - 1]).toMatchObject({ type: 'done' })
    } finally {
      await app.close()
    }
  })

  it('POST /api/parse with third_pass_enabled runs third-pass and merges summary', async () => {
    setupEnv()
    const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/internal/v1/nlp/parse')) {
        expect(JSON.parse(String(init?.body ?? '{}'))).toMatchObject({
          text: 'run fast',
          third_pass_enabled: false,
        })
        return jsonResponse(PARSE_RESULT)
      }
      if (url.includes('/internal/v1/nlp/third-pass')) {
        expect(JSON.parse(String(init?.body ?? '{}'))).toMatchObject({
          text: 'run fast',
          request_id: expect.any(String),
          think_mode: true,
          enabled: true,
        })
        return jsonResponse({
          status: 'ok',
          reason: '',
          occurrences: [{ surface: 'run fast' }],
        })
      }
      throw new Error(`Unexpected: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    const app = buildGatewayApp()
    try {
      const start = await app.inject({
        method: 'POST',
        url: '/api/parse',
        payload: { text: 'run fast', third_pass_enabled: true, think_mode: true },
      })
      const { job_id } = start.json() as { job_id: string }

      const stream = await app.inject({
        method: 'GET',
        url: `/api/parse/jobs/${job_id}/stream`,
      })
      const frames = parseSseFrames(stream.body)

      expect(frames).toContainEqual({ type: 'stage_progress', stage: 'nlp', status: 'done' })
      expect(frames).toContainEqual({
        type: 'stage_progress',
        stage: 'llm',
        status: 'done',
        llm_summary: {
          status: 'ok',
          reason: '',
          occurrences: [{ surface: 'run fast' }],
        },
      })
      const resultFrame = frames.find((frame) => frame.type === 'result') as Record<string, unknown>
      expect(resultFrame.summary).toMatchObject({
        total_tokens: 2,
        third_pass_summary: {
          status: 'ok',
          occurrences: [{ surface: 'run fast' }],
        },
      })
    } finally {
      await app.close()
    }
  })

  it('POST /api/parse/sync-row forwards to lexicon-service and proxies result', async () => {
    setupEnv()
    let capturedUrl = ''
    let capturedBody: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      capturedUrl = String(input)
      if (capturedUrl.includes('/internal/v1/lexicon/sync-row')) {
        capturedBody = JSON.parse(String(init?.body ?? '{}'))
        return jsonResponse(SYNC_ROW_RESULT)
      }
      throw new Error(`Unexpected: ${capturedUrl}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({
        method: 'POST',
        url: '/api/parse/sync-row',
        payload: { token: 'ran', normalized: 'run', lemma: 'run', categories: 'Verb' },
      })
      expect(res.statusCode).toBe(200)
      expect(capturedUrl).toContain('lexicon-host')
      expect(capturedUrl).toContain('/internal/v1/lexicon/sync-row')
      expect((capturedBody as { token: string }).token).toBe('ran')
      const body = res.json()
      expect(body.status).toBe('added')
      expect(body.category).toBe('Verb')
    } finally {
      await app.close()
    }
  })

  it('GET /api/parse/jobs/:id/stream for unknown jobId returns "Job not found" error', async () => {
    setupEnv()

    const app = buildGatewayApp()
    try {
      const stream = await app.inject({
        method: 'GET',
        url: '/api/parse/jobs/nonexistent-job-id/stream',
      })
      expect(stream.statusCode).toBe(200)
      const frames = parseSseFrames(stream.body)
      expect(frames.some((f) => f.type === 'error' && String(f.message).includes('Job not found'))).toBe(true)
    } finally {
      await app.close()
    }
  })
})

// ─── тесты: lexicon CRUD (через gateway) ─────────────────────────────────────

describe('api-gateway e2e: lexicon routes', () => {
  it('GET /api/lexicon/entries forwards query params to lexicon-service', async () => {
    setupEnv()
    let capturedUrl = ''
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      capturedUrl = String(input)
      if (capturedUrl.includes('/lexicon/entries')) {
        return jsonResponse(LEXICON_ENTRY_LIST)
      }
      throw new Error(`Unexpected: ${capturedUrl}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({
        method: 'GET',
        url: '/api/lexicon/entries?status=approved&limit=10&offset=0&category_filter=Verb',
      })
      expect(res.statusCode).toBe(200)
      expect(capturedUrl).toContain('lexicon-host')
      expect(capturedUrl).toContain('status=approved')
      expect(capturedUrl).toContain('limit=10')
      expect(capturedUrl).toContain('category_filter=Verb')
      expect(res.json().rows).toHaveLength(1)
      expect(res.json().rows[0].value).toBe('run')
    } finally {
      await app.close()
    }
  })

  it('POST /api/lexicon/entries forwards body to lexicon-service', async () => {
    setupEnv()
    let capturedBody: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/lexicon/entries')) {
        capturedBody = JSON.parse(String(init?.body ?? '{}'))
        return jsonResponse({ id: 42, message: 'Entry created.' })
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({
        method: 'POST',
        url: '/api/lexicon/entries',
        payload: { category: 'Verb', value: 'sprint', source: 'manual', confidence: 0.9 },
      })
      expect(res.statusCode).toBe(200)
      expect((capturedBody as { category: string }).category).toBe('Verb')
      expect((capturedBody as { value: string }).value).toBe('sprint')
    } finally {
      await app.close()
    }
  })

  it('PATCH /api/lexicon/entries/:id interpolates entryId and forwards body', async () => {
    setupEnv()
    let capturedUrl = ''
    let capturedBody: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      capturedUrl = String(input)
      if (capturedUrl.includes('/lexicon/entries/')) {
        capturedBody = JSON.parse(String(init?.body ?? '{}'))
        return jsonResponse({ message: 'Updated entry id=42.' })
      }
      throw new Error(`Unexpected: ${capturedUrl}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({
        method: 'PATCH',
        url: '/api/lexicon/entries/42',
        payload: { status: 'approved', category: 'Verb', value: 'run' },
      })
      expect(res.statusCode).toBe(200)
      expect(capturedUrl).toContain('/lexicon/entries/42')
      expect((capturedBody as { status: string }).status).toBe('approved')
    } finally {
      await app.close()
    }
  })

  it('DELETE /api/lexicon/entries forwards bulk-delete body to lexicon-service', async () => {
    setupEnv()
    let capturedBody: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/lexicon/entries') && init?.method === 'DELETE') {
        capturedBody = JSON.parse(String(init?.body ?? '{}'))
        return jsonResponse({ rows: [], message: 'Deleted 2 entries.' })
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({
        method: 'DELETE',
        url: '/api/lexicon/entries',
        payload: { entry_ids: [1, 2], query: { status: 'all', limit: 20, offset: 0 } },
      })
      expect(res.statusCode).toBe(200)
      expect((capturedBody as { entry_ids: number[] }).entry_ids).toEqual([1, 2])
    } finally {
      await app.close()
    }
  })

  it('POST /api/lexicon/entries/bulk-status forwards ids and new status', async () => {
    setupEnv()
    let capturedBody: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/lexicon/entries/bulk-status')) {
        capturedBody = JSON.parse(String(init?.body ?? '{}'))
        return jsonResponse({ rows: [], message: "Updated 2 of 2 entries to 'approved'." })
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({
        method: 'POST',
        url: '/api/lexicon/entries/bulk-status',
        payload: { entry_ids: [3, 5], status: 'approved', query: {} },
      })
      expect(res.statusCode).toBe(200)
      expect((capturedBody as { status: string }).status).toBe('approved')
      expect((capturedBody as { entry_ids: number[] }).entry_ids).toEqual([3, 5])
    } finally {
      await app.close()
    }
  })

  it('POST /api/lexicon/categories forwards category name to lexicon-service', async () => {
    setupEnv()
    let capturedBody: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/lexicon/categories')) {
        capturedBody = JSON.parse(String(init?.body ?? '{}'))
        return jsonResponse({ categories: ['Verb', 'Adverb'], message: "Created category 'Adverb'." })
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({
        method: 'POST',
        url: '/api/lexicon/categories',
        payload: { name: 'Adverb' },
      })
      expect(res.statusCode).toBe(200)
      expect((capturedBody as { name: string }).name).toBe('Adverb')
      expect(res.json().categories).toContain('Adverb')
    } finally {
      await app.close()
    }
  })

  it('GET /api/lexicon/export proxies binary response from export-service', async () => {
    setupEnv()
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/export/lexicon.xlsx')) {
        return new Response(Buffer.from('PK\x03\x04'), {
          status: 200,
          headers: {
            'content-type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'content-disposition': 'attachment; filename="lexicon.xlsx"',
          },
        })
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({ method: 'GET', url: '/api/lexicon/export' })
      expect(res.statusCode).toBe(200)
      expect(res.headers['content-type']).toContain('spreadsheetml')
    } finally {
      await app.close()
    }
  })
})

// ─── тесты: assignments CRUD (через gateway) ─────────────────────────────────

describe('api-gateway e2e: assignments routes', () => {
  it('GET /api/assignments forwards to assignments-service and returns list', async () => {
    setupEnv()
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/assignments') && !url.includes('scan') && !url.includes('bulk')) {
        return jsonResponse([
          {
            id: 1,
            unit_code: 'Unit01',
            unit_number: 1,
            subunit_count: 2,
            subunits: [],
            created_at: '2026-03-10T00:00:00Z',
            updated_at: '2026-03-10T00:00:00Z',
          },
        ])
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({ method: 'GET', url: '/api/assignments' })
      expect(res.statusCode).toBe(200)
      const body = res.json()
      expect(Array.isArray(body)).toBe(true)
      expect(body[0].unit_code).toBe('Unit01')
    } finally {
      await app.close()
    }
  })

  it('POST /api/assignments forwards unit payload to assignments-service', async () => {
    setupEnv()
    let capturedBody: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/assignments') && init?.method === 'POST') {
        capturedBody = JSON.parse(String(init.body ?? '{}'))
        return jsonResponse({
          id: 2,
          unit_code: 'Unit02',
          unit_number: 2,
          subunit_count: 2,
          subunits: [],
          created_at: '2026-03-10T01:00:00Z',
          updated_at: '2026-03-10T01:00:00Z',
        })
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({
        method: 'POST',
        url: '/api/assignments',
        payload: { subunits: [{ content: 'A' }, { content: 'B' }] },
      })
      expect(res.statusCode).toBe(200)
      expect((capturedBody as { subunits: Array<{ content: string }> }).subunits).toEqual([{ content: 'A' }, { content: 'B' }])
      expect(res.json().unit_code).toBe('Unit02')
    } finally {
      await app.close()
    }
  })

  it('GET /api/assignments/:id interpolates id and proxies result', async () => {
    setupEnv()
    let capturedUrl = ''
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      capturedUrl = String(input)
      if (capturedUrl.match(/\/assignments\/\d+$/)) {
        return jsonResponse({
          id: 5,
          unit_code: 'Unit05',
          unit_number: 5,
          subunit_count: 1,
          subunits: [{ id: 51, unit_id: 5, subunit_code: '5A', position: 0, content: 'Body', created_at: null, updated_at: null }],
          created_at: '2026-03-10T00:00:00Z',
          updated_at: '2026-03-10T00:00:00Z',
        })
      }
      throw new Error(`Unexpected: ${capturedUrl}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({ method: 'GET', url: '/api/assignments/5' })
      expect(res.statusCode).toBe(200)
      expect(capturedUrl).toContain('/assignments/5')
      expect(res.json().id).toBe(5)
    } finally {
      await app.close()
    }
  })

  it('DELETE /api/assignments/:id interpolates id and proxies result', async () => {
    setupEnv()
    let capturedUrl = ''
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      capturedUrl = String(input)
      if (init?.method === 'DELETE' && capturedUrl.match(/\/assignments\/\d+$/)) {
        return jsonResponse({ deleted: true, message: 'Unit deleted.' })
      }
      throw new Error(`Unexpected: ${capturedUrl}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({ method: 'DELETE', url: '/api/assignments/3' })
      expect(res.statusCode).toBe(200)
      expect(capturedUrl).toContain('/assignments/3')
    } finally {
      await app.close()
    }
  })

  it('POST /api/assignments/bulk-delete forwards ids to assignments-service', async () => {
    setupEnv()
    let capturedBody: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/assignments/bulk-delete')) {
        capturedBody = JSON.parse(String(init?.body ?? '{}'))
        return jsonResponse({ success_count: 2, failed_count: 0, message: 'Deleted 2.' })
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({
        method: 'POST',
        url: '/api/assignments/bulk-delete',
        payload: { assignment_ids: [1, 2] },
      })
      expect(res.statusCode).toBe(200)
      expect((capturedBody as { assignment_ids: number[] }).assignment_ids).toEqual([1, 2])
    } finally {
      await app.close()
    }
  })

  it('POST /api/assignments/quick-add forwards body to assignments-service', async () => {
    setupEnv()
    let capturedBody: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/assignments/quick-add')) {
        capturedBody = JSON.parse(String(init?.body ?? '{}'))
        return jsonResponse({ status: 'added', message: "Added 'sprint' to 'Verb'." })
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({
        method: 'POST',
        url: '/api/assignments/quick-add',
        payload: { term: 'sprint', category: 'Verb', assignment_id: 7 },
      })
      expect(res.statusCode).toBe(200)
      expect((capturedBody as { term: string }).term).toBe('sprint')
    } finally {
      await app.close()
    }
  })

  it('POST /api/assignments/suggest-category forwards to assignments-service', async () => {
    setupEnv()
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/assignments/suggest-category')) {
        return jsonResponse({
          term: 'running',
          recommended_category: 'Verb',
          candidate_categories: ['Verb', 'Noun'],
          confidence: 0.9,
          rationale: 'running is typically used as a Verb',
          suggested_example_usage: 'I am running every day.',
        })
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const res = await app.inject({
        method: 'POST',
        url: '/api/assignments/suggest-category',
        payload: { term: 'running', content_completed: 'I run every day.', available_categories: ['Verb', 'Noun'] },
      })
      expect(res.statusCode).toBe(200)
      expect(res.json().recommended_category).toBe('Verb')
      expect(res.json().confidence).toBeGreaterThan(0)
    } finally {
      await app.close()
    }
  })
})

// ─── тесты: assignments mutation routes + bulk-rescan SSE ─────────────────────

describe('api-gateway e2e: assignment SSE jobs', () => {
  it('PUT /api/assignments/:id proxies unit update synchronously', async () => {
    setupEnv()
    let capturedBody: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/assignments/7') && init?.method === 'PUT') {
        capturedBody = JSON.parse(String(init.body ?? '{}'))
        return jsonResponse({
          id: 7,
          unit_code: 'Unit07',
          unit_number: 7,
          subunit_count: 2,
          subunits: [],
          created_at: '2026-03-10T00:00:00Z',
          updated_at: '2026-03-10T02:00:00Z',
        })
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const response = await app.inject({
        method: 'PUT',
        url: '/api/assignments/7',
        payload: { subunits: [{ content: 'Updated A' }, { content: 'Updated B' }] },
      })
      expect(response.statusCode).toBe(200)
      expect((capturedBody as { subunits: Array<{ content: string }> }).subunits).toEqual([
        { content: 'Updated A' },
        { content: 'Updated B' },
      ])
      expect(response.json().unit_code).toBe('Unit07')
    } finally {
      await app.close()
    }
  })

  it('PUT /api/assignments/:id correctly interpolates assignmentId in service URL', async () => {
    setupEnv()
    let capturedUrl = ''
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      capturedUrl = String(input)
      if (capturedUrl.includes('/assignments/42') && init?.method === 'PUT') {
        return jsonResponse({
          id: 42,
          unit_code: 'Unit42',
          unit_number: 42,
          subunit_count: 1,
          subunits: [],
          created_at: '2026-03-10T00:00:00Z',
          updated_at: '2026-03-10T02:00:00Z',
        })
      }
      throw new Error(`Unexpected: ${capturedUrl}`)
    }))

    const app = buildGatewayApp()
    try {
      const response = await app.inject({
        method: 'PUT',
        url: '/api/assignments/42',
        payload: { subunits: [{ content: 'b' }] },
      })
      expect(response.statusCode).toBe(200)
      expect(capturedUrl).toContain('/assignments/42')
    } finally {
      await app.close()
    }
  })

  it('POST /api/assignments/bulk-rescan → SSE stream with progress, result, done', async () => {
    setupEnv()
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/assignments/bulk-rescan')) {
        return jsonResponse(BULK_RESCAN_RESULT)
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const start = await app.inject({
        method: 'POST',
        url: '/api/assignments/bulk-rescan',
        payload: { assignment_ids: [1, 2] },
      })
      expect(start.statusCode).toBe(200)
      const { job_id } = start.json() as { job_id: string }

      const stream = await app.inject({
        method: 'GET',
        url: `/api/assignments/scan/jobs/${job_id}/stream`,
      })
      const frames = parseSseFrames(stream.body)

      expect(frames[0]).toMatchObject({ type: 'progress', message: 'Rescanning assignments...' })
      const resultFrame = frames.find((f) => f.type === 'result')
      expect(resultFrame).toBeDefined()
      expect((resultFrame as { success_count: number }).success_count).toBe(2)
      expect(frames[frames.length - 1]).toMatchObject({ type: 'done' })
    } finally {
      await app.close()
    }
  })

  it('POST /api/assignments/bulk-rescan emits error frame when service unavailable', async () => {
    setupEnv()
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.includes('/internal/v1/assignments/bulk-rescan')) {
        throw new Error('connect ECONNREFUSED assignments-host')
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      const start = await app.inject({
        method: 'POST',
        url: '/api/assignments/bulk-rescan',
        payload: { assignment_ids: [1, 2] },
      })
      const { job_id } = start.json() as { job_id: string }

      const stream = await app.inject({
        method: 'GET',
        url: `/api/assignments/scan/jobs/${job_id}/stream`,
      })
      const frames = parseSseFrames(stream.body)
      expect(frames.some((f) => f.type === 'error')).toBe(true)
      expect(JSON.stringify(frames)).toContain('ECONNREFUSED')
    } finally {
      await app.close()
    }
  })
})

// ─── тесты: заголовок x-request-id ───────────────────────────────────────────

describe('api-gateway e2e: request ID propagation', () => {
  it('forwards x-request-id to lexicon-service', async () => {
    setupEnv()
    let capturedReqId = ''
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/lexicon/entries')) {
        capturedReqId = new Headers(init?.headers).get('x-request-id') ?? ''
        return jsonResponse(LEXICON_ENTRY_LIST)
      }
      throw new Error(`Unexpected: ${url}`)
    }))

    const app = buildGatewayApp()
    try {
      await app.inject({
        method: 'GET',
        url: '/api/lexicon/entries',
        headers: { 'x-request-id': 'test-req-42' },
      })
      expect(capturedReqId).toBe('test-req-42')
    } finally {
      await app.close()
    }
  })

  it('forwards x-request-id to NLP service for warmup', async () => {
    setupEnv()
    let capturedReqId = ''
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      capturedReqId = new Headers(init?.headers).get('x-request-id') ?? ''
      return jsonResponse(WARMUP_OK)
    }))

    const app = buildGatewayApp()
    try {
      await app.inject({
        method: 'GET',
        url: '/api/system/warmup',
        headers: { 'x-request-id': 'warmup-req-77' },
      })
      expect(capturedReqId).toBe('warmup-req-77')
    } finally {
      await app.close()
    }
  })
})

// ─── тесты: 404 для несуществующих маршрутов ──────────────────────────────────

describe('api-gateway e2e: 404 handling', () => {
  it('unknown /api/* route returns 404', async () => {
    setupEnv()

    const app = buildGatewayApp()
    try {
      const res = await app.inject({ method: 'GET', url: '/api/nonexistent/route' })
      expect(res.statusCode).toBe(404)
    } finally {
      await app.close()
    }
  })
})
