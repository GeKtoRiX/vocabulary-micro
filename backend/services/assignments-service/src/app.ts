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

  app.post('/assignments', async (request, reply) => {
    try {
      const body = request.body as { subunits?: Array<{ content?: string }> }
      reply.code(201).send(await repository.createUnit({ subunits: readUnitSubunits(body.subunits) }))
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.get('/assignments/:assignmentId', async (request, reply) => {
    const assignment = await repository.getAssignmentById(Number((request.params as { assignmentId: string }).assignmentId))
    if (!assignment) {
      reply.code(404).send({ detail: 'Unit not found.' })
      return
    }
    reply.send(assignment)
  })

  app.put('/assignments/:assignmentId', async (request, reply) => {
    try {
      const body = request.body as { subunits?: Array<{ content?: string }> }
      const updated = await repository.updateAssignment({
        assignment_id: Number((request.params as { assignmentId: string }).assignmentId),
        subunits: readUnitSubunits(body.subunits),
      })
      if (!updated) {
        reply.code(404).send({ detail: 'Unit not found.' })
        return
      }
      reply.send(updated)
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.delete('/assignments/:assignmentId', async (request) => {
    const deleted = await repository.deleteAssignment(Number((request.params as { assignmentId: string }).assignmentId))
    return {
      deleted,
      message: deleted ? 'Unit deleted.' : 'Unit not found.',
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
    const result = await runStandaloneScan(config, {
      assignmentId: null,
      title: String(body.title ?? ''),
      contentOriginal: String(body.content_original ?? ''),
      contentCompleted: String(body.content_completed ?? ''),
    })
    assertAssignmentScanResultContract(result)
    return result
  })

  app.put('/internal/v1/assignments/:assignmentId/update', async (request) => {
    const body = request.body as {
      title?: string
      content_original?: string
      content_completed: string
    }
    const assignmentId = Number((request.params as { assignmentId: string }).assignmentId)
    const result = await runStandaloneScan(config, {
      assignmentId,
      title: String(body.title ?? ''),
      contentOriginal: String(body.content_original ?? ''),
      contentCompleted: String(body.content_completed ?? ''),
    })
    assertAssignmentScanResultContract(result)
    return result
  })

  app.post('/internal/v1/assignments/bulk-rescan', async (request) => {
    const body = request.body as { assignment_ids?: number[] }
    const ids = [...new Set((body.assignment_ids ?? []).map((item) => Number(item)).filter((item) => item > 0))]
    const payload = {
      success_count: 0,
      failed_count: ids.length,
      message: `Bulk rescan unavailable for unit storage: ${ids.length} failed.`,
    }
    assertBulkRescanResultContract(payload)
    return payload
  })

  app.get('/internal/v1/assignments/statistics', async () => {
    const payload = await repository.getAssignmentsStatistics()
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

async function runStandaloneScan(
  config: ReturnType<typeof loadConfig>,
  input: {
    assignmentId: number | null
    title: string
    contentOriginal: string
    contentCompleted: string
  },
) {
  return scanAssignment({
    assignmentId: input.assignmentId,
    title: input.title,
    contentOriginal: input.contentOriginal,
    contentCompleted: input.contentCompleted,
    lexiconRows: await fetchAllLexiconRows(config),
    completedThresholdPercent: 90,
  })
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
  return new PostgresAssignmentsRepository(
    config.assignmentsService.postgresUrl,
    config.assignmentsService.schemaName,
  )
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

function readUnitSubunits(input: Array<{ content?: string }> | undefined): Array<{ content: string }> {
  return (Array.isArray(input) ? input : []).map((subunit) => ({
    content: String(subunit?.content ?? ''),
  }))
}
