import { randomUUID } from 'node:crypto'
import fastify from 'fastify'
import {
  assertAssignmentScanResultContract,
  assertAssignmentsStatisticsContract,
  assertBulkRescanResultContract,
  assertExtractSentenceResultContract,
  assertLexiconSearchResultContract,
  assertQuickAddSuggestionContract,
  assertRowSyncResultContract,
  buildUrl,
  loadConfig,
  requestJson,
} from '@vocabulary/shared'
import { AssignmentsRepository } from './repository.js'
import { PostgresAssignmentsRepository } from './postgres_repository.js'
import { extractSentence, scanAssignment, suggestQuickAddCategory, type LexiconSearchRow } from './scanner.js'
import type { AssignmentsStore } from './storage.js'

export function buildAssignmentsServiceApp() {
  const config = loadConfig()
  const app = fastify({ logger: process.env.NODE_ENV !== 'test' })
  const repository = createAssignmentsRepository(config)

  app.addHook('onClose', async () => {
    await repository.close()
  })

  app.get('/health', async () => ({
    status: 'ok',
    storage_backend: config.assignmentsService.storageBackend,
  }))

  app.get('/assignments', async (request) => {
    const query = request.query as { limit?: number; offset?: number }
    return repository.listAssignments(query.limit, query.offset)
  })

  app.get('/assignments/:assignmentId', async (request, reply) => {
    const assignment = await repository.getAssignmentById(Number((request.params as { assignmentId: string }).assignmentId))
    if (!assignment) {
      reply.code(404).send({ detail: 'Assignment not found.' })
      return
    }
    reply.send(assignment)
  })

  app.delete('/assignments/:assignmentId', async (request) => {
    const deleted = await repository.deleteAssignment(Number((request.params as { assignmentId: string }).assignmentId))
    return {
      deleted,
      message: deleted ? 'Assignment deleted.' : 'Assignment not found.',
    }
  })

  app.post('/assignments/bulk-delete', async (request) => {
    const body = request.body as { assignment_ids?: number[] }
    const result = await repository.bulkDelete(body.assignment_ids ?? [])
    return {
      operation: 'bulk_delete',
      success_count: result.deleted.length,
      failed_count: result.not_found.length,
      message: `Bulk delete: ${result.deleted.length} succeeded, ${result.not_found.length} failed.`,
    }
  })

  app.get('/assignments/:assignmentId/audio', async (_, reply) => {
    reply.code(404).send({ detail: 'Audio not available' })
  })

  app.post('/assignments/quick-add', async (request, reply) => {
    try {
      const body = request.body as {
        term: string
        content_completed: string
        category?: string
        assignment_id?: number | null
      }
      const result = await quickAddMissingWord(config, body)
      assertRowSyncResultContract(result)
      reply.send(result)
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.post('/assignments/suggest-category', async (request) => {
    const body = request.body as {
      term: string
      content_completed: string
      available_categories?: string[]
    }
    let available = Array.isArray(body.available_categories) ? body.available_categories.filter(Boolean) : []
    if (!available.length) {
      const lexicon = await fetchLexiconSearch(config, { limit: 1, offset: 0, status: 'all' })
      available = Array.isArray(lexicon.available_categories) ? lexicon.available_categories.map(String) : []
    }
    const suggestion = suggestQuickAddCategory(body.term)
    const availableMap = new Map(available.map((item) => [item.toLowerCase(), item]))
    const candidateCategories = suggestion.candidate_categories
      .map((item) => availableMap.get(String(item).toLowerCase()) ?? (available.length ? '' : item))
      .filter(Boolean)
    const recommended = candidateCategories[0] ?? (available[0] ?? suggestion.recommended_category)
    const payload = {
      term: String(body.term ?? '').trim().toLowerCase(),
      recommended_category: recommended,
      candidate_categories: candidateCategories.length ? candidateCategories : [recommended],
      confidence: suggestion.confidence,
      rationale: suggestion.rationale,
      suggested_example_usage: await extractSentenceViaApi(config, body.content_completed, body.term),
    }
    assertQuickAddSuggestionContract(payload)
    return payload
  })

  app.post('/internal/v1/assignments/scan', async (request) => {
    const body = request.body as {
      title?: string
      content_original?: string
      content_completed: string
    }
    const saved = await repository.saveAssignment({
      title: String(body.title ?? ''),
      content_original: String(body.content_original ?? ''),
      content_completed: String(body.content_completed ?? ''),
    })
    const result = await scanAndPersist(config, repository, saved)
    assertAssignmentScanResultContract(result)
    return result
  })

  app.put('/internal/v1/assignments/:assignmentId/update', async (request) => {
    const assignmentId = String((request.params as { assignmentId: string }).assignmentId)
    const body = request.body as {
      title?: string
      content_original?: string
      content_completed: string
    }
    const updated = await repository.updateAssignmentContent({
      assignment_id: Number(assignmentId),
      title: String(body.title ?? ''),
      content_original: String(body.content_original ?? ''),
      content_completed: String(body.content_completed ?? ''),
    })
    if (!updated) {
      throw new Error(`Assignment #${assignmentId} not found.`)
    }
    const result = await scanAndPersist(config, repository, updated)
    assertAssignmentScanResultContract(result)
    return result
  })

  app.post('/internal/v1/assignments/bulk-rescan', async (request) => {
    const body = request.body as { assignment_ids?: number[] }
    const ids = [...new Set((body.assignment_ids ?? []).map((item) => Number(item)).filter((item) => item > 0))]
    if (!ids.length) {
      return {
        success_count: 0,
        failed_count: 0,
        message: 'Bulk rescan: 0 succeeded, 0 failed.',
      }
    }
    const lexiconRows = await fetchAllLexiconRows(config)
    const assignmentsById = new Map(
      (await repository.getAssignmentsByIds(ids)).map((assignment) => [assignment.id, assignment] as const),
    )
    const processed: number[] = []
    const failed: number[] = []
    for (const id of ids) {
      const assignment = assignmentsById.get(id)
      if (!assignment) {
        failed.push(id)
        continue
      }
      try {
        await scanAndPersist(config, repository, assignment, lexiconRows)
        processed.push(id)
      } catch {
        failed.push(id)
      }
    }
    const payload = {
      success_count: processed.length,
      failed_count: failed.length,
      message: `Bulk rescan: ${processed.length} succeeded, ${failed.length} failed.`,
    }
    assertBulkRescanResultContract(payload)
    return payload
  })

  app.get('/internal/v1/assignments/statistics', async () => {
    const coverage = await repository.getCoverageStats()
    const totalAssignments = coverage.length
    const average = totalAssignments
      ? coverage.reduce((sum, item) => sum + item.coverage_pct, 0) / totalAssignments
      : 0
    const payload = {
      assignment_coverage: coverage,
      total_assignments: totalAssignments,
      average_assignment_coverage: average,
      low_coverage_count: coverage.filter((item) => item.coverage_pct < 60).length,
    }
    assertAssignmentsStatisticsContract(payload)
    return payload
  })

  return app
}

async function fetchLexiconSearch(
  config: ReturnType<typeof loadConfig>,
  query: Record<string, unknown>,
): Promise<{
  rows: LexiconSearchRow[]
  available_categories: string[]
}> {
  return requestJson(serviceBaseUrl(config.lexiconService), '/internal/v1/lexicon/search', {
    method: 'GET',
    query,
  }).then((payload) => {
    assertLexiconSearchResultContract(payload)
    return payload
  }) as Promise<{
    rows: LexiconSearchRow[]
    available_categories: string[]
  }>
}

async function scanAndPersist(
  config: ReturnType<typeof loadConfig>,
  repository: AssignmentsStore,
  assignment: {
    id: number
    title: string
    content_original: string
    content_completed: string
  },
  lexiconRows?: LexiconSearchRow[],
) {
  const result = scanAssignment({
    assignmentId: assignment.id,
    title: assignment.title,
    contentOriginal: assignment.content_original,
    contentCompleted: assignment.content_completed,
    lexiconRows: lexiconRows ?? await fetchAllLexiconRows(config),
    completedThresholdPercent: 90,
  })
  await repository.updateAssignmentStatus({
    assignment_id: assignment.id,
    status: result.assignment_status,
    lexicon_coverage_percent: result.lexicon_coverage_percent,
  })
  return result
}

async function fetchAllLexiconRows(config: ReturnType<typeof loadConfig>): Promise<LexiconSearchRow[]> {
  const lexicon = await fetchLexiconSearch(config, {
    status: 'all',
    limit: 12000,
    offset: 0,
    sort_by: 'id',
    sort_direction: 'desc',
  })
  return lexicon.rows
}

function createAssignmentsRepository(config: ReturnType<typeof loadConfig>): AssignmentsStore {
  if (config.assignmentsService.storageBackend !== 'postgres') {
    return new AssignmentsRepository(config.assignmentsDbPath)
  }

  const repository = new PostgresAssignmentsRepository(
    config.assignmentsService.postgresUrl,
    config.assignmentsService.schemaName,
  )
  if (!config.assignmentsService.bootstrapFromSqlite) {
    return repository
  }

  let bootstrapPromise: Promise<void> | null = null
  const bootstrapIfNeeded = async () => {
    if (bootstrapPromise) {
      await bootstrapPromise
      return
    }
    bootstrapPromise = (async () => {
      if (!(await repository.isEmpty())) {
        return
      }
      const sqliteRepository = new AssignmentsRepository(config.assignmentsDbPath)
      try {
        await repository.importSnapshot(sqliteRepository.exportSnapshot())
      } finally {
        sqliteRepository.close()
      }
    })().catch((error) => {
      bootstrapPromise = null
      throw error
    })
    await bootstrapPromise
  }

  return {
    async saveAssignment(input) {
      await bootstrapIfNeeded()
      return repository.saveAssignment(input)
    },
    async listAssignments(limit, offset) {
      await bootstrapIfNeeded()
      return repository.listAssignments(limit, offset)
    },
    async getAssignmentById(id) {
      await bootstrapIfNeeded()
      return repository.getAssignmentById(id)
    },
    async getAssignmentsByIds(ids) {
      await bootstrapIfNeeded()
      return repository.getAssignmentsByIds(ids)
    },
    async updateAssignmentContent(input) {
      await bootstrapIfNeeded()
      return repository.updateAssignmentContent(input)
    },
    async updateAssignmentStatus(input) {
      await bootstrapIfNeeded()
      return repository.updateAssignmentStatus(input)
    },
    async deleteAssignment(id) {
      await bootstrapIfNeeded()
      return repository.deleteAssignment(id)
    },
    async bulkDelete(ids) {
      await bootstrapIfNeeded()
      return repository.bulkDelete(ids)
    },
    async getCoverageStats() {
      await bootstrapIfNeeded()
      return repository.getCoverageStats()
    },
    async exportSnapshot() {
      await bootstrapIfNeeded()
      return repository.exportSnapshot()
    },
    async isEmpty() {
      await bootstrapIfNeeded()
      return repository.isEmpty()
    },
    async close() {
      await repository.close()
    },
  }
}

async function quickAddMissingWord(
  config: ReturnType<typeof loadConfig>,
  input: {
    term: string
    content_completed: string
    category?: string
    assignment_id?: number | null
  },
) {
  const term = String(input.term ?? '').trim().toLowerCase()
  const chosenCategory = String(input.category ?? '').trim() || 'Auto Added'
  if (!term) {
    return {
      status: 'rejected',
      value: '',
      category: 'Auto Added',
      request_id: '',
      message: 'Quick Add rejected: empty word.',
      category_fallback_used: true,
    }
  }

  const search = await fetchLexiconSearch(config, {
    status: 'all',
    limit: 12000,
    offset: 0,
  })
  const exists = search.rows.some((row) =>
    String(row.category ?? '').toLowerCase() === chosenCategory.toLowerCase()
      && String(row.normalized ?? '').toLowerCase() === term,
  )
  if (exists) {
    const requestId = randomUUID().replace(/-/g, '')
    return {
      status: 'already_exists',
      value: term,
      category: chosenCategory,
      request_id: requestId,
      message: `Quick Add skipped: '${term}' already exists in category '${chosenCategory}'.`,
      category_fallback_used: false,
    }
  }

  const requestId = randomUUID().replace(/-/g, '')
  const example = await extractSentenceViaApi(config, input.content_completed, term)
  const response = await fetch(buildUrl(serviceBaseUrl(config.lexiconService), '/internal/v1/lexicon/entries'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      category: chosenCategory,
      value: term,
      source: 'manual',
      confidence: 1.0,
      request_id: requestId,
      example_usage: example,
    }),
  })
  if (!response.ok) {
    throw new Error(await response.text() || response.statusText)
  }
  return {
    status: 'added',
    value: term,
    category: chosenCategory,
    request_id: requestId,
    message: `Quick Add added '${term}' to '${chosenCategory}'${example ? ' with example usage.' : '.'}`,
    category_fallback_used: false,
  }
}

async function extractSentenceViaApi(
  config: ReturnType<typeof loadConfig>,
  content: string,
  term: string,
): Promise<string> {
  try {
    const payload = await requestJson<{ sentence?: string }>(serviceBaseUrl(config.nlpService), '/internal/v1/nlp/extract-sentence', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: content, term }),
    })
    assertExtractSentenceResultContract(payload)
    return String(payload.sentence ?? '').trim() || extractSentence(content, term)
  } catch {
    return extractSentence(content, term)
  }
}

function serviceBaseUrl(config: { host: string; port: number }): string {
  return buildUrl(`http://${config.host}:${config.port}`, '/')
}
