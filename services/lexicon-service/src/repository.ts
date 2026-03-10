import fs from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import Database from 'better-sqlite3'

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

export interface LexiconSearchQuery {
  status?: string
  limit?: number
  offset?: number
  value_filter?: string
  category_filter?: string
  source_filter?: string
  request_filter?: string
  sort_by?: string
  sort_direction?: string
  semantic_raw_query?: string | null
  id_min?: number | null
  id_max?: number | null
  reviewed_by_filter?: string
  confidence_min?: number | null
  confidence_max?: number | null
}

export interface AddEntryRequest {
  category: string
  value: string
  source?: string
  confidence?: number
}

export interface UpdateEntryRequest {
  status: string
  category: string
  value: string
  query: LexiconSearchQuery
}

export interface DeleteEntriesRequest {
  entry_ids: number[]
  query: LexiconSearchQuery
}

export interface BulkStatusRequest {
  entry_ids: number[]
  status: string
  query: LexiconSearchQuery
}

export interface CategoryRequest {
  name: string
}

export interface RowSyncRequest {
  token: string
  normalized: string
  lemma: string
  categories: string
}

export interface ExportSnapshotTable {
  name: string
  columns: string[]
  rows: unknown[][]
}

export interface BulkAddEntriesRequest {
  entries: Array<{ category: string; value: string }>
  source?: string
  confidence?: number
  request_id?: string | null
}

export interface UpsertMweExpressionRequest {
  canonical_form: string
  expression_type: string
  is_separable?: boolean
  max_gap_tokens?: number
  base_lemma?: string | null
  particle?: string | null
}

export interface UpsertMweSenseRequest {
  expression_id: number
  sense_key: string
  gloss: string
  usage_label: string
  example?: string
  priority?: number
}

type DbRow = Record<string, unknown>

export class LexiconRepository {
  private readonly db: Database.Database

  constructor(private readonly dbPath: string) {
    const resolvedPath = path.resolve(dbPath)
    fs.mkdirSync(path.dirname(resolvedPath), { recursive: true })
    this.db = new Database(resolvedPath)
    this.db.pragma('busy_timeout = 5000')
    this.db.pragma('foreign_keys = ON')
    this.db.pragma('journal_mode = WAL')
    this.ensureSchema()
  }

