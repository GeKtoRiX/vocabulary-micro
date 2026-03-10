import fs from 'node:fs'
import { randomUUID } from 'node:crypto'
import fastify from 'fastify'
import type { FastifyReply, FastifyRequest } from 'fastify'
import fastifyStatic from '@fastify/static'
import {
  buildUrl,
  extractForwardHeaders,
  loadConfig,
  proxyJson,
  proxyResponse,
  requestBuffer,
  requestJson,
  bridgeLegacyJob,
} from '@vocabulary/shared'
import { cleanupJob, createJob, nextJobEvent, pushJobEvent } from './jobs.js'

interface LexiconStatsPayload {
  total_entries: number
  counts_by_status: Record<string, number>
  counts_by_source: Record<string, number>
  categories: Array<{ name: string; count: number }>
}

interface AssignmentsStatsPayload {
  assignment_coverage: Array<{ title: string; coverage_pct: number; created_at: string }>
  total_assignments: number
  average_assignment_coverage: number
  low_coverage_count: number
}

export function buildGatewayApp() {
  const config = loadConfig()
  const app = fastify({ logger: false })

  app.addHook('onRequest', async (request) => {
    setRequestId(request, typeof request.headers['x-request-id'] === 'string' ? request.headers['x-request-id'] : undefined)
  })

  app.get('/api/system/health', async (request, reply) => {
    reply.send({ status: 'ok', request_id: getRequestId(request) })
  })

  app.get('/api/system/warmup', async (request, reply) => {
    const requestId = getRequestId(request)
    if (config.gateway.parseBackend === 'nlp') {
      await proxyJson(
        reply,
        serviceBaseUrl(config.nlpService),
        '/internal/v1/system/warmup',
        {
          method: 'GET',
          headers: extractForwardHeaders(request, requestId),
        },
      )
      return
    }
    await proxyJson(reply, config.legacyBaseUrl, '/api/system/warmup', {
      method: 'GET',
      headers: extractForwardHeaders(request, requestId),
    })
  })

  app.post('/api/parse', async (request, reply) => {
    const requestId = getRequestId(request)
    const jobId = createJob()
    queueMicrotask(async () => {
      pushJobEvent(jobId, { type: 'progress', message: 'Parsing...', request_id: requestId })
      try {
        if (config.gateway.parseBackend === 'nlp') {
          const payload = await requestJson<Record<string, unknown>>(
            serviceBaseUrl(config.nlpService),
            '/internal/v1/nlp/parse',
            {
              method: 'POST',
              headers: {
                ...extractForwardHeaders(request, requestId),
                'content-type': 'application/json',
              },
              body: JSON.stringify(request.body ?? {}),
            },
          )
          pushJobEvent(jobId, asGatewayEvent({ type: 'result', request_id: requestId, ...payload }))
        } else {
          await bridgeLegacyJob({
            baseUrl: config.legacyBaseUrl,
            startPath: '/api/parse',
            streamPath: (innerJobId) => `/api/parse/jobs/${innerJobId}/stream`,
            body: request.body ?? {},
            headers: extractForwardHeaders(request, requestId),
            onEvent(event) {
              pushJobEvent(jobId, asGatewayEvent({ ...event, request_id: requestId }))
            },
          })
        }
      } catch (error) {
        pushJobEvent(jobId, {
          type: 'error',
          request_id: requestId,
          message: error instanceof Error ? error.message : String(error),
        })
      } finally {
        pushJobEvent(jobId, { type: 'done', request_id: requestId })
      }
    })
    reply.send({ job_id: jobId })
  })

  app.get('/api/parse/jobs/:jobId/stream', async (request, reply) => {
    await streamGatewayJob(reply, String((request.params as { jobId: string }).jobId))
  })

  app.post('/api/parse/sync-row', async (request, reply) => {
    const requestId = getRequestId(request)
    if (config.gateway.lexiconBackend === 'service') {
      await proxyJson(reply, serviceBaseUrl(config.lexiconService), '/internal/v1/lexicon/sync-row', {
        method: 'POST',
        headers: {
          ...extractForwardHeaders(request, requestId),
          'content-type': 'application/json',
        },
        body: JSON.stringify(request.body ?? {}),
      })
      return
    }
    await proxyJson(reply, config.legacyBaseUrl, '/api/parse/sync-row', {
      method: 'POST',
      headers: {
        ...extractForwardHeaders(request, requestId),
        'content-type': 'application/json',
      },
      body: JSON.stringify(request.body ?? {}),
    })
  })

  registerLexiconRoutes(app)
  registerAssignmentsRoutes(app)

  app.get('/api/statistics', async (request, reply) => {
    const requestId = getRequestId(request)
    if (config.gateway.statisticsBackend === 'legacy') {
      await proxyJson(reply, config.legacyBaseUrl, '/api/statistics', {
        method: 'GET',
        headers: extractForwardHeaders(request, requestId),
      })
      return
    }

    try {
      const [lexiconStats, assignmentsStats] = await Promise.all([
        requestJson<LexiconStatsPayload>(serviceBaseUrl(config.lexiconService), '/internal/v1/lexicon/statistics', {
          method: 'GET',
          headers: { 'x-request-id': requestId },
        }),
        requestJson<AssignmentsStatsPayload>(serviceBaseUrl(config.assignmentsService), '/internal/v1/assignments/statistics', {
          method: 'GET',
          headers: { 'x-request-id': requestId },
        }),
      ])
      const topCategory = lexiconStats.categories[0] ?? { name: '', count: 0 }
      reply.send({
        total_entries: lexiconStats.total_entries,
        counts_by_status: lexiconStats.counts_by_status,
        counts_by_source: lexiconStats.counts_by_source,
        categories: lexiconStats.categories,
        assignment_coverage: assignmentsStats.assignment_coverage,
        overview: {
          total_assignments: assignmentsStats.total_assignments,
          average_assignment_coverage: Number(assignmentsStats.average_assignment_coverage.toFixed(1)),
          pending_review_count: Number(lexiconStats.counts_by_status.pending_review ?? 0),
          approved_count: Number(lexiconStats.counts_by_status.approved ?? 0),
          low_coverage_count: assignmentsStats.low_coverage_count,
          top_category: topCategory,
        },
      })
    } catch (error) {
      reply.code(502).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  if (config.gateway.serveStatic && fs.existsSync(config.gateway.staticDir)) {
    app.register(fastifyStatic, {
      root: config.gateway.staticDir,
      prefix: '/',
      wildcard: false,
    })

    app.setNotFoundHandler((request: FastifyRequest, reply: FastifyReply) => {
      if (request.url.startsWith('/api/')) {
        reply.code(404).send({ detail: 'Not found' })
        return
      }
      if (request.method !== 'GET') {
        reply.code(404).send({ detail: 'Not found' })
        return
      }
      reply.sendFile('index.html')
    })
  }

  return app
}

function registerLexiconRoutes(app: ReturnType<typeof fastify>) {
  const config = loadConfig()

  app.get('/api/lexicon/entries', async (request: FastifyRequest, reply: FastifyReply) => {
    const requestId = getRequestId(request)
    const baseUrl = config.gateway.lexiconBackend === 'service'
      ? serviceBaseUrl(config.lexiconService)
      : config.legacyBaseUrl
    const path = config.gateway.lexiconBackend === 'service' ? '/lexicon/entries' : '/api/lexicon/entries'
    await proxyJson(reply, baseUrl, path, {
      method: 'GET',
      headers: extractForwardHeaders(request, requestId),
      query: request.query as Record<string, unknown>,
    })
  })

  for (const route of [
    { method: 'POST', url: '/api/lexicon/entries', path: '/lexicon/entries' },
    { method: 'PATCH', url: '/api/lexicon/entries/:entryId', path: '/lexicon/entries/:entryId' },
    { method: 'DELETE', url: '/api/lexicon/entries', path: '/lexicon/entries' },
    { method: 'POST', url: '/api/lexicon/entries/bulk-status', path: '/lexicon/entries/bulk-status' },
    { method: 'POST', url: '/api/lexicon/categories', path: '/lexicon/categories' },
    { method: 'DELETE', url: '/api/lexicon/categories/:name', path: '/lexicon/categories/:name' },
  ] as const) {
    app.route({
      method: route.method,
      url: route.url,
      handler: async (request: FastifyRequest, reply: FastifyReply) => {
        const requestId = getRequestId(request)
        const baseUrl = config.gateway.lexiconBackend === 'service'
          ? serviceBaseUrl(config.lexiconService)
          : config.legacyBaseUrl
        const targetPath = interpolatePath(
          config.gateway.lexiconBackend === 'service' ? route.path : `/api${route.path}`,
          request.params as Record<string, string>,
        )
        await proxyJson(reply, baseUrl, targetPath, {
          method: route.method,
          headers: {
            ...extractForwardHeaders(request, requestId),
            'content-type': 'application/json',
          },
          body: request.body === undefined ? undefined : JSON.stringify(request.body),
        })
      },
    })
  }

  app.get('/api/lexicon/export', async (request: FastifyRequest, reply: FastifyReply) => {
    const requestId = getRequestId(request)
    try {
      const response = config.gateway.exportBackend === 'service'
        ? await requestBuffer(serviceBaseUrl(config.exportService), '/internal/v1/export/lexicon.xlsx', {
            method: 'GET',
            headers: extractForwardHeaders(request, requestId),
          })
        : await requestBuffer(config.legacyBaseUrl, '/api/lexicon/export', {
            method: 'GET',
            headers: extractForwardHeaders(request, requestId),
          })
      await proxyResponse(reply, response)
    } catch (error) {
      reply.code(502).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })
}

function registerAssignmentsRoutes(app: ReturnType<typeof fastify>) {
  const config = loadConfig()

  app.post('/api/assignments/scan', async (request: FastifyRequest, reply: FastifyReply) => {
    const requestId = getRequestId(request)
    const jobId = createJob()
    queueMicrotask(async () => {
      pushJobEvent(jobId, { type: 'progress', message: 'Scanning assignment...', request_id: requestId })
      try {
        if (config.gateway.assignmentsBackend === 'service') {
          const payload = await requestJson<Record<string, unknown>>(
            serviceBaseUrl(config.assignmentsService),
            '/internal/v1/assignments/scan',
            {
              method: 'POST',
              headers: {
                ...extractForwardHeaders(request, requestId),
                'content-type': 'application/json',
              },
              body: JSON.stringify(request.body ?? {}),
            },
          )
          pushJobEvent(jobId, { type: 'result', data: payload, request_id: requestId })
        } else {
          await bridgeLegacyJob({
            baseUrl: config.legacyBaseUrl,
            startPath: '/api/assignments/scan',
            streamPath: (innerJobId) => `/api/assignments/scan/jobs/${innerJobId}/stream`,
            body: request.body ?? {},
            headers: extractForwardHeaders(request, requestId),
            onEvent(event) {
              pushJobEvent(jobId, asGatewayEvent({ ...event, request_id: requestId }))
            },
          })
        }
      } catch (error) {
        pushJobEvent(jobId, {
          type: 'error',
          request_id: requestId,
          message: error instanceof Error ? error.message : String(error),
        })
      } finally {
        pushJobEvent(jobId, { type: 'done', request_id: requestId })
      }
    })
    reply.send({ job_id: jobId })
  })

  app.get('/api/assignments/scan/jobs/:jobId/stream', async (request: FastifyRequest, reply: FastifyReply) => {
    await streamGatewayJob(reply, String((request.params as { jobId: string }).jobId))
  })

  for (const route of [
    { method: 'GET', url: '/api/assignments', path: '/assignments' },
    { method: 'GET', url: '/api/assignments/:assignmentId', path: '/assignments/:assignmentId' },
    { method: 'DELETE', url: '/api/assignments/:assignmentId', path: '/assignments/:assignmentId' },
    { method: 'POST', url: '/api/assignments/bulk-delete', path: '/assignments/bulk-delete' },
    { method: 'GET', url: '/api/assignments/:assignmentId/audio', path: '/assignments/:assignmentId/audio' },
    { method: 'POST', url: '/api/assignments/quick-add', path: '/assignments/quick-add' },
    { method: 'POST', url: '/api/assignments/suggest-category', path: '/assignments/suggest-category' },
  ] as const) {
    app.route({
      method: route.method,
      url: route.url,
      handler: async (request: FastifyRequest, reply: FastifyReply) => {
        const requestId = getRequestId(request)
        const baseUrl = config.gateway.assignmentsBackend === 'service'
          ? serviceBaseUrl(config.assignmentsService)
          : config.legacyBaseUrl
        const targetPath = interpolatePath(
          config.gateway.assignmentsBackend === 'service' ? route.path : `/api${route.path}`,
          request.params as Record<string, string>,
        )
        await proxyJson(reply, baseUrl, targetPath, {
          method: route.method,
          headers: {
            ...extractForwardHeaders(request, requestId),
            'content-type': 'application/json',
          },
          query: request.query as Record<string, unknown>,
          body: request.body === undefined ? undefined : JSON.stringify(request.body),
        })
      },
    })
  }

  app.put('/api/assignments/:assignmentId', async (request: FastifyRequest, reply: FastifyReply) => {
    const requestId = getRequestId(request)
    const jobId = createJob()
    const assignmentId = String((request.params as { assignmentId: string }).assignmentId)
    queueMicrotask(async () => {
      pushJobEvent(jobId, { type: 'progress', message: 'Updating assignment...', request_id: requestId })
      try {
        if (config.gateway.assignmentsBackend === 'service') {
          const payload = await requestJson<Record<string, unknown>>(
            serviceBaseUrl(config.assignmentsService),
            `/internal/v1/assignments/${assignmentId}/update`,
            {
              method: 'PUT',
              headers: {
                ...extractForwardHeaders(request, requestId),
                'content-type': 'application/json',
              },
              body: JSON.stringify(request.body ?? {}),
            },
          )
          pushJobEvent(jobId, { type: 'result', data: payload, request_id: requestId })
        } else {
          await bridgeLegacyJob({
            baseUrl: config.legacyBaseUrl,
            startPath: `/api/assignments/${assignmentId}`,
            streamPath: (innerJobId) => `/api/assignments/scan/jobs/${innerJobId}/stream`,
            body: request.body ?? {},
            headers: extractForwardHeaders(request, requestId),
            onEvent(event) {
              pushJobEvent(jobId, asGatewayEvent({ ...event, request_id: requestId }))
            },
          })
        }
      } catch (error) {
        pushJobEvent(jobId, {
          type: 'error',
          request_id: requestId,
          message: error instanceof Error ? error.message : String(error),
        })
      } finally {
        pushJobEvent(jobId, { type: 'done', request_id: requestId })
      }
    })
    reply.send({ job_id: jobId })
  })

  app.post('/api/assignments/bulk-rescan', async (request: FastifyRequest, reply: FastifyReply) => {
    const requestId = getRequestId(request)
    const jobId = createJob()
    queueMicrotask(async () => {
      pushJobEvent(jobId, { type: 'progress', message: 'Rescanning assignments...', request_id: requestId })
      try {
        if (config.gateway.assignmentsBackend === 'service') {
          const payload = await requestJson<Record<string, unknown>>(
            serviceBaseUrl(config.assignmentsService),
            '/internal/v1/assignments/bulk-rescan',
            {
              method: 'POST',
              headers: {
                ...extractForwardHeaders(request, requestId),
                'content-type': 'application/json',
              },
              body: JSON.stringify(request.body ?? {}),
            },
          )
          pushJobEvent(jobId, asGatewayEvent({ type: 'result', request_id: requestId, ...payload }))
        } else {
          await bridgeLegacyJob({
            baseUrl: config.legacyBaseUrl,
            startPath: '/api/assignments/bulk-rescan',
            streamPath: (innerJobId) => `/api/assignments/scan/jobs/${innerJobId}/stream`,
            body: request.body ?? {},
            headers: extractForwardHeaders(request, requestId),
            onEvent(event) {
              pushJobEvent(jobId, asGatewayEvent({ ...event, request_id: requestId }))
            },
          })
        }
      } catch (error) {
        pushJobEvent(jobId, {
          type: 'error',
          request_id: requestId,
          message: error instanceof Error ? error.message : String(error),
        })
      } finally {
        pushJobEvent(jobId, { type: 'done', request_id: requestId })
      }
    })
    reply.send({ job_id: jobId })
  })
}

async function streamGatewayJob(reply: import('fastify').FastifyReply, jobId: string): Promise<void> {
  reply.hijack()
  reply.raw.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  })
  while (true) {
    const event = await nextJobEvent(jobId)
    if (!event) {
      reply.raw.write('data: {"type":"error","message":"Job not found"}\n\n')
      reply.raw.end()
      return
    }
    reply.raw.write(`data: ${JSON.stringify(event)}\n\n`)
    if (event.type === 'done' || event.type === 'error') {
      break
    }
  }
  cleanupJob(jobId)
  reply.raw.end()
}

function interpolatePath(pathname: string, params: Record<string, string> = {}): string {
  let result = pathname
  for (const [key, value] of Object.entries(params)) {
    result = result.replace(`:${key}`, encodeURIComponent(value))
  }
  return result
}

function serviceBaseUrl(config: { host: string; port: number }): string {
  return buildUrl(`http://${config.host}:${config.port}`, '/')
}

function asGatewayEvent(event: Record<string, unknown>): import('./jobs.js').GatewayJobEvent {
  return event as import('./jobs.js').GatewayJobEvent
}

function setRequestId(request: FastifyRequest, requestId?: string): void {
  ;(request as FastifyRequest & { correlationId?: string }).correlationId =
    requestId && requestId.trim() ? requestId : randomUUID()
}

function getRequestId(request: FastifyRequest): string {
  return (request as FastifyRequest & { correlationId?: string }).correlationId ?? randomUUID()
}
