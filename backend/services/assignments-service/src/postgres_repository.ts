import { runPostgresMigrations } from '@vocabulary/shared'
import { Pool, type PoolClient, type QueryResultRow } from 'pg'
import type {
  AssignmentsExportSnapshot,
  AssignmentsStatisticsRecord,
  UnitRecord,
  UnitSubunitDraft,
  UnitSubunitRecord,
} from './repository.js'

const SNAPSHOT_TABLES = [
  {
    name: 'units',
    columns: [
      'id',
      'unit_code',
      'unit_number',
      'subunit_count',
      'created_at',
      'updated_at',
    ],
  },
  {
    name: 'unit_subunits',
    columns: [
      'id',
      'unit_id',
      'subunit_code',
      'position',
      'content',
      'created_at',
      'updated_at',
    ],
  },
] as const

type DbRow = Record<string, unknown>

export class PostgresAssignmentsRepository {
  private readonly pool: Pool
  private readonly ready: Promise<void>
  private readonly schemaName: string

  constructor(private readonly postgresUrl: string, schemaName = 'assignments') {
    this.schemaName = normalizeSchemaName(schemaName)
    this.pool = new Pool({
      connectionString: postgresUrl,
      options: `-c search_path=${this.schemaName},public`,
    })
    this.ready = runPostgresMigrations(this.pool, {
      serviceName: 'assignments-service',
      migrationsDir: 'backend/services/assignments-service/infrastructure/postgres_migrations',
      schemaName: this.schemaName,
    })
  }

  async createUnit(input: { subunits: UnitSubunitDraft[] }): Promise<UnitRecord> {
    await this.ready
    const subunits = normalizeSubunits(input.subunits)
    if (!subunits.length) {
      throw new Error('Unit must contain at least one subunit.')
    }

    return this.withTransaction(async (client) => {
      const nowIso = new Date().toISOString()
      const nextUnitNumber = await this.getNextUnitNumber(client)
      const unitCode = formatUnitCode(nextUnitNumber)
      const unitRow = (await client.query(
        `
          INSERT INTO units(
            unit_code,
            unit_number,
            subunit_count,
            created_at,
            updated_at
          )
          VALUES ($1, $2, $3, $4, $5)
          RETURNING
            id,
            unit_code,
            unit_number,
            subunit_count,
            created_at,
            updated_at
        `,
        [unitCode, nextUnitNumber, subunits.length, nowIso, nowIso],
      )).rows[0] as DbRow
      await this.insertSubunits(client, Number(unitRow.id), nextUnitNumber, subunits, nowIso)
      return this.getAssignmentById(Number(unitRow.id), client) as Promise<UnitRecord>
    })
  }

  async listAssignments(limit = 50, offset = 0): Promise<UnitRecord[]> {
    await this.ready
    const rows = (await this.pool.query(
      `
        SELECT
          id,
          unit_code,
          unit_number,
          subunit_count,
          created_at,
          updated_at
        FROM units
        ORDER BY unit_number DESC
        LIMIT $1 OFFSET $2
      `,
      [Math.max(1, Number(limit) || 50), Math.max(0, Number(offset) || 0)],
    )).rows as DbRow[]
    return this.attachSubunits(rows)
  }

  async getAssignmentById(id: number, client: Pool | PoolClient = this.pool): Promise<UnitRecord | null> {
    await this.ready
    const row = (await client.query(
      `
        SELECT
          id,
          unit_code,
          unit_number,
          subunit_count,
          created_at,
          updated_at
        FROM units
        WHERE id = $1
        LIMIT 1
      `,
      [Math.max(0, Number(id) || 0)],
    )).rows[0] as DbRow | undefined
    if (!row) {
      return null
    }
    return (await this.attachSubunits([row], client))[0] ?? null
  }

  async getAssignmentsByIds(ids: number[]): Promise<UnitRecord[]> {
    await this.ready
    const safeIds = [...new Set(ids.map((id) => Math.max(0, Number(id) || 0)).filter(Boolean))]
    if (!safeIds.length) {
      return []
    }
    const rows = (await this.pool.query(
      `
        SELECT
          id,
          unit_code,
          unit_number,
          subunit_count,
          created_at,
          updated_at
        FROM units
        WHERE id = ANY($1::int[])
        ORDER BY unit_number DESC
      `,
      [safeIds],
    )).rows as DbRow[]
    return this.attachSubunits(rows)
  }