  searchEntries(query: LexiconSearchQuery): Record<string, unknown> {
    const safe = this.normalizeQuery(query)
    if (!this.tableExists('lexicon_entries')) {
      return this.emptySearchResult(safe, `SQLite file not found: ${this.dbPath}`)
    }

    const whereClauses: string[] = []
    const params: Array<string | number> = []
    if (safe.status !== 'all') {
      whereClauses.push('status = ?')
      params.push(safe.status)
    }
    if (safe.source_filter !== 'all') {
      whereClauses.push('source = ?')
      params.push(safe.source_filter)
    }
    if (safe.category_filter) {
      whereClauses.push('category = ? COLLATE NOCASE')
      params.push(safe.category_filter)
    }
    if (safe.value_filter) {
      whereClauses.push('(value LIKE ? OR normalized LIKE ?)')
      params.push(`%${safe.value_filter}%`, `%${safe.value_filter.toLowerCase()}%`)
    }
    if (safe.request_filter) {
      whereClauses.push('request_id LIKE ?')
      params.push(`%${safe.request_filter}%`)
    }
    if (safe.id_min !== null) {
      whereClauses.push('id >= ?')
      params.push(safe.id_min)
    }
    if (safe.id_max !== null) {
      whereClauses.push('id <= ?')
      params.push(safe.id_max)
    }
    if (safe.reviewed_by_filter) {
      whereClauses.push('reviewed_by LIKE ?')
      params.push(`%${safe.reviewed_by_filter}%`)
    }
    if (safe.confidence_min !== null) {
      whereClauses.push('confidence >= ?')
      params.push(safe.confidence_min)
    }
    if (safe.confidence_max !== null) {
      whereClauses.push('confidence <= ?')
      params.push(safe.confidence_max)
    }

    const whereSql = whereClauses.length ? ` WHERE ${whereClauses.join(' AND ')}` : ''
    const rows = this.db.prepare(
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
        ORDER BY ${safe.sort_by} ${safe.sort_direction.toUpperCase()}
        LIMIT ? OFFSET ?
      `,
    ).all(...params, safe.limit, safe.offset) as DbRow[]

    const countsByStatus = Object.fromEntries(
      (this.db.prepare(
        'SELECT status, COUNT(*) AS cnt FROM lexicon_entries GROUP BY status ORDER BY status ASC',
      ).all() as DbRow[]).map((row) => [String(row.status ?? ''), Number(row.cnt ?? 0)]),
    )
    const categories = this.listCategories()
    const totalRows = Number((this.db.prepare('SELECT COUNT(*) AS cnt FROM lexicon_entries').get() as DbRow | undefined)?.cnt ?? 0)

    return {
      rows: rows.map((row) => this.serializeRow(row)),
      total_rows: totalRows,
      filtered_rows: rows.length,
      counts_by_status: countsByStatus,
      available_categories: categories,
      message: `Loaded ${rows.length} row(s) from ${path.basename(this.dbPath)}.`,
    }
  }

  addEntry(request: AddEntryRequest): { message: string } {
    const category = this.normalizeCategory(request.category) || 'Auto Added'
    const value = this.cleanText(request.value)
    const normalized = value.toLowerCase()
    if (!value) {
      throw new Error('Value must not be empty.')
    }
    const source = this.normalizeSource(request.source)
    const confidence = this.normalizeConfidence(request.confidence)
    const nowIso = new Date().toISOString()
    const status = source === 'auto' ? 'pending_review' : 'approved'

    const insert = this.db.prepare(`
      INSERT OR IGNORE INTO lexicon_categories(name)
      VALUES (?)
    `)
    const insertEntry = this.db.prepare(`
      INSERT OR IGNORE INTO lexicon_entries(
        category,
        value,
        normalized,
        source,
        confidence,
        first_seen_at,
        request_id,
        example_usage,
        status
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `)

    this.db.transaction(() => {
      insert.run(category)
      insertEntry.run(category, value, normalized, source, confidence, nowIso, null, null, status)
    })()

    return { message: `Entry '${value}' added to '${category}'.` }
  }

  addEntries(request: BulkAddEntriesRequest): { inserted_count: number; message: string } {
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

    const insertCategory = this.db.prepare('INSERT OR IGNORE INTO lexicon_categories(name) VALUES (?)')
    const insertEntry = this.db.prepare(`
      INSERT OR IGNORE INTO lexicon_entries(
        category,
        value,
        normalized,
        source,
        confidence,
        first_seen_at,
        request_id,
        example_usage,
        status
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `)

    let insertedCount = 0
    this.db.transaction(() => {
      for (const entry of entries) {
        insertCategory.run(entry.category)
        const result = insertEntry.run(
          entry.category,
          entry.value,
          entry.value.toLowerCase(),
          source,
          confidence,
          nowIso,
          requestId,
          null,
          status,
        )
        insertedCount += result.changes
      }
    })()

    return {
      inserted_count: insertedCount,
      message: `Inserted ${insertedCount} of ${entries.length} requested entries.`,
    }
  }

  updateEntry(entryId: number, request: UpdateEntryRequest): Record<string, unknown> {
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

    const current = this.db.prepare(
      'SELECT reviewed_at, reviewed_by, review_note FROM lexicon_entries WHERE id = ?',
    ).get(safeId) as DbRow | undefined
    if (!current) {
      throw new Error(`Update skipped: entry id=${safeId} not found.`)
    }

    const categories = new Set(this.listCategories())
    if (!categories.has(category)) {
      throw new Error(`Update skipped: category '${category}' does not exist. Use 'Add Category' first.`)
    }

    const reviewedAt = status === 'pending_review'
      ? null
      : String(current.reviewed_at ?? '') || new Date().toISOString()
    const reviewedBy = status === 'pending_review' ? null : String(current.reviewed_by ?? '') || 'ui'
    const reviewNote = status === 'pending_review' ? null : (current.review_note ?? null)

    const result = this.db.prepare(`
      UPDATE lexicon_entries
      SET category = ?,
          value = ?,
          normalized = ?,
          status = ?,
          reviewed_at = ?,
          reviewed_by = ?,
          review_note = ?
      WHERE id = ?
    `).run(category, value, value.toLowerCase(), status, reviewedAt, reviewedBy, reviewNote, safeId)

    if (result.changes <= 0) {
      throw new Error(`Update skipped: entry id=${safeId} not found.`)
    }
    const payload = this.searchEntries(request.query)
    payload.message = `Updated entry id=${safeId}.`
    return payload
  }

  deleteEntries(request: DeleteEntriesRequest): Record<string, unknown> {
    const ids = [...new Set((request.entry_ids ?? []).map((item) => this.parseEntryId(item)).filter((item) => item > 0))]
    if (!ids.length) {
      throw new Error('Delete skipped: select a valid entry first.')
    }
    const placeholders = ids.map(() => '?').join(', ')
    const result = this.db.prepare(`DELETE FROM lexicon_entries WHERE id IN (${placeholders})`).run(...ids)
    if (result.changes > 0) {
      this.syncSequence('lexicon_entries')
    }
    const payload = this.searchEntries(request.query)
    payload.message = result.changes <= 0
      ? `Delete skipped: no matching entries for ids=${JSON.stringify(ids)}.`
      : ids.length === 1 ? `Deleted entry id=${ids[0]}.` : `Deleted ${result.changes} selected rows.`
    return payload
  }

  bulkUpdateStatus(request: BulkStatusRequest): Record<string, unknown> {
    const ids = [...new Set((request.entry_ids ?? []).map((item) => this.parseEntryId(item)).filter((item) => item > 0))]
    const targetStatus = this.normalizeEditableStatus(request.status)
    let updated = 0
    const errors: string[] = []

    const update = this.db.prepare(`
      UPDATE lexicon_entries
      SET status = ?,
          reviewed_at = ?,
          reviewed_by = ?,
          review_note = ?
      WHERE id = ?
    `)
    const get = this.db.prepare('SELECT id, reviewed_at, reviewed_by, review_note FROM lexicon_entries WHERE id = ?')

    this.db.transaction(() => {
      for (const id of ids) {
        const current = get.get(id) as DbRow | undefined
        if (!current) {
          errors.push(`id=${id} not found`)
          continue
        }
        const reviewedAt = targetStatus === 'pending_review' ? null : String(current.reviewed_at ?? '') || new Date().toISOString()
        const reviewedBy = targetStatus === 'pending_review' ? null : String(current.reviewed_by ?? '') || 'ui'
        const reviewNote = targetStatus === 'pending_review' ? null : (current.review_note ?? null)
        const result = update.run(targetStatus, reviewedAt, reviewedBy, reviewNote, id)
        updated += result.changes
      }
    })()

    const payload = this.searchEntries(request.query)
    payload.message = errors.length
      ? `Updated ${updated} of ${ids.length} entries to '${targetStatus}'. Errors: ${errors.length}.`
      : `Updated ${updated} of ${ids.length} entries to '${targetStatus}'.`
    return payload
  }

  createCategory(request: CategoryRequest): Record<string, unknown> {
    const cleaned = this.normalizeCategory(request.name)
    if (!cleaned) {
      return { categories: this.listCategories(), message: 'Category name must not be empty.' }
    }
    const result = this.db.prepare('INSERT OR IGNORE INTO lexicon_categories(name) VALUES (?)').run(cleaned)
    return {
      categories: this.listCategories(),
      message: result.changes > 0 ? `Created category '${cleaned}'.` : `Category '${cleaned}' already exists.`,
    }
  }

  deleteCategory(name: string): Record<string, unknown> {
    const cleaned = this.normalizeCategory(name)
    if (!cleaned) {
      return { categories: this.listCategories(), message: 'Category name must not be empty.' }
    }
    const usage = this.db.prepare('SELECT COUNT(*) AS cnt FROM lexicon_entries WHERE category = ?').get(cleaned) as DbRow
    const count = Number(usage.cnt ?? 0)
    if (count > 0) {
      return {
        categories: this.listCategories(),
        message: `Delete category skipped: '${cleaned}' is used by ${count} entries.`,
      }
    }
    const result = this.db.prepare('DELETE FROM lexicon_categories WHERE name = ?').run(cleaned)
    return {
      categories: this.listCategories(),
      message: result.changes > 0 ? `Deleted category '${cleaned}'.` : `Category '${cleaned}' not found.`,
    }
  }

  getStatistics(): Record<string, unknown> {
    const total = Number((this.db.prepare('SELECT COUNT(*) AS cnt FROM lexicon_entries').get() as DbRow | undefined)?.cnt ?? 0)
    const countsByStatus = Object.fromEntries(
      (this.db.prepare('SELECT status, COUNT(*) AS cnt FROM lexicon_entries GROUP BY status ORDER BY cnt DESC').all() as DbRow[])
        .map((row) => [String(row.status ?? ''), Number(row.cnt ?? 0)]),
    )
    const countsBySource = Object.fromEntries(
      (this.db.prepare('SELECT source, COUNT(*) AS cnt FROM lexicon_entries GROUP BY source ORDER BY cnt DESC').all() as DbRow[])
        .map((row) => [String(row.source ?? ''), Number(row.cnt ?? 0)]),
    )
    const categories = (this.db.prepare(
      'SELECT category, COUNT(*) AS cnt FROM lexicon_entries GROUP BY category ORDER BY cnt DESC LIMIT 50',
    ).all() as DbRow[]).map((row) => ({
      name: String(row.category ?? ''),
      count: Number(row.cnt ?? 0),
    }))
    return {
      total_entries: total,
      counts_by_status: countsByStatus,
      counts_by_source: countsBySource,
      categories,
    }
  }

  buildIndex(): Record<string, unknown> {
    const rows = this.db.prepare(`
      SELECT category, normalized, status
      FROM lexicon_entries
      WHERE TRIM(normalized) <> ''
    `).all() as DbRow[]
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
        const key = parts.join(' ')
        multiWordIndex[key] = [...(multiWordIndex[key] ?? []), category]
      }
    }
    return {
      single_word_index: singleWordIndex,
      multi_word_index: multiWordIndex,
      total_rows: rows.length,
      lexicon_version: this.lexiconVersion(),
    }
  }

  exportSnapshot(): { tables: ExportSnapshotTable[] } {
    const tables = [
      'lexicon_entries',
      'lexicon_categories',
      'lexicon_meta',
      'mwe_expressions',
      'mwe_senses',
      'mwe_meta',
    ]
      .filter((name) => this.tableExists(name))
      .map((name) => this.readOwnedTableSnapshot(name))
    return { tables }
  }

  upsertMweExpression(request: UpsertMweExpressionRequest): { expression_id: number } {
    const canonicalForm = this.cleanText(request.canonical_form).toLowerCase()
    if (!canonicalForm) {
      throw new Error('canonical_form must not be empty')
    }
    const expressionType = String(request.expression_type ?? '').trim().toLowerCase()
    if (!['phrasal_verb', 'idiom'].includes(expressionType)) {
      throw new Error("expression_type must be 'phrasal_verb' or 'idiom'")
    }
    this.db.prepare(`
      INSERT INTO mwe_expressions(
        canonical_form,
        expression_type,
        base_lemma,
        particle,
        is_separable,
        max_gap_tokens
      ) VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT(canonical_form) DO UPDATE SET
        expression_type = excluded.expression_type,
        base_lemma = excluded.base_lemma,
        particle = excluded.particle,
        is_separable = excluded.is_separable,
        max_gap_tokens = excluded.max_gap_tokens,
        updated_at = CURRENT_TIMESTAMP
    `).run(
      canonicalForm,
      expressionType,
      this.cleanText(String(request.base_lemma ?? '')).toLowerCase(),
      this.cleanText(String(request.particle ?? '')).toLowerCase(),
      request.is_separable ? 1 : 0,
      Math.max(1, Number(request.max_gap_tokens ?? 4) || 4),
    )

    const row = this.db.prepare(`
      SELECT id
      FROM mwe_expressions
      WHERE canonical_form = ?
    `).get(canonicalForm) as DbRow | undefined
    if (!row) {
      throw new Error('Failed to upsert mwe expression')
    }
    return { expression_id: Number(row.id ?? 0) }
  }

  upsertMweSense(request: UpsertMweSenseRequest): { sense_id: number } {
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
    this.db.prepare(`
      INSERT INTO mwe_senses(
        expression_id,
        sense_key,
        gloss,
        usage_label,
        example,
        priority
      ) VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT(expression_id, sense_key) DO UPDATE SET
        gloss = excluded.gloss,
        usage_label = excluded.usage_label,
        example = excluded.example,
        priority = excluded.priority,
        updated_at = CURRENT_TIMESTAMP
    `).run(expressionId, senseKey, gloss, usageLabel, example, priority)

    const row = this.db.prepare(`
      SELECT id
      FROM mwe_senses
      WHERE expression_id = ? AND sense_key = ?
    `).get(expressionId, senseKey) as DbRow | undefined
    if (!row) {
      throw new Error('Failed to upsert mwe sense')
    }
    return { sense_id: Number(row.id ?? 0) }
  }

  syncRow(request: RowSyncRequest): Record<string, unknown> {
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

    const existingCategories = new Set(this.listCategories())
    const { category, fallbackUsed } = this.resolveSyncCategory(hintedCategory, existingCategories)
    const existing = this.db.prepare(
      'SELECT 1 FROM lexicon_entries WHERE category = ? COLLATE NOCASE AND normalized = ? LIMIT 1',
    ).get(category, candidate)
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
    this.db.transaction(() => {
      this.db.prepare('INSERT OR IGNORE INTO lexicon_categories(name) VALUES (?)').run(category)
      this.db.prepare(`
        INSERT INTO lexicon_entries(
          category,
          value,
          normalized,
          source,
          confidence,
          first_seen_at,
          request_id,
          status
        ) VALUES (?, ?, ?, 'auto', 1.0, ?, ?, 'pending_review')
      `).run(category, candidate, candidate, nowIso, requestId)
    })()

    return {
      status: 'added',
      value: candidate,
      category,
      request_id: requestId,
      message: `Row sync added '${candidate}' to category '${category}' (source=auto, status=pending_review).`,
      category_fallback_used: fallbackUsed,
    }
  }

  close(): void {
    this.db.close()
  }

  private ensureSchema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS lexicon_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        value TEXT NOT NULL,
        normalized TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'manual',
        confidence REAL,
        first_seen_at TEXT,
        request_id TEXT,
        example_usage TEXT,
        status TEXT NOT NULL DEFAULT 'approved',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TEXT,
        reviewed_by TEXT,
        review_note TEXT,
        UNIQUE(category, normalized)
      );
      CREATE TABLE IF NOT EXISTS lexicon_categories (
        name TEXT PRIMARY KEY,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
      CREATE TABLE IF NOT EXISTS lexicon_meta (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        lexicon_version INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
      INSERT OR IGNORE INTO lexicon_meta(id, lexicon_version, updated_at)
      VALUES (1, 0, CURRENT_TIMESTAMP);
      CREATE INDEX IF NOT EXISTS idx_lexicon_entries_status ON lexicon_entries(status);
      CREATE INDEX IF NOT EXISTS idx_lexicon_entries_normalized ON lexicon_entries(normalized);
      CREATE INDEX IF NOT EXISTS idx_lexicon_entries_confidence ON lexicon_entries(confidence);
      CREATE TRIGGER IF NOT EXISTS trg_lexicon_entries_insert
      AFTER INSERT ON lexicon_entries
      BEGIN
        UPDATE lexicon_meta
        SET lexicon_version = lexicon_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1;
      END;
      CREATE TRIGGER IF NOT EXISTS trg_lexicon_entries_update
      AFTER UPDATE ON lexicon_entries
      BEGIN
        UPDATE lexicon_meta
        SET lexicon_version = lexicon_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1;
      END;
      CREATE TRIGGER IF NOT EXISTS trg_lexicon_entries_delete
      AFTER DELETE ON lexicon_entries
      BEGIN
        UPDATE lexicon_meta
        SET lexicon_version = lexicon_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1;
      END;
      CREATE TABLE IF NOT EXISTS mwe_expressions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        canonical_form TEXT NOT NULL UNIQUE,
        expression_type TEXT NOT NULL CHECK(expression_type IN ('phrasal_verb', 'idiom')),
        base_lemma TEXT NOT NULL DEFAULT '',
        particle TEXT NOT NULL DEFAULT '',
        is_separable INTEGER NOT NULL DEFAULT 0,
        max_gap_tokens INTEGER NOT NULL DEFAULT 4,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
      CREATE TABLE IF NOT EXISTS mwe_senses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        expression_id INTEGER NOT NULL REFERENCES mwe_expressions(id) ON DELETE CASCADE,
        sense_key TEXT NOT NULL,
        gloss TEXT NOT NULL,
        usage_label TEXT NOT NULL CHECK(usage_label IN ('literal', 'idiomatic')),
        example TEXT NOT NULL DEFAULT '',
        priority INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(expression_id, sense_key)
      );
      CREATE TABLE IF NOT EXISTS mwe_meta (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        mwe_version INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
      INSERT OR IGNORE INTO mwe_meta(id, mwe_version, updated_at)
      VALUES (1, 0, CURRENT_TIMESTAMP);
      CREATE INDEX IF NOT EXISTS idx_mwe_senses_expression_id ON mwe_senses(expression_id);
      CREATE INDEX IF NOT EXISTS idx_mwe_expressions_type ON mwe_expressions(expression_type);
      CREATE TRIGGER IF NOT EXISTS trg_mwe_expressions_insert
      AFTER INSERT ON mwe_expressions
      BEGIN
        UPDATE mwe_meta
        SET mwe_version = mwe_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1;
      END;
      CREATE TRIGGER IF NOT EXISTS trg_mwe_expressions_update
      AFTER UPDATE ON mwe_expressions
      BEGIN
        UPDATE mwe_meta
        SET mwe_version = mwe_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1;
      END;
      CREATE TRIGGER IF NOT EXISTS trg_mwe_expressions_delete
      AFTER DELETE ON mwe_expressions
      BEGIN
        UPDATE mwe_meta
        SET mwe_version = mwe_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1;
      END;
      CREATE TRIGGER IF NOT EXISTS trg_mwe_senses_insert
      AFTER INSERT ON mwe_senses
      BEGIN
        UPDATE mwe_meta
        SET mwe_version = mwe_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1;
      END;
      CREATE TRIGGER IF NOT EXISTS trg_mwe_senses_update
      AFTER UPDATE ON mwe_senses
      BEGIN
        UPDATE mwe_meta
        SET mwe_version = mwe_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1;
      END;
      CREATE TRIGGER IF NOT EXISTS trg_mwe_senses_delete
      AFTER DELETE ON mwe_senses
      BEGIN
        UPDATE mwe_meta
        SET mwe_version = mwe_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1;
      END;
      INSERT OR IGNORE INTO lexicon_categories(name)
      SELECT DISTINCT category
      FROM lexicon_entries
      WHERE TRIM(category) <> '';
    `)
  }

  private emptySearchResult(safe: ReturnType<LexiconRepository['normalizeQuery']>, message: string): Record<string, unknown> {
    return {
      rows: [],
      total_rows: 0,
      filtered_rows: 0,
      counts_by_status: {},
      available_categories: ['Auto Added'],
      message,
      ...safe,
    }
  }

  private tableExists(name: string): boolean {
    return Boolean(this.db.prepare(
      "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
    ).get(name))
  }

  private lexiconVersion(): number {
    return Number((this.db.prepare(
      'SELECT lexicon_version FROM lexicon_meta WHERE id = 1',
    ).get() as DbRow | undefined)?.lexicon_version ?? 0)
  }

  private readOwnedTableSnapshot(name: string): ExportSnapshotTable {
    const columns = (this.db.prepare(`PRAGMA table_info(${name})`).all() as DbRow[])
      .map((row) => String(row.name ?? '').trim())
      .filter(Boolean)
    const orderBy = name === 'lexicon_entries'
      ? ' ORDER BY id ASC'
      : name === 'lexicon_categories'
        ? ' ORDER BY name ASC'
        : ' ORDER BY id ASC'
    const rows = columns.length
      ? this.db.prepare(`SELECT ${columns.join(', ')} FROM ${name}${orderBy}`).raw().all() as unknown[][]
      : []
    return { name, columns, rows }
  }

  listCategories(): string[] {
    const rows = this.db.prepare(`
      SELECT name
      FROM (
        SELECT name AS name FROM lexicon_categories WHERE TRIM(name) <> ''
        UNION
        SELECT category AS name FROM lexicon_entries WHERE TRIM(category) <> ''
      )
      ORDER BY name ASC
    `).all() as DbRow[]
    const categories = rows
      .map((row) => String(row.name ?? '').trim())
      .filter(Boolean)
    if (!categories.includes('Auto Added')) {
      categories.push('Auto Added')
    }
    return [...new Set(categories)].sort((a, b) => a.localeCompare(b))
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
    const sortDirection = ALLOWED_SORT_DIRECTIONS.has(requestedSortDirection)
      ? requestedSortDirection
      : 'desc'
    return {
      status,
      limit,
      offset,
      value_filter: this.cleanText(query.value_filter),
      category_filter: this.cleanText(query.category_filter),
      source_filter: this.normalizeSourceFilter(query.source_filter),
      request_filter: this.cleanText(query.request_filter),
      sort_by: sortBy,
      sort_direction: sortDirection,
      semantic_raw_query: query.semantic_raw_query ?? null,
      id_min: idMin,
      id_max: idMax,
      reviewed_by_filter: this.cleanText(query.reviewed_by_filter),
      confidence_min: confidenceMin,
      confidence_max: confidenceMax,
    }
  }

  private serializeRow(row: DbRow): Record<string, unknown> {
    return {
      id: Number(row.id),
      category: String(row.category ?? ''),
      value: String(row.value ?? ''),
      normalized: String(row.normalized ?? ''),
      source: String(row.source ?? ''),
      confidence: row.confidence === null || row.confidence === undefined ? null : Number(row.confidence),
      first_seen_at: row.first_seen_at === null || row.first_seen_at === undefined ? null : String(row.first_seen_at),
      request_id: row.request_id === null || row.request_id === undefined ? null : String(row.request_id),
      status: String(row.status ?? ''),
      created_at: row.created_at === null || row.created_at === undefined ? null : String(row.created_at),
      reviewed_at: row.reviewed_at === null || row.reviewed_at === undefined ? null : String(row.reviewed_at),
      reviewed_by: row.reviewed_by === null || row.reviewed_by === undefined ? null : String(row.reviewed_by),
      review_note: row.review_note === null || row.review_note === undefined ? null : String(row.review_note),
    }
  }

  private parseEntryId(value: unknown): number {
    const parsed = Number.parseInt(String(value ?? ''), 10)
    return Number.isFinite(parsed) ? parsed : 0
  }

  private normalizeOptionalInt(value: unknown): number | null {
    if (value === null || value === undefined || value === '') {
      return null
    }
    const parsed = Number.parseInt(String(value), 10)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null
  }

  private normalizeOptionalFloat(value: unknown): number | null {
    if (value === null || value === undefined || value === '') {
      return null
    }
    const parsed = Number.parseFloat(String(value))
    return Number.isFinite(parsed) ? parsed : null
  }

  private normalizeConfidence(value: unknown): number | null {
    const parsed = this.normalizeOptionalFloat(value)
    return parsed === null ? null : parsed
  }

  private normalizeEditableStatus(value: string): string {
    const normalized = String(value ?? '').trim().toLowerCase()
    return EDITABLE_ENTRY_STATUSES.has(normalized) ? normalized : 'pending_review'
  }

  private normalizeStatusFilter(value: unknown): string {
    const normalized = String(value ?? 'all').trim().toLowerCase()
    return ALLOWED_STATUS_FILTERS.has(normalized) ? normalized : 'all'
  }

  private normalizeSourceFilter(value: unknown): string {
    const normalized = String(value ?? 'all').trim().toLowerCase()
    return ALLOWED_SOURCE_FILTERS.has(normalized) ? normalized : 'all'
  }

  private normalizeSource(value: unknown): string {
    const normalized = String(value ?? 'manual').trim().toLowerCase()
    return normalized === 'auto' ? 'auto' : 'manual'
  }

  private normalizeCategory(value: unknown): string {
    return this.cleanText(value)
  }

  private normalizeValue(value: unknown): string {
    return this.cleanText(value).toLowerCase()
  }

  private cleanText(value: unknown): string {
    return String(value ?? '').replace(/\s+/g, ' ').trim()
  }

  private syncSequence(tableName: string): void {
    const row = this.db.prepare(`SELECT MAX(id) AS max_id FROM ${tableName}`).get() as DbRow
    const maxId = Number(row.max_id ?? 0)
    this.db.prepare(`
      UPDATE sqlite_sequence
      SET seq = ?
      WHERE name = ?
    `).run(maxId, tableName)
    this.db.prepare(`
      INSERT OR IGNORE INTO sqlite_sequence(name, seq)
      VALUES (?, ?)
    `).run(tableName, maxId)
  }

  private resolveRowSyncCandidate(request: RowSyncRequest): string {
    const probes = [
      this.canonicalizeExpression(request.normalized),
      this.canonicalizeExpression(request.token),
      this.normalizeLexeme(request.lemma),
      this.normalizeLexeme(request.normalized),
      this.normalizeLexeme(request.token),
    ]
    let fallback = ''
    for (const probe of probes) {
      const candidate = String(probe ?? '').trim().toLowerCase()
      if (!candidate || candidate === '-') {
        continue
      }
      if (!fallback) {
        fallback = candidate
      }
      if (this.allowAutoAdd(candidate)) {
        return candidate
      }
    }
    return fallback
  }

  private canonicalizeExpression(value: string): string {
    return this.cleanText(value).toLowerCase()
  }

  private normalizeLexeme(value: string): string {
    return this.cleanText(value).toLowerCase()
  }

  private firstCategoryHint(categories: string): string {
    for (const raw of String(categories ?? '').split(',')) {
      const clean = raw.trim()
      if (clean && clean !== '-') {
        return clean
      }
    }
    return ''
  }

  private resolveSyncCategory(suggestedCategory: string, existingCategories: Set<string>): { category: string; fallbackUsed: boolean } {
    const cleanSuggested = String(suggestedCategory ?? '').trim()
    if (!cleanSuggested) {
      return { category: 'Auto Added', fallbackUsed: true }
    }
    if (existingCategories.has(cleanSuggested)) {
      return { category: cleanSuggested, fallbackUsed: false }
    }
    if (AUTO_CREATE_SYNC_CATEGORIES.has(cleanSuggested)) {
      this.db.prepare('INSERT OR IGNORE INTO lexicon_categories(name) VALUES (?)').run(cleanSuggested)
      existingCategories.add(cleanSuggested)
      return { category: cleanSuggested, fallbackUsed: false }
    }
    return { category: 'Auto Added', fallbackUsed: true }
  }

  private allowAutoAdd(candidate: string): boolean {
    const cleaned = String(candidate ?? '').trim().toLowerCase()
    if (!cleaned) {
      return false
    }
    if (AUTO_ADD_BLOCKLIST.has(cleaned)) {
      return false
    }
    if (cleaned.length < 2) {
      return false
    }
    if (/^\d+$/.test(cleaned)) {
      return false
    }
    return SAFE_TERM_RE.test(cleaned)
  }
}
