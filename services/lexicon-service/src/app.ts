import fastify from 'fastify'
import {
  loadConfig,
} from '@vocabulary/shared'
import {
  LexiconRepository,
  type AddEntryRequest,
  type BulkAddEntriesRequest,
  type BulkStatusRequest,
  type DeleteEntriesRequest,
  type UpdateEntryRequest,
  type RowSyncRequest,
  type CategoryRequest,
  type UpsertMweExpressionRequest,
  type UpsertMweSenseRequest,
} from './repository.js'
import { PostgresLexiconRepository } from './postgres_repository.js'
import type { LexiconStore } from './storage.js'

export function buildLexiconServiceApp() {
  const config = loadConfig()
  const app = fastify({ logger: false })
  const repository = createLexiconRepository(config)

  app.addHook('onClose', async () => {
    await repository.close()
  })

  app.get('/health', async () => ({
    status: 'ok',
    storage_backend: config.lexiconService.storageBackend,
  }))

  app.get('/lexicon/entries', async (request, reply) => {
    reply.send(await repository.searchEntries(request.query as Record<string, unknown>))
  })

  app.post('/lexicon/entries', async (request, reply) => {
    try {
      reply.send(await repository.addEntry(request.body as AddEntryRequest))
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.patch('/lexicon/entries/:entryId', async (request, reply) => {
    try {
      const entryId = Number((request.params as { entryId: string }).entryId)
      reply.send(await repository.updateEntry(entryId, request.body as UpdateEntryRequest))
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.delete('/lexicon/entries', async (request, reply) => {
    try {
      reply.send(await repository.deleteEntries(request.body as DeleteEntriesRequest))
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.post('/lexicon/entries/bulk-status', async (request, reply) => {
    try {
      reply.send(await repository.bulkUpdateStatus(request.body as BulkStatusRequest))
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.post('/lexicon/categories', async (request) => {
    return repository.createCategory(request.body as CategoryRequest)
  })

  app.delete('/lexicon/categories/:name', async (request) => {
    return repository.deleteCategory(String((request.params as { name: string }).name))
  })

  app.get('/internal/v1/lexicon/search', async (request, reply) => {
    reply.send(await repository.searchEntries(request.query as Record<string, unknown>))
  })

  app.post('/internal/v1/lexicon/sync-row', async (request) => {
    return repository.syncRow(request.body as RowSyncRequest)
  })

  app.get('/internal/v1/lexicon/statistics', async () => {
    return repository.getStatistics()
  })

  app.get('/internal/v1/lexicon/categories', async () => {
    return { categories: await repository.listCategories() }
  })

  app.post('/internal/v1/lexicon/categories', async (request, reply) => {
    try {
      reply.send(await repository.createCategory(request.body as CategoryRequest))
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.post('/internal/v1/lexicon/entries', async (request, reply) => {
    try {
      reply.send(await repository.addEntry(request.body as AddEntryRequest))
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.post('/internal/v1/lexicon/entries/bulk', async (request, reply) => {
    try {
      reply.send(await repository.addEntries(request.body as BulkAddEntriesRequest))
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.get('/internal/v1/lexicon/index', async () => {
    return repository.buildIndex()
  })

  app.get('/internal/v1/lexicon/export-snapshot', async () => {
    return repository.exportSnapshot()
  })

  app.post('/internal/v1/lexicon/mwe/expression', async (request, reply) => {
    try {
      reply.send(await repository.upsertMweExpression(request.body as UpsertMweExpressionRequest))
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.post('/internal/v1/lexicon/mwe/sense', async (request, reply) => {
    try {
      reply.send(await repository.upsertMweSense(request.body as UpsertMweSenseRequest))
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  return app
}

function createLexiconRepository(config: ReturnType<typeof loadConfig>): LexiconStore {
  if (config.lexiconService.storageBackend !== 'postgres') {
    return new LexiconRepository(config.lexiconDbPath)
  }

  const repository = new PostgresLexiconRepository(config.lexiconService.postgresUrl)
  if (!config.lexiconService.bootstrapFromSqlite) {
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
      const sqliteRepository = new LexiconRepository(config.lexiconDbPath)
      try {
        await repository.importSnapshot(sqliteRepository.exportSnapshot())
      } finally {
        sqliteRepository.close()
      }
    })()
    await bootstrapPromise
  }

  return {
    async searchEntries(query) {
      await bootstrapIfNeeded()
      return repository.searchEntries(query)
    },
    async addEntry(request) {
      await bootstrapIfNeeded()
      return repository.addEntry(request)
    },
    async addEntries(request) {
      await bootstrapIfNeeded()
      return repository.addEntries(request)
    },
    async updateEntry(entryId, request) {
      await bootstrapIfNeeded()
      return repository.updateEntry(entryId, request)
    },
    async deleteEntries(request) {
      await bootstrapIfNeeded()
      return repository.deleteEntries(request)
    },
    async bulkUpdateStatus(request) {
      await bootstrapIfNeeded()
      return repository.bulkUpdateStatus(request)
    },
    async createCategory(request) {
      await bootstrapIfNeeded()
      return repository.createCategory(request)
    },
    async deleteCategory(name) {
      await bootstrapIfNeeded()
      return repository.deleteCategory(name)
    },
    async listCategories() {
      await bootstrapIfNeeded()
      return repository.listCategories()
    },
    async getStatistics() {
      await bootstrapIfNeeded()
      return repository.getStatistics()
    },
    async buildIndex() {
      await bootstrapIfNeeded()
      return repository.buildIndex()
    },
    async exportSnapshot() {
      await bootstrapIfNeeded()
      return repository.exportSnapshot()
    },
    async upsertMweExpression(request) {
      await bootstrapIfNeeded()
      return repository.upsertMweExpression(request)
    },
    async upsertMweSense(request) {
      await bootstrapIfNeeded()
      return repository.upsertMweSense(request)
    },
    async syncRow(request) {
      await bootstrapIfNeeded()
      return repository.syncRow(request)
    },
    async close() {
      await repository.close()
    },
  }
}