  async updateAssignment(input: {
    assignment_id: number
    subunits: UnitSubunitDraft[]
  }): Promise<UnitRecord | null> {
    await this.ready
    const safeId = Math.max(0, Number(input.assignment_id) || 0)
    if (!safeId) {
      return null
    }

    const subunits = normalizeSubunits(input.subunits)
    if (!subunits.length) {
      throw new Error('Unit must contain at least one subunit.')
    }

    return this.withTransaction(async (client) => {
      const existing = (await client.query(
        'SELECT unit_number FROM units WHERE id = $1 LIMIT 1',
        [safeId],
      )).rows[0] as DbRow | undefined
      if (!existing) {
        return null
      }

      const unitNumber = Number(existing.unit_number ?? 0)
      const nowIso = new Date().toISOString()
      await client.query(
        `
          UPDATE units
          SET subunit_count = $1,
              updated_at = $2
          WHERE id = $3
        `,
        [subunits.length, nowIso, safeId],
      )
      await client.query('DELETE FROM unit_subunits WHERE unit_id = $1', [safeId])
      await this.insertSubunits(client, safeId, unitNumber, subunits, nowIso)
      return this.getAssignmentById(safeId, client)
    })
  }

  async deleteAssignment(id: number): Promise<boolean> {
    await this.ready
    const safeId = Math.max(0, Number(id) || 0)
    if (!safeId) {
      return false
    }
    const result = await this.pool.query('DELETE FROM units WHERE id = $1', [safeId])
    return (result.rowCount ?? 0) > 0
  }

  async bulkDelete(ids: number[]): Promise<{ deleted: number[]; not_found: number[] }> {
    await this.ready
    const safeIds = [...new Set(ids.map((id) => Math.max(0, Number(id) || 0)).filter(Boolean))]
    if (!safeIds.length) {
      return { deleted: [], not_found: [] }
    }
    const existing = new Set<number>(
      ((await this.pool.query('SELECT id FROM units WHERE id = ANY($1::int[])', [safeIds])).rows as DbRow[])
        .map((row) => Number(row.id)),
    )
    if (existing.size > 0) {
      await this.pool.query('DELETE FROM units WHERE id = ANY($1::int[])', [safeIds])
    }
    return {
      deleted: safeIds.filter((id) => existing.has(id)),
      not_found: safeIds.filter((id) => !existing.has(id)),
    }
  }

  async getAssignmentsStatistics(): Promise<AssignmentsStatisticsRecord> {
    await this.ready
    const summary = (await this.pool.query(
      `
        SELECT
          COUNT(*)::int AS total_units,
          COALESCE(SUM(subunit_count), 0)::int AS total_subunits
        FROM units
      `,
    )).rows[0] as DbRow
    const totalUnits = Number(summary.total_units ?? 0)
    const totalSubunits = Number(summary.total_subunits ?? 0)
    const units = ((await this.pool.query(
      `
        SELECT unit_code, subunit_count, created_at
        FROM units
        ORDER BY unit_number DESC
        LIMIT 100
      `,
    )).rows as DbRow[]).map((row) => ({
      unit_code: String(row.unit_code ?? ''),
      subunit_count: Number(row.subunit_count ?? 0),
      created_at: String(row.created_at ?? ''),
    }))

    return {
      units,
      total_units: totalUnits,
      total_subunits: totalSubunits,
      average_subunits_per_unit: totalUnits > 0 ? Number((totalSubunits / totalUnits).toFixed(2)) : null,
    }
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
    const unitsCount = Number((await this.pool.query('SELECT COUNT(*)::int AS cnt FROM units')).rows[0]?.cnt ?? 0)
    const subunitsCount = Number((await this.pool.query('SELECT COUNT(*)::int AS cnt FROM unit_subunits')).rows[0]?.cnt ?? 0)
    return unitsCount === 0 && subunitsCount === 0
  }

  async importSnapshot(snapshot: AssignmentsExportSnapshot): Promise<void> {
    await this.ready
    const tableMap = new Map(snapshot.tables.map((table) => [table.name, table]))
    await this.withTransaction(async (client) => {
      await client.query('TRUNCATE TABLE unit_subunits, units RESTART IDENTITY CASCADE')
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
      await this.syncSequence(client, 'units', 'id')
      await this.syncSequence(client, 'unit_subunits', 'id')
    })
  }

