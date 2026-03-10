import { runPostgresMigrations } from '@vocabulary/shared'
import { Pool, type PoolClient, type QueryResultRow } from 'pg'
import type { AssignmentRecord, AssignmentsExportSnapshot } from './repository.js'

const SNAPSHOT_TABLES = [
  {
    name: 'assignments',
    columns: [
      'id',
      'title',
      'content_original',
      'content_completed',
      'status',
      'lexicon_coverage_percent',
      'created_at',
      'updated_at',
    ],
  },
  {
    name: 'assignment_audio',
    columns: [
      'id',
      'assignment_id',
      'audio_path',
      'audio_format',
      'voice',
      'style_preset',
      'duration_sec',
      'sample_rate',
      'created_at',
    ],
  },
] as const

type DbRow = Record<string, unknown>

export class PostgresAssignmentsRepository {
  private readonly pool: Pool
  private readonly ready: Promise<void>

  constructor(private readonly postgresUrl: string) {
    this.pool = new Pool({ connectionString: postgresUrl })
    this.ready = runPostgresMigrations(this.pool, {
      serviceName: 'assignments-service',
      migrationsDir: 'services/assignments-service/infrastructure/postgres_migrations',
    })
  }

  async saveAssignment(input: {
    title: string
    content_original: string
    content_completed: string
  }): Promise<AssignmentRecord> {
    await this.ready
    const title = this.cleanTitle(input.title)
    const nowIso = new Date().toISOString()
    const row = (await this.pool.query(
      `
        INSERT INTO assignments(
          title,
          content_original,
          content_completed,
          status,
          lexicon_coverage_percent,
          created_at,
          updated_at
        )
        VALUES ($1, $2, $3, 'PENDING', 0.0, $4, $5)
        RETURNING
          id,
          title,
          content_original,
          content_completed,
          status,
          lexicon_coverage_percent,
          created_at,
          updated_at
      `,
      [title, String(input.content_original ?? ''), String(input.content_completed ?? ''), nowIso, nowIso],
    )).rows[0] as DbRow
    return this.serializeAssignment(row)
  }

  async listAssignments(limit = 50, offset = 0): Promise<AssignmentRecord[]> {
    await this.ready
    const rows = (await this.pool.query(
      `
        SELECT
          id,
          title,
          content_original,
          content_completed,
          status,
          lexicon_coverage_percent,
          created_at,
          updated_at
        FROM assignments
        ORDER BY id DESC
        LIMIT $1 OFFSET $2
      `,
      [Math.max(1, Number(limit) || 50), Math.max(0, Number(offset) || 0)],
    )).rows as DbRow[]
    return rows.map((row) => this.serializeAssignment(row))
  }

  async getAssignmentById(id: number): Promise<AssignmentRecord | null> {
    await this.ready
    const row = (await this.pool.query(
      `
        SELECT
          id,
          title,
          content_original,
          content_completed,
          status,
          lexicon_coverage_percent,
          created_at,
          updated_at
        FROM assignments
        WHERE id = $1
        LIMIT 1
      `,
      [Math.max(0, Number(id) || 0)],
    )).rows[0] as DbRow | undefined
    return row ? this.serializeAssignment(row) : null
  }

  async getAssignmentsByIds(ids: number[]): Promise<AssignmentRecord[]> {
    await this.ready
    const safeIds = [...new Set(ids.map((id) => Math.max(0, Number(id) || 0)).filter(Boolean))]
    if (!safeIds.length) {
      return []
    }
    const rows = (await this.pool.query(
      `
        SELECT
          id,
          title,
          content_original,
          content_completed,
          status,
          lexicon_coverage_percent,
          created_at,
          updated_at
        FROM assignments
        WHERE id = ANY($1::int[])
      `,
      [safeIds],
    )).rows as DbRow[]
    return rows.map((row) => this.serializeAssignment(row))
  }

  async updateAssignmentContent(input: {
    assignment_id: number
    title: string
    content_original: string
    content_completed: string
  }): Promise<AssignmentRecord | null> {
    await this.ready
    const safeId = Math.max(0, Number(input.assignment_id) || 0)
    if (!safeId) {
      return null
    }
    const nowIso = new Date().toISOString()
    const row = (await this.pool.query(
      `
        UPDATE assignments
        SET title = $1,
            content_original = $2,
            content_completed = $3,
            updated_at = $4
        WHERE id = $5
        RETURNING
          id,
          title,
          content_original,
          content_completed,
          status,
          lexicon_coverage_percent,
          created_at,
          updated_at
      `,
      [
        this.cleanTitle(input.title),
        String(input.content_original ?? ''),
        String(input.content_completed ?? ''),
        nowIso,
        safeId,
      ],
    )).rows[0] as DbRow | undefined
    return row ? this.serializeAssignment(row) : null
  }

  async updateAssignmentStatus(input: {
    assignment_id: number
    status: string
    lexicon_coverage_percent: number
  }): Promise<AssignmentRecord | null> {
    await this.ready
    const safeId = Math.max(0, Number(input.assignment_id) || 0)
    if (!safeId) {
      return null
    }
    const nowIso = new Date().toISOString()
    const row = (await this.pool.query(
      `
        UPDATE assignments
        SET status = $1,
            lexicon_coverage_percent = $2,
            updated_at = $3
        WHERE id = $4
        RETURNING
          id,
          title,
          content_original,
          content_completed,
          status,
          lexicon_coverage_percent,
          created_at,
          updated_at
      `,
      [
        String(input.status ?? 'PENDING').trim().toUpperCase() || 'PENDING',
        Number(input.lexicon_coverage_percent ?? 0),
        nowIso,
        safeId,
      ],
    )).rows[0] as DbRow | undefined
    return row ? this.serializeAssignment(row) : null
  }

