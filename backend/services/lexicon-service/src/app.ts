import fastify from 'fastify'
import {
  assertCategoryMutationResultContract,
  assertExportSnapshotContract,
  assertInsertManyResultContract,
  assertLexiconIndexContract,
  assertLexiconSearchResultContract,
  assertLexiconStatisticsContract,
  assertMutationMessageContract,
  assertMweExpressionMutationContract,
  assertMweSenseMutationContract,
  loadConfig,
  assertRowSyncResultContract,
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
  const app = fastify({ logger: process.env.NODE_ENV !== 'test' })
  const repository = createLexiconRepository(config)

  app.addHook('onClose', async () => {
    await repository.close()
  })

  app.get('/health', async () => ({
    status: 'ok',
    storage_backend: config.lexiconService.storageBackend,
  }))

  app.get('/lexicon/entries', async (request, reply) => {
    const payload = await repository.searchEntries(request.query as Record<string, unknown>)
    assertLexiconSearchResultContract(payload)
    reply.send(payload)
  })

  app.post('/lexicon/entries', async (request, reply) => {
    try {
      const payload = await repository.addEntry(request.body as AddEntryRequest)
      assertMutationMessageContract(payload)
      reply.send(payload)
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
    const payload = await repository.createCategory(request.body as CategoryRequest)
    assertCategoryMutationResultContract(payload)
    return payload
  })

  app.delete('/lexicon/categories/:name', async (request) => {
    const payload = await repository.deleteCategory(String((request.params as { name: string }).name))
    assertCategoryMutationResultContract(payload)
    return payload
  })

  app.get('/internal/v1/lexicon/search', async (request, reply) => {
    const payload = await repository.searchEntries(request.query as Record<string, unknown>)
    assertLexiconSearchResultContract(payload)
    reply.send(payload)
  })

  app.post('/internal/v1/lexicon/sync-row', async (request) => {
    const payload = await repository.syncRow(request.body as RowSyncRequest)
    assertRowSyncResultContract(payload)
    return payload
  })

  app.get('/internal/v1/lexicon/statistics', async () => {
    const payload = await repository.getStatistics()
    assertLexiconStatisticsContract(payload)
    return payload
  })

  app.get('/internal/v1/lexicon/categories', async () => {
    const payload = { categories: await repository.listCategories(), message: '' }
    assertCategoryMutationResultContract(payload)
    return { categories: payload.categories }
  })

  app.post('/internal/v1/lexicon/categories', async (request, reply) => {
    try {
      const payload = await repository.createCategory(request.body as CategoryRequest)
      assertCategoryMutationResultContract(payload)
      reply.send(payload)
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.post('/internal/v1/lexicon/entries', async (request, reply) => {
    try {
      const payload = await repository.addEntry(request.body as AddEntryRequest)
      assertMutationMessageContract(payload)
      reply.send(payload)
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.post('/internal/v1/lexicon/entries/bulk', async (request, reply) => {
    try {
      const payload = await repository.addEntries(request.body as BulkAddEntriesRequest)
      assertInsertManyResultContract(payload)
      reply.send(payload)
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.get('/internal/v1/lexicon/index', async () => {
    const payload = await repository.buildIndex()
    assertLexiconIndexContract(payload)
    return payload
  })

  app.get('/internal/v1/lexicon/export-snapshot', async () => {
    const payload = await repository.exportSnapshot()
    assertExportSnapshotContract(payload)
    return payload
  })

  app.post('/internal/v1/lexicon/mwe/expression', async (request, reply) => {
    try {
      const payload = await repository.upsertMweExpression(request.body as UpsertMweExpressionRequest)
      assertMweExpressionMutationContract(payload)
      reply.send(payload)
    } catch (error) {
      reply.code(400).send({ detail: error instanceof Error ? error.message : String(error) })
    }
  })

  app.post('/internal/v1/lexicon/mwe/sense', async (request, reply) => {
    try {
      const payload = await repository.upsertMweSense(request.body as UpsertMweSenseRequest)
      assertMweSenseMutationContract(payload)
      reply.send(payload)
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

  const repository = new PostgresLexiconRepository(
    config.lexiconService.postgresUrl,
    config.lexiconService.schemaName,
  )
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
    })().catch((error) => {
      bootstrapPromise = null
      throw error
    })
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