  async close(): Promise<void> {
    await this.pool.end()
  }

  private async attachSubunits(rows: DbRow[], client: Pool | PoolClient = this.pool): Promise<UnitRecord[]> {
    if (!rows.length) {
      return []
    }
    const unitIds = rows.map((row) => Number(row.id))
    const subunitsByUnitId = await this.listSubunitsByUnitIds(unitIds, client)
    return rows.map((row) => this.serializeUnit(row, subunitsByUnitId.get(Number(row.id)) ?? []))
  }

  private async listSubunitsByUnitIds(unitIds: number[], client: Pool | PoolClient): Promise<Map<number, UnitSubunitRecord[]>> {
    const safeIds = [...new Set(unitIds.map((id) => Math.max(0, Number(id) || 0)).filter(Boolean))]
    if (!safeIds.length) {
      return new Map()
    }
    const rows = (await client.query(
      `
        SELECT
          id,
          unit_id,
          subunit_code,
          position,
          content,
          created_at,
          updated_at
        FROM unit_subunits
        WHERE unit_id = ANY($1::int[])
        ORDER BY unit_id ASC, position ASC
      `,
      [safeIds],
    )).rows as DbRow[]

    const grouped = new Map<number, UnitSubunitRecord[]>()
    for (const row of rows) {
      const unitId = Number(row.unit_id)
      const bucket = grouped.get(unitId) ?? []
      bucket.push(this.serializeSubunit(row))
      grouped.set(unitId, bucket)
    }
    return grouped
  }

  private async insertSubunits(
    client: PoolClient,
    unitId: number,
    unitNumber: number,
    subunits: UnitSubunitDraft[],
    nowIso: string,
  ): Promise<void> {
    for (const [index, subunit] of subunits.entries()) {
      await client.query(
        `
          INSERT INTO unit_subunits(
            unit_id,
            subunit_code,
            position,
            content,
            created_at,
            updated_at
          )
          VALUES ($1, $2, $3, $4, $5, $6)
        `,
        [unitId, formatSubunitCode(unitNumber, index), index, subunit.content, nowIso, nowIso],
      )
    }
  }

  private async getNextUnitNumber(client: PoolClient): Promise<number> {
    const row = (await client.query(
      'SELECT COALESCE(MAX(unit_number), 0) AS max_unit_number FROM units',
    )).rows[0] as DbRow
    return Number(row.max_unit_number ?? 0) + 1
  }

  private serializeUnit(row: DbRow, subunits: UnitSubunitRecord[]): UnitRecord {
    return {
      id: Number(row.id),
      unit_code: String(row.unit_code ?? ''),
      unit_number: Number(row.unit_number ?? 0),
      subunit_count: Number(row.subunit_count ?? subunits.length),
      subunits,
      created_at: row.created_at == null ? null : String(row.created_at),
      updated_at: row.updated_at == null ? null : String(row.updated_at),
    }
  }

  private serializeSubunit(row: DbRow): UnitSubunitRecord {
    return {
      id: Number(row.id),
      unit_id: Number(row.unit_id),
      subunit_code: String(row.subunit_code ?? ''),
      position: Number(row.position ?? 0),
      content: String(row.content ?? ''),
      created_at: row.created_at == null ? null : String(row.created_at),
      updated_at: row.updated_at == null ? null : String(row.updated_at),
    }
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
    const sequenceName = `${this.schemaName}.${tableName}_${columnName}_seq`
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

function normalizeSubunits(subunits: UnitSubunitDraft[]): UnitSubunitDraft[] {
  return (Array.isArray(subunits) ? subunits : [])
    .map((subunit) => ({ content: String(subunit?.content ?? '').trim() }))
    .filter((subunit) => subunit.content.length > 0)
}

function formatUnitCode(unitNumber: number): string {
  return `Unit${String(Math.max(1, unitNumber)).padStart(2, '0')}`
}

function formatSubunitCode(unitNumber: number, index: number): string {
  return `${Math.max(1, unitNumber)}${toAlphaIndex(index)}`
}

function toAlphaIndex(index: number): string {
  let value = Math.max(0, index)
  let result = ''
  do {
    result = String.fromCharCode(65 + (value % 26)) + result
    value = Math.floor(value / 26) - 1
  } while (value >= 0)
  return result
}