  async deleteAssignment(id: number): Promise<boolean> {
    await this.ready
    const safeId = Math.max(0, Number(id) || 0)
    if (!safeId) {
      return false
    }
    const result = await this.pool.query('DELETE FROM assignments WHERE id = $1', [safeId])
    return (result.rowCount ?? 0) > 0
  }

  async bulkDelete(ids: number[]): Promise<{ deleted: number[]; not_found: number[] }> {
    await this.ready
    const safeIds = [...new Set(ids.map((id) => Math.max(0, Number(id) || 0)).filter(Boolean))]
    if (!safeIds.length) {
      return { deleted: [], not_found: [] }
    }
    const existing = new Set<number>(
      ((await this.pool.query('SELECT id FROM assignments WHERE id = ANY($1::int[])', [safeIds])).rows as DbRow[])
        .map((row) => Number(row.id)),
    )
    if (existing.size > 0) {
      await this.pool.query('DELETE FROM assignments WHERE id = ANY($1::int[])', [safeIds])
    }
    return {
      deleted: safeIds.filter((id) => existing.has(id)),
      not_found: safeIds.filter((id) => !existing.has(id)),
    }
  }

  async getCoverageStats(): Promise<Array<{ title: string; coverage_pct: number; created_at: string }>> {
    await this.ready
    return ((await this.pool.query(
      `
        SELECT title, lexicon_coverage_percent, created_at
        FROM assignments
        ORDER BY created_at DESC
        LIMIT 100
      `,
    )).rows as DbRow[]).map((row) => ({
      title: String(row.title ?? ''),
      coverage_pct: Number(row.lexicon_coverage_percent ?? 0),
      created_at: String(row.created_at ?? ''),
    }))
  }

  async exportSnapshot(): Promise<AssignmentsExportSnapshot> {
    await this.ready
    const tables = []
    for (const table of SNAPSHOT_TABLES) {
      const rows = (await this.pool.query(
        `SELECT ${table.columns.join(', ')} FROM ${table.name} ORDER BY id ASC`,
      )).rows as DbRow[]
      tables.push({
        name: table.name,
        columns: [...table.columns],
        rows: rows.map((row) => table.columns.map((column) => row[column])),
      })
    }
    return { tables }
  }

  async isEmpty(): Promise<boolean> {
    await this.ready
    const assignmentsCount = Number((await this.pool.query('SELECT COUNT(*)::int AS cnt FROM assignments')).rows[0]?.cnt ?? 0)
    const audioCount = Number((await this.pool.query('SELECT COUNT(*)::int AS cnt FROM assignment_audio')).rows[0]?.cnt ?? 0)
    return assignmentsCount === 0 && audioCount === 0
  }

  async importSnapshot(snapshot: AssignmentsExportSnapshot): Promise<void> {
    await this.ready
    const tableMap = new Map(snapshot.tables.map((table) => [table.name, table]))
    await this.withTransaction(async (client) => {
      await client.query('TRUNCATE TABLE assignment_audio, assignments RESTART IDENTITY')
      for (const table of SNAPSHOT_TABLES) {
        const source = tableMap.get(table.name)
        if (!source || !source.rows.length) {
          continue
        }
        const valuePlaceholders = source.rows.map((_, rowIndex) => {
          const base = rowIndex * source.columns.length
          return `(${source.columns.map((_, columnIndex) => `$${base + columnIndex + 1}`).join(', ')})`
        }).join(', ')
        const values = source.rows.flat()
        await client.query(
          `INSERT INTO ${table.name}(${source.columns.join(', ')}) VALUES ${valuePlaceholders}`,
          values,
        )
      }
      await this.syncSequence(client, 'assignments', 'id')
      await this.syncSequence(client, 'assignment_audio', 'id')
    })
  }

  async close(): Promise<void> {
    await this.pool.end()
  }

  private serializeAssignment(row: DbRow): AssignmentRecord {
    return {
      id: Number(row.id),
      title: String(row.title ?? ''),
      content_original: String(row.content_original ?? ''),
      content_completed: String(row.content_completed ?? ''),
      status: String(row.status ?? 'PENDING'),
      lexicon_coverage_percent: Number(row.lexicon_coverage_percent ?? 0),
      created_at: row.created_at == null ? null : String(row.created_at),
      updated_at: row.updated_at == null ? null : String(row.updated_at),
    }
  }

  private cleanTitle(value: string): string {
    const cleaned = String(value ?? '').trim()
    return cleaned || 'Untitled Assignment'
  }

  private async withTransaction<T>(callback: (client: PoolClient) => Promise<T>): Promise<T> {
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

  private async syncSequence(client: PoolClient | Pool, tableName: string, columnName: string): Promise<void> {
    const sequenceName = `${tableName}_${columnName}_seq`
    const exists = (await client.query(
      'SELECT to_regclass($1) IS NOT NULL AS exists',
      [sequenceName],
    )).rows[0] as QueryResultRow
    if (!exists?.exists) {
      return
    }
    const maxId = Number((await client.query(
      `SELECT COALESCE(MAX(${columnName}), 0) AS max_id FROM ${tableName}`,
    )).rows[0]?.max_id ?? 0)
    if (maxId > 0) {
      await client.query('SELECT setval($1, $2, true)', [sequenceName, maxId])
      return
    }
    await client.query(
      'SELECT setval($1, 1, false)',
      [sequenceName],
    )
  }
}
