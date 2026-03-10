import { randomUUID } from 'node:crypto'
import { runPostgresMigrations } from '@vocabulary/shared'
import { Pool, type PoolClient, type QueryResultRow } from 'pg'
import type {
  AddEntryRequest,
  BulkAddEntriesRequest,
  BulkStatusRequest,
  CategoryRequest,
  DeleteEntriesRequest,
  ExportSnapshotTable,
  LexiconSearchQuery,
  RowSyncRequest,
  UpdateEntryRequest,
  UpsertMweExpressionRequest,
  UpsertMweSenseRequest,
} from './repository.js'

const EDITABLE_ENTRY_STATUSES = new Set(['pending_review', 'approved', 'rejected'])
const ALLOWED_STATUS_FILTERS = new Set(['all', 'approved', 'pending_review', 'rejected'])
const ALLOWED_SOURCE_FILTERS = new Set(['all', 'manual', 'auto'])
const ALLOWED_SORT_COLUMNS = new Set([
  'id',
  'category',
  'value',
  'normalized',
  'source',
  'confidence',
  'first_seen_at',
  'request_id',
  'status',
  'created_at',
  'reviewed_at',
  'reviewed_by',
  'review_note',
])
const ALLOWED_SORT_DIRECTIONS = new Set(['asc', 'desc'])
const AUTO_CREATE_SYNC_CATEGORIES = new Set(['Noun', 'Verb', 'Adjective', 'Adverb', 'Idiom', 'Phrasal Verb'])
const AUTO_ADD_BLOCKLIST = new Set([
  'a', 'an', 'and', 'are', 'as', 'at', 'be', 'but', 'by', 'for', 'from', 'he', 'her', 'his', 'i', 'if',
  'in', 'into', 'is', 'it', 'its', 'me', 'my', 'of', 'on', 'or', 'our', 'she', 'so', 'that', 'the',
  'their', 'them', 'they', 'this', 'to', 'was', 'we', 'were', 'with', 'you', 'your',
])
const SAFE_TERM_RE = /^[a-z][a-z0-9' -]*[a-z0-9]$|^[a-z]$/
const OWNED_TABLES = ['lexicon_entries', 'lexicon_categories', 'lexicon_meta', 'mwe_expressions', 'mwe_senses', 'mwe_meta'] as const

type DbRow = Record<string, unknown>

export class PostgresLexiconRepository {
  private readonly pool: Pool
  private readonly ready: Promise<void>
  private readonly schemaName: string

  constructor(private readonly postgresUrl: string, schemaName = 'lexicon') {
    this.schemaName = normalizeSchemaName(schemaName)
    this.pool = new Pool({
      connectionString: postgresUrl,
      options: `-c search_path=${this.schemaName},public`,
    })
    this.ready = runPostgresMigrations(this.pool, {
      serviceName: 'lexicon-service',
      migrationsDir: 'services/lexicon-service/infrastructure/postgres_migrations',
      schemaName: this.schemaName,
    })
  }

  async searchEntries(query: LexiconSearchQuery): Promise<Record<string, unknown>> {
    await this.ready
    const safe = this.normalizeQuery(query)

    const whereClauses: string[] = []
    const params: Array<string | number> = []
    let index = 1
    if (safe.status !== 'all') {
      whereClauses.push(`status = $${index++}`)
      params.push(safe.status)
    }
    if (safe.source_filter !== 'all') {
      whereClauses.push(`source = $${index++}`)
      params.push(safe.source_filter)
    }
    if (safe.category_filter) {
      whereClauses.push(`LOWER(category) = LOWER($${index++})`)
      params.push(safe.category_filter)
    }
    if (safe.value_filter) {
      whereClauses.push(`(value ILIKE $${index} OR normalized ILIKE $${index + 1})`)
      params.push(`%${safe.value_filter}%`, `%${safe.value_filter.toLowerCase()}%`)
      index += 2
    }
    if (safe.request_filter) {
      whereClauses.push(`COALESCE(request_id, '') ILIKE $${index++}`)
      params.push(`%${safe.request_filter}%`)
    }
    if (safe.id_min !== null) {
      whereClauses.push(`id >= $${index++}`)
      params.push(safe.id_min)
    }
    if (safe.id_max !== null) {
      whereClauses.push(`id <= $${index++}`)
      params.push(safe.id_max)
    }
    if (safe.reviewed_by_filter) {
      whereClauses.push(`COALESCE(reviewed_by, '') ILIKE $${index++}`)
      params.push(`%${safe.reviewed_by_filter}%`)
    }
    if (safe.confidence_min !== null) {
      whereClauses.push(`confidence >= $${index++}`)
      params.push(safe.confidence_min)
    }
    if (safe.confidence_max !== null) {
      whereClauses.push(`confidence <= $${index++}`)
      params.push(safe.confidence_max)
    }

    const whereSql = whereClauses.length ? ` WHERE ${whereClauses.join(' AND ')}` : ''
    const rows = (await this.pool.query(
      `
        SELECT
          id,
          category,
          value,
          normalized,
          source,
          confidence,
          first_seen_at,
          request_id,
          status,
          created_at,
          reviewed_at,
          reviewed_by,
          review_note
        FROM lexicon_entries
        ${whereSql}
        ORDER BY ${this.quoteIdent(safe.sort_by)} ${safe.sort_direction.toUpperCase()}
        LIMIT $${index} OFFSET $${index + 1}
      `,
      [...params, safe.limit, safe.offset],
    )).rows as DbRow[]

    const countsByStatus = Object.fromEntries(
      (await this.pool.query('SELECT status, COUNT(*)::int AS cnt FROM lexicon_entries GROUP BY status ORDER BY status ASC')).rows
        .map((row: DbRow) => [String(row.status ?? ''), Number(row.cnt ?? 0)]),
    )
    const categories = await this.listCategories()
    const totalRows = Number((await this.pool.query('SELECT COUNT(*)::int AS cnt FROM lexicon_entries')).rows[0]?.cnt ?? 0)

    return {
      rows: rows.map((row) => this.serializeRow(row)),
      total_rows: totalRows,
      filtered_rows: rows.length,
      counts_by_status: countsByStatus,
      available_categories: categories,
      message: `Loaded ${rows.length} row(s) from postgres.`,
    }
  }

  async addEntry(request: AddEntryRequest): Promise<{ message: string }> {
    const category = this.normalizeCategory(request.category) || 'Auto Added'
    const value = this.cleanText(request.value)
    if (!value) {
      throw new Error('Value must not be empty.')
    }
    const source = this.normalizeSource(request.source)
    const confidence = this.normalizeConfidence(request.confidence)
    const nowIso = new Date().toISOString()
    const status = source === 'auto' ? 'pending_review' : 'approved'

    await this.withTransaction(async (client) => {
      await client.query('INSERT INTO lexicon_categories(name) VALUES ($1) ON CONFLICT(name) DO NOTHING', [category])
      const result = await client.query(
        `
          INSERT INTO lexicon_entries(
            category,
            value,
            normalized,
            source,
            confidence,
            first_seen_at,
            request_id,
            example_usage,
            status
          ) VALUES ($1, $2, $3, $4, $5, $6, NULL, NULL, $7)
          ON CONFLICT(category, normalized) DO NOTHING
        `,
        [category, value, value.toLowerCase(), source, confidence, nowIso, status],
      )
      if ((result.rowCount ?? 0) > 0) {
        await this.bumpMeta(client, 'lexicon')
      }
    })

    return { message: `Entry '${value}' added to '${category}'.` }
  }

  async addEntries(request: BulkAddEntriesRequest): Promise<{ inserted_count: number; message: string }> {
    const entries = (request.entries ?? [])
      .map((entry) => ({
        category: this.normalizeCategory(entry.category) || 'Auto Added',
        value: this.cleanText(entry.value),
      }))
      .filter((entry) => entry.value)
    if (!entries.length) {
      return { inserted_count: 0, message: 'No entries to add.' }
    }
    const source = this.normalizeSource(request.source)
    const confidence = this.normalizeConfidence(request.confidence)
    const requestId = String(request.request_id ?? '').trim() || null
    const nowIso = new Date().toISOString()
    const status = source === 'auto' ? 'pending_review' : 'approved'

    let insertedCount = 0
    await this.withTransaction(async (client) => {
      for (const entry of entries) {
        await client.query('INSERT INTO lexicon_categories(name) VALUES ($1) ON CONFLICT(name) DO NOTHING', [entry.category])
        const result = await client.query(
          `
            INSERT INTO lexicon_entries(
              category,
              value,
              normalized,
              source,
              confidence,
              first_seen_at,
              request_id,
              example_usage,
              status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, NULL, $8)
            ON CONFLICT(category, normalized) DO NOTHING
          `,
          [entry.category, entry.value, entry.value.toLowerCase(), source, confidence, nowIso, requestId, status],
        )
        insertedCount += result.rowCount ?? 0
      }
      if (insertedCount > 0) {
        await this.bumpMeta(client, 'lexicon')
      }
    })
    return {
      inserted_count: insertedCount,
      message: `Inserted ${insertedCount} of ${entries.length} requested entries.`,
    }
  }

  async updateEntry(entryId: number, request: UpdateEntryRequest): Promise<Record<string, unknown>> {
    const safeId = this.parseEntryId(entryId)
    const status = this.normalizeEditableStatus(request.status)
    const category = this.normalizeCategory(request.category)
    const value = this.cleanText(request.value)
    if (safeId <= 0) {
      throw new Error('Update skipped: select a valid entry first.')
    }
    if (!value) {
      throw new Error('Update skipped: value must not be empty.')
    }
    if (!category) {
      throw new Error('Update skipped: category must not be empty.')
    }

    const current = (await this.pool.query(
      'SELECT reviewed_at, reviewed_by, review_note FROM lexicon_entries WHERE id = $1',
      [safeId],
    )).rows[0] as DbRow | undefined
    if (!current) {
      throw new Error(`Update skipped: entry id=${safeId} not found.`)
    }

    const categories = new Set(await this.listCategories())
    if (!categories.has(category)) {
      throw new Error(`Update skipped: category '${category}' does not exist. Use 'Add Category' first.`)
    }

    const reviewedAt = status === 'pending_review'
      ? null
      : String(current.reviewed_at ?? '') || new Date().toISOString()
    const reviewedBy = status === 'pending_review' ? null : String(current.reviewed_by ?? '') || 'ui'
    const reviewNote = status === 'pending_review' ? null : (current.review_note ?? null)
    const result = await this.pool.query(
      `
        UPDATE lexicon_entries
        SET category = $1,
            value = $2,
            normalized = $3,
            status = $4,
            reviewed_at = $5,
            reviewed_by = $6,
            review_note = $7
        WHERE id = $8
      `,
      [category, value, value.toLowerCase(), status, reviewedAt, reviewedBy, reviewNote, safeId],
    )
    if ((result.rowCount ?? 0) <= 0) {
      throw new Error(`Update skipped: entry id=${safeId} not found.`)
    }
    await this.bumpMeta(this.pool, 'lexicon')
    const payload = await this.searchEntries(request.query)
    payload.message = `Updated entry id=${safeId}.`
    return payload
  }

  async deleteEntries(request: DeleteEntriesRequest): Promise<Record<string, unknown>> {
    const ids = [...new Set((request.entry_ids ?? []).map((item) => this.parseEntryId(item)).filter((item) => item > 0))]
    if (!ids.length) {
      throw new Error('Delete skipped: select a valid entry first.')
    }
    const result = await this.pool.query(
      `DELETE FROM lexicon_entries WHERE id = ANY($1::int[])`,
      [ids],
    )
    if ((result.rowCount ?? 0) > 0) {
      await this.bumpMeta(this.pool, 'lexicon')
    }
    const payload = await this.searchEntries(request.query)
    payload.message = (result.rowCount ?? 0) <= 0
      ? `Delete skipped: no matching entries for ids=${JSON.stringify(ids)}.`
      : ids.length === 1 ? `Deleted entry id=${ids[0]}.` : `Deleted ${result.rowCount} selected rows.`
    return payload
  }

  async bulkUpdateStatus(request: BulkStatusRequest): Promise<Record<string, unknown>> {
    const ids = [...new Set((request.entry_ids ?? []).map((item) => this.parseEntryId(item)).filter((item) => item > 0))]
    const targetStatus = this.normalizeEditableStatus(request.status)
    let updated = 0
    const errors: string[] = []

    await this.withTransaction(async (client) => {
      for (const id of ids) {
        const current = (await client.query(
          'SELECT id, reviewed_at, reviewed_by, review_note FROM lexicon_entries WHERE id = $1',
          [id],
        )).rows[0] as DbRow | undefined
        if (!current) {
          errors.push(`id=${id} not found`)
          continue
        }
        const reviewedAt = targetStatus === 'pending_review' ? null : String(current.reviewed_at ?? '') || new Date().toISOString()
        const reviewedBy = targetStatus === 'pending_review' ? null : String(current.reviewed_by ?? '') || 'ui'
        const reviewNote = targetStatus === 'pending_review' ? null : (current.review_note ?? null)
        const result = await client.query(
          `
            UPDATE lexicon_entries
            SET status = $1,
                reviewed_at = $2,
                reviewed_by = $3,
                review_note = $4
            WHERE id = $5
          `,
          [targetStatus, reviewedAt, reviewedBy, reviewNote, id],
        )
        updated += result.rowCount ?? 0
      }
      if (updated > 0) {
        await this.bumpMeta(client, 'lexicon')
      }
    })

    const payload = await this.searchEntries(request.query)
    payload.message = errors.length
      ? `Updated ${updated} of ${ids.length} entries to '${targetStatus}'. Errors: ${errors.length}.`
      : `Updated ${updated} of ${ids.length} entries to '${targetStatus}'.`
    return payload
  }

  async createCategory(request: CategoryRequest): Promise<Record<string, unknown>> {
    const cleaned = this.normalizeCategory(request.name)
    if (!cleaned) {
      return { categories: await this.listCategories(), message: 'Category name must not be empty.' }
    }
    const result = await this.pool.query(
      'INSERT INTO lexicon_categories(name) VALUES ($1) ON CONFLICT(name) DO NOTHING',
      [cleaned],
    )
    return {
      categories: await this.listCategories(),
      message: (result.rowCount ?? 0) > 0 ? `Created category '${cleaned}'.` : `Category '${cleaned}' already exists.`,
    }
  }

  async deleteCategory(name: string): Promise<Record<string, unknown>> {
    const cleaned = this.normalizeCategory(name)
    if (!cleaned) {
      return { categories: await this.listCategories(), message: 'Category name must not be empty.' }
    }
    const usage = (await this.pool.query(
      'SELECT COUNT(*)::int AS cnt FROM lexicon_entries WHERE category = $1',
      [cleaned],
    )).rows[0] as DbRow | undefined
    const count = Number(usage?.cnt ?? 0)
    if (count > 0) {
      return {
        categories: await this.listCategories(),
        message: `Delete category skipped: '${cleaned}' is used by ${count} entries.`,
      }
    }
    const result = await this.pool.query('DELETE FROM lexicon_categories WHERE name = $1', [cleaned])
    return {
      categories: await this.listCategories(),
      message: (result.rowCount ?? 0) > 0 ? `Deleted category '${cleaned}'.` : `Category '${cleaned}' not found.`,
    }
  }

  async listCategories(): Promise<string[]> {
    await this.ready
    const rows = (await this.pool.query(`
      SELECT name
      FROM (
        SELECT name AS name FROM lexicon_categories WHERE TRIM(name) <> ''
        UNION
        SELECT category AS name FROM lexicon_entries WHERE TRIM(category) <> ''
      ) categories
      ORDER BY name ASC
    `)).rows as DbRow[]
    const categories = rows.map((row) => String(row.name ?? '').trim()).filter(Boolean)
    if (!categories.includes('Auto Added')) {
      categories.push('Auto Added')
    }
    return [...new Set(categories)].sort((a, b) => a.localeCompare(b))
  }

  async getStatistics(): Promise<Record<string, unknown>> {
    await this.ready
    const total = Number((await this.pool.query('SELECT COUNT(*)::int AS cnt FROM lexicon_entries')).rows[0]?.cnt ?? 0)
    const countsByStatus = Object.fromEntries(
      (await this.pool.query('SELECT status, COUNT(*)::int AS cnt FROM lexicon_entries GROUP BY status ORDER BY cnt DESC')).rows
        .map((row: DbRow) => [String(row.status ?? ''), Number(row.cnt ?? 0)]),
    )
    const countsBySource = Object.fromEntries(
      (await this.pool.query('SELECT source, COUNT(*)::int AS cnt FROM lexicon_entries GROUP BY source ORDER BY cnt DESC')).rows
        .map((row: DbRow) => [String(row.source ?? ''), Number(row.cnt ?? 0)]),
    )
    const categories = (await this.pool.query(
      'SELECT category, COUNT(*)::int AS cnt FROM lexicon_entries GROUP BY category ORDER BY cnt DESC LIMIT 50',
    )).rows.map((row: DbRow) => ({ name: String(row.category ?? ''), count: Number(row.cnt ?? 0) }))
    return {
      total_entries: total,
      counts_by_status: countsByStatus,
      counts_by_source: countsBySource,
      categories,
    }
  }

  async buildIndex(): Promise<Record<string, unknown>> {
    await this.ready
    const rows = (await this.pool.query(`
      SELECT category, normalized, status
      FROM lexicon_entries
      WHERE TRIM(normalized) <> ''
    `)).rows as DbRow[]
    const singleWordIndex: Record<string, string[]> = {}
    const multiWordIndex: Record<string, string[]> = {}
    for (const row of rows) {
      if (String(row.status ?? '').toLowerCase() === 'rejected') {
        continue
      }
      const normalized = String(row.normalized ?? '').trim().toLowerCase()
      const category = String(row.category ?? '').trim()
      if (!normalized || !category) {
        continue
      }
      const parts = normalized.split(/\s+/).filter(Boolean)
      if (parts.length <= 1) {
        singleWordIndex[normalized] = [...(singleWordIndex[normalized] ?? []), category]
      } else {
        multiWordIndex[parts.join(' ')] = [...(multiWordIndex[parts.join(' ')] ?? []), category]
      }
    }
    return {
      single_word_index: singleWordIndex,
      multi_word_index: multiWordIndex,
      total_rows: rows.length,
      lexicon_version: await this.lexiconVersion(),
    }
  }

  async exportSnapshot(): Promise<{ tables: ExportSnapshotTable[] }> {
    await this.ready
    return {
      tables: await Promise.all(OWNED_TABLES.map(async (name) => this.readOwnedTableSnapshot(name))),
    }
  }

  async isEmpty(): Promise<boolean> {
    await this.ready
    const row = (await this.pool.query(`
      SELECT
        (SELECT COUNT(*)::int FROM lexicon_entries) AS lexicon_entries_count,
        (SELECT COUNT(*)::int FROM lexicon_categories) AS lexicon_categories_count,
        (SELECT COUNT(*)::int FROM mwe_expressions) AS mwe_expressions_count,
        (SELECT COUNT(*)::int FROM mwe_senses) AS mwe_senses_count
    `)).rows[0] as DbRow | undefined
    const total = Number(row?.lexicon_entries_count ?? 0)
      + Number(row?.lexicon_categories_count ?? 0)
      + Number(row?.mwe_expressions_count ?? 0)
      + Number(row?.mwe_senses_count ?? 0)
    return total === 0
  }

  async importSnapshot(snapshot: { tables: ExportSnapshotTable[] }): Promise<void> {
    await this.ready
    const tablesByName = new Map(snapshot.tables.map((table) => [table.name, table]))
    await this.withTransaction(async (client) => {
      for (const name of OWNED_TABLES) {
        const table = tablesByName.get(name)
        if (!table || !table.columns.length || !table.rows.length) {
          continue
        }
        const columns = table.columns.map((column) => this.quoteIdent(column)).join(', ')
        const placeholders = table.columns.map((_, index) => `$${index + 1}`).join(', ')
        for (const row of table.rows) {
          await client.query(
            `INSERT INTO ${this.quoteIdent(name)} (${columns}) VALUES (${placeholders}) ON CONFLICT DO NOTHING`,
            row,
          )
        }
      }
      await this.syncSerialSequence(client, 'lexicon_entries', 'id')
      await this.syncSerialSequence(client, 'mwe_expressions', 'id')
      await this.syncSerialSequence(client, 'mwe_senses', 'id')
      const lexiconMeta = tablesByName.get('lexicon_meta')
      if (lexiconMeta?.rows[0]) {
        const [id, version, updatedAt] = lexiconMeta.rows[0]
        await client.query(
          `
            INSERT INTO lexicon_meta(id, lexicon_version, updated_at)
            VALUES ($1, $2, $3)
            ON CONFLICT(id) DO UPDATE SET
              lexicon_version = EXCLUDED.lexicon_version,
              updated_at = EXCLUDED.updated_at
          `,
          [id, version, updatedAt],
        )
      }
      const mweMeta = tablesByName.get('mwe_meta')
      if (mweMeta?.rows[0]) {
        const [id, version, updatedAt] = mweMeta.rows[0]
        await client.query(
          `
            INSERT INTO mwe_meta(id, mwe_version, updated_at)
            VALUES ($1, $2, $3)
            ON CONFLICT(id) DO UPDATE SET
              mwe_version = EXCLUDED.mwe_version,
              updated_at = EXCLUDED.updated_at
          `,
          [id, version, updatedAt],
        )
      }
    })
  }

  async upsertMweExpression(request: UpsertMweExpressionRequest): Promise<{ expression_id: number }> {
    const canonicalForm = this.cleanText(request.canonical_form).toLowerCase()
    if (!canonicalForm) {
      throw new Error('canonical_form must not be empty')
    }
    const expressionType = String(request.expression_type ?? '').trim().toLowerCase()
    if (!['phrasal_verb', 'idiom'].includes(expressionType)) {
      throw new Error("expression_type must be 'phrasal_verb' or 'idiom'")
    }
    const result = await this.pool.query(
      `
        INSERT INTO mwe_expressions(
          canonical_form,
          expression_type,
          base_lemma,
          particle,
          is_separable,
          max_gap_tokens
        ) VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT(canonical_form) DO UPDATE SET
          expression_type = excluded.expression_type,
          base_lemma = excluded.base_lemma,
          particle = excluded.particle,
          is_separable = excluded.is_separable,
          max_gap_tokens = excluded.max_gap_tokens,
          updated_at = CURRENT_TIMESTAMP
        RETURNING id
      `,
      [
        canonicalForm,
        expressionType,
        this.cleanText(String(request.base_lemma ?? '')).toLowerCase(),
        this.cleanText(String(request.particle ?? '')).toLowerCase(),
        request.is_separable ? 1 : 0,
        Math.max(1, Number(request.max_gap_tokens ?? 4) || 4),
      ],
    )
    if ((result.rowCount ?? 0) > 0) {
      await this.bumpMeta(this.pool, 'mwe')
    }
    return { expression_id: Number(result.rows[0]?.id ?? 0) }
  }

  async upsertMweSense(request: UpsertMweSenseRequest): Promise<{ sense_id: number }> {
    const expressionId = Math.max(1, Number(request.expression_id ?? 0) || 0)
    const senseKey = this.cleanText(request.sense_key)
    const gloss = this.cleanText(request.gloss)
    const usageLabel = String(request.usage_label ?? '').trim().toLowerCase()
    const example = this.cleanText(String(request.example ?? ''))
    const priority = Number(request.priority ?? 0) || 0
    if (!expressionId) {
      throw new Error('expression_id must be a positive integer')
    }
    if (!senseKey) {
      throw new Error('sense_key must not be empty')
    }
    if (!gloss) {
      throw new Error('gloss must not be empty')
    }
    if (!['literal', 'idiomatic'].includes(usageLabel)) {
      throw new Error("usage_label must be 'literal' or 'idiomatic'")
    }
    const result = await this.pool.query(
      `
        INSERT INTO mwe_senses(
          expression_id,
          sense_key,
          gloss,
          usage_label,
          example,
          priority
        ) VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT(expression_id, sense_key) DO UPDATE SET
          gloss = excluded.gloss,
          usage_label = excluded.usage_label,
          example = excluded.example,
          priority = excluded.priority,
          updated_at = CURRENT_TIMESTAMP
        RETURNING id
      `,
      [expressionId, senseKey, gloss, usageLabel, example, priority],
    )
    if ((result.rowCount ?? 0) > 0) {
      await this.bumpMeta(this.pool, 'mwe')
    }
    return { sense_id: Number(result.rows[0]?.id ?? 0) }
  }

  async syncRow(request: RowSyncRequest): Promise<Record<string, unknown>> {
    const requestId = randomUUID().replace(/-/g, '')
    const candidate = this.resolveRowSyncCandidate(request)
    if (!candidate) {
      return {
        status: 'rejected',
        value: '',
        category: 'Auto Added',
        request_id: requestId,
        message: 'Row sync rejected: empty token value.',
        category_fallback_used: true,
      }
    }
    const hintedCategory = this.firstCategoryHint(request.categories)
    if (!this.allowAutoAdd(candidate)) {
      return {
        status: 'rejected',
        value: candidate,
        category: 'Auto Added',
        request_id: requestId,
        message: `Row sync rejected for '${candidate}' by auto-add validation rules.`,
        category_fallback_used: true,
      }
    }

    const existingCategories = new Set(await this.listCategories())
    const { category, fallbackUsed } = await this.resolveSyncCategory(hintedCategory, existingCategories)
    const existing = (await this.pool.query(
      'SELECT 1 FROM lexicon_entries WHERE LOWER(category) = LOWER($1) AND normalized = $2 LIMIT 1',
      [category, candidate],
    )).rows[0]
    if (existing) {
      return {
        status: 'already_exists',
        value: candidate,
        category,
        request_id: requestId,
        message: `Row sync skipped: '${candidate}' already exists in category '${category}'.`,
        category_fallback_used: fallbackUsed,
      }
    }

    const nowIso = new Date().toISOString()
    await this.withTransaction(async (client) => {
      await client.query('INSERT INTO lexicon_categories(name) VALUES ($1) ON CONFLICT(name) DO NOTHING', [category])
      await client.query(
        `
          INSERT INTO lexicon_entries(
            category,
            value,
            normalized,
            source,
            confidence,
            first_seen_at,
            request_id,
            status
          ) VALUES ($1, $2, $3, 'auto', 1.0, $4, $5, 'pending_review')
        `,
        [category, candidate, candidate, nowIso, requestId],
      )
      await this.bumpMeta(client, 'lexicon')
    })

    return {
      status: 'added',
      value: candidate,
      category,
      request_id: requestId,
      message: `Row sync added '${candidate}' to category '${category}' (source=auto, status=pending_review).`,
      category_fallback_used: fallbackUsed,
    }
  }

  async close(): Promise<void> {
    await this.ready
    await this.pool.end()
  }

  private async readOwnedTableSnapshot(name: typeof OWNED_TABLES[number]): Promise<ExportSnapshotTable> {
    const columns = (await this.pool.query(
      `
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = $1
          AND table_name = $2
        ORDER BY ordinal_position ASC
      `,
      [this.schemaName, name],
    )).rows.map((row: DbRow) => String(row.column_name))
    const orderBy = name === 'lexicon_entries'
      ? ' ORDER BY id ASC'
      : name === 'lexicon_categories'
        ? ' ORDER BY name ASC'
        : ' ORDER BY id ASC'
    const result = columns.length
      ? await this.pool.query(`SELECT ${columns.map((column: string) => this.quoteIdent(column)).join(', ')} FROM ${this.quoteIdent(name)}${orderBy}`)
      : { rows: [] as QueryResultRow[] }
    return {
      name,
      columns,
      rows: result.rows.map((row: QueryResultRow) => columns.map((column: string) => row[column] ?? null)),
    }
  }

  private async lexiconVersion(): Promise<number> {
    await this.ready
    return Number((await this.pool.query('SELECT lexicon_version FROM lexicon_meta WHERE id = 1')).rows[0]?.lexicon_version ?? 0)
  }

  private async withTransaction<T>(callback: (client: PoolClient) => Promise<T>): Promise<T> {
    await this.ready
    const client = await this.pool.connect()
    let inTransaction = false
    try {
      await client.query('BEGIN')
      inTransaction = true
      const result = await callback(client)
      await client.query('COMMIT')
      inTransaction = false
      return result
    } catch (error) {
      if (inTransaction) {
        await client.query('ROLLBACK')
      }
      throw error
    } finally {
      client.release()
    }
  }

  private async syncSerialSequence(client: PoolClient, tableName: string, columnName: string): Promise<void> {
    const sequenceName = String((await client.query(
      'SELECT pg_get_serial_sequence($1, $2) AS sequence_name',
      [tableName, columnName],
    )).rows[0]?.sequence_name ?? '')
    if (!sequenceName) {
      return
    }
    const maxId = Number((await client.query(
      `SELECT COALESCE(MAX(${this.quoteIdent(columnName)}), 0) AS max_id FROM ${this.quoteIdent(tableName)}`,
    )).rows[0]?.max_id ?? 0)
    if (maxId > 0) {
      await client.query('SELECT setval($1, $2, true)', [sequenceName, maxId])
      return
    }
    await client.query('SELECT setval($1, 1, false)', [sequenceName])
  }

  private async bumpMeta(client: PoolClient | Pool, target: 'lexicon' | 'mwe'): Promise<void> {
    const table = target === 'lexicon' ? 'lexicon_meta' : 'mwe_meta'
    const column = target === 'lexicon' ? 'lexicon_version' : 'mwe_version'
    await client.query(
      `
        UPDATE ${this.quoteIdent(table)}
        SET ${this.quoteIdent(column)} = ${this.quoteIdent(column)} + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
      `,
    )
  }

  private quoteIdent(value: string): string {
    return `"${String(value).replace(/"/g, '""')}"`
  }

  private serializeRow(row: DbRow): Record<string, unknown> {
    return {
      id: Number(row.id),
      category: String(row.category ?? ''),
      value: String(row.value ?? ''),
      normalized: String(row.normalized ?? ''),
      source: String(row.source ?? 'manual'),
      confidence: row.confidence == null ? null : Number(row.confidence),
      first_seen_at: row.first_seen_at == null ? null : String(row.first_seen_at),
      request_id: row.request_id == null ? null : String(row.request_id),
      status: String(row.status ?? 'approved'),
      created_at: row.created_at == null ? null : String(row.created_at),
      reviewed_at: row.reviewed_at == null ? null : String(row.reviewed_at),
      reviewed_by: row.reviewed_by == null ? null : String(row.reviewed_by),
      review_note: row.review_note == null ? null : String(row.review_note),
    }
  }

  private normalizeQuery(query: LexiconSearchQuery) {
    const status = this.normalizeStatusFilter(query.status)
    const limit = Math.max(1, Math.min(1000, Number(query.limit ?? 100) || 100))
    const offset = Math.max(0, Number(query.offset ?? 0) || 0)
    let idMin = this.normalizeOptionalInt(query.id_min)
    let idMax = this.normalizeOptionalInt(query.id_max)
    if (idMin !== null && idMax !== null && idMin > idMax) {
      ;[idMin, idMax] = [idMax, idMin]
    }
    let confidenceMin = this.normalizeOptionalFloat(query.confidence_min)
    let confidenceMax = this.normalizeOptionalFloat(query.confidence_max)
    if (confidenceMin !== null && confidenceMax !== null && confidenceMin > confidenceMax) {
      ;[confidenceMin, confidenceMax] = [confidenceMax, confidenceMin]
    }
    const requestedSortBy = String(query.sort_by ?? 'id')
    const sortBy = ALLOWED_SORT_COLUMNS.has(requestedSortBy) ? requestedSortBy : 'id'
    const requestedSortDirection = String(query.sort_direction ?? 'desc').toLowerCase()
    const sortDirection = ALLOWED_SORT_DIRECTIONS.has(requestedSortDirection) ? requestedSortDirection : 'desc'
    return {
      status,
      limit,
      offset,
      category_filter: this.normalizeCategoryFilter(query.category_filter),
      value_filter: this.cleanText(query.value_filter ?? ''),
      source_filter: this.normalizeSourceFilter(query.source_filter),
      request_filter: this.cleanText(query.request_filter ?? ''),
      id_min: idMin,
      id_max: idMax,
      reviewed_by_filter: this.cleanText(query.reviewed_by_filter ?? ''),
      confidence_min: confidenceMin,
      confidence_max: confidenceMax,
      sort_by: sortBy,
      sort_direction: sortDirection,
    }
  }

  private normalizeStatusFilter(value: string | undefined): string {
    const cleaned = String(value ?? 'all').trim().toLowerCase()
    return ALLOWED_STATUS_FILTERS.has(cleaned) ? cleaned : 'all'
  }

  private normalizeSourceFilter(value: string | undefined): string {
    const cleaned = String(value ?? 'all').trim().toLowerCase()
    return ALLOWED_SOURCE_FILTERS.has(cleaned) ? cleaned : 'all'
  }

  private normalizeCategoryFilter(value: string | undefined): string {
    return this.cleanText(value ?? '')
  }

  private normalizeCategory(value: string): string {
    return this.cleanText(value)
  }

  private normalizeSource(value: string | undefined): string {
    return String(value ?? 'manual').trim().toLowerCase() === 'auto' ? 'auto' : 'manual'
  }

  private normalizeConfidence(value: number | undefined): number | null {
    if (value === undefined || value === null) {
      return null
    }
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) {
      return null
    }
    return Math.max(0, Math.min(1, numeric))
  }

  private normalizeEditableStatus(value: string): string {
    const cleaned = String(value ?? '').trim().toLowerCase()
    if (!EDITABLE_ENTRY_STATUSES.has(cleaned)) {
      throw new Error(`Invalid status '${value}'.`)
    }
    return cleaned
  }

  private normalizeOptionalInt(value: number | null | undefined): number | null {
    if (value === null || value === undefined) {
      return null
    }
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) {
      return null
    }
    return Math.trunc(numeric)
  }

  private normalizeOptionalFloat(value: number | null | undefined): number | null {
    if (value === null || value === undefined) {
      return null
    }
    const numeric = Number(value)
    return Number.isFinite(numeric) ? numeric : null
  }

  private cleanText(value: string): string {
    return String(value ?? '').trim()
  }

  private parseEntryId(value: number): number {
    return Math.max(0, Number(value) || 0)
  }

  private allowAutoAdd(candidate: string): boolean {
    const cleaned = this.cleanText(candidate).toLowerCase()
    if (!cleaned || AUTO_ADD_BLOCKLIST.has(cleaned)) {
      return false
    }
    return SAFE_TERM_RE.test(cleaned)
  }

  private firstCategoryHint(categories: string): string {
    for (const item of String(categories || '').split(',')) {
      const category = String(item).trim()
      if (category && category !== '-') {
        return category
      }
    }
    return ''
  }

  private resolveRowSyncCandidate(request: RowSyncRequest): string {
    for (const probe of [request.normalized, request.token, request.lemma]) {
      const candidate = this.cleanText(probe).toLowerCase()
      if (!candidate || candidate === '-') {
        continue
      }
      if (this.allowAutoAdd(candidate)) {
        return candidate
      }
    }
    return this.cleanText(request.normalized || request.token || request.lemma).toLowerCase()
  }

  private async resolveSyncCategory(hintedCategory: string, existingCategories: Set<string>): Promise<{ category: string; fallbackUsed: boolean }> {
    const cleanSuggested = this.cleanText(hintedCategory)
    if (!cleanSuggested) {
      return { category: 'Auto Added', fallbackUsed: true }
    }
    if (existingCategories.has(cleanSuggested)) {
      return { category: cleanSuggested, fallbackUsed: false }
    }
    if (AUTO_CREATE_SYNC_CATEGORIES.has(cleanSuggested)) {
      await this.createCategory({ name: cleanSuggested })
      existingCategories.add(cleanSuggested)
      return { category: cleanSuggested, fallbackUsed: false }
    }
    return { category: 'Auto Added', fallbackUsed: true }
  }
}

function normalizeSchemaName(input: string): string {
  const value = String(input ?? '').trim()
  if (!value) {
    throw new Error('Postgres schema name must not be empty.')
  }
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(value)) {
    throw new Error(`Invalid Postgres schema name: ${value}`)
  }
  return value
}
