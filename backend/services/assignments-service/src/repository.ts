import fs from 'node:fs'
import path from 'node:path'
import Database from 'better-sqlite3'

type DbRow = Record<string, unknown>

export interface AssignmentsExportSnapshotTable {
  name: string
  columns: string[]
  rows: unknown[][]
}

export interface AssignmentsExportSnapshot {
  tables: AssignmentsExportSnapshotTable[]
}

export interface UnitSubunitRecord {
  id: number
  unit_id: number
  subunit_code: string
  position: number
  content: string
  created_at: string | null
  updated_at: string | null
}

export interface UnitRecord {
  id: number
  unit_code: string
  unit_number: number
  subunit_count: number
  subunits: UnitSubunitRecord[]
  created_at: string | null
  updated_at: string | null
}

export interface UnitSubunitDraft {
  content: string
}

export interface AssignmentsStatisticsRecord {
  units: Array<{
    unit_code: string
    subunit_count: number
    created_at: string
  }>
  total_units: number
  total_subunits: number
  average_subunits_per_unit: number | null
}

export class AssignmentsRepository {
  private readonly db: Database.Database

  constructor(private readonly dbPath: string) {
    const resolvedPath = path.resolve(dbPath)
    fs.mkdirSync(path.dirname(resolvedPath), { recursive: true })
    this.db = new Database(resolvedPath)
    this.db.pragma('busy_timeout = 5000')
    this.db.pragma('journal_mode = WAL')
    this.db.pragma('foreign_keys = ON')
    this.ensureSchema()
  }

  createUnit(input: { subunits: UnitSubunitDraft[] }): UnitRecord {
    const subunits = normalizeSubunits(input.subunits)
    if (!subunits.length) {
      throw new Error('Unit must contain at least one subunit.')
    }

    const nowIso = new Date().toISOString()
    const transaction = this.db.transaction(() => {
      const unitNumber = this.getNextUnitNumber()
      const unitCode = formatUnitCode(unitNumber)
      const result = this.db.prepare(`
        INSERT INTO units(
          unit_code,
          unit_number,
          subunit_count,
          created_at,
          updated_at
        )
        VALUES (?, ?, ?, ?, ?)
      `).run(unitCode, unitNumber, subunits.length, nowIso, nowIso)
      const unitId = Number(result.lastInsertRowid)
      this.insertSubunits(unitId, unitNumber, subunits, nowIso)
      return unitId
    })

    return this.getAssignmentById(transaction())!
  }

  listAssignments(limit = 50, offset = 0): UnitRecord[] {
    const unitRows = this.db.prepare(`
      SELECT
        id,
        unit_code,
        unit_number,
        subunit_count,
        created_at,
        updated_at
      FROM units
      ORDER BY unit_number DESC
      LIMIT ? OFFSET ?
    `).all(Math.max(1, Number(limit) || 50), Math.max(0, Number(offset) || 0)) as DbRow[]
    return this.attachSubunits(unitRows)
  }

  getAssignmentById(id: number): UnitRecord | null {
    const row = this.db.prepare(`
      SELECT
        id,
        unit_code,
        unit_number,
        subunit_count,
        created_at,
        updated_at
      FROM units
      WHERE id = ?
      LIMIT 1
    `).get(Math.max(0, Number(id) || 0)) as DbRow | undefined
    if (!row) {
      return null
    }
    return this.attachSubunits([row])[0] ?? null
  }

  getAssignmentsByIds(ids: number[]): UnitRecord[] {
    const safeIds = [...new Set(ids.map((id) => Math.max(0, Number(id) || 0)).filter(Boolean))]
    if (!safeIds.length) {
      return []
    }
    const placeholders = safeIds.map(() => '?').join(', ')
    const rows = this.db.prepare(`
      SELECT
        id,
        unit_code,
        unit_number,
        subunit_count,
        created_at,
        updated_at
      FROM units
      WHERE id IN (${placeholders})
      ORDER BY unit_number DESC
    `).all(...safeIds) as DbRow[]
    return this.attachSubunits(rows)
  }

  updateAssignment(input: {
    assignment_id: number
    subunits: UnitSubunitDraft[]
  }): UnitRecord | null {
    const safeId = Math.max(0, Number(input.assignment_id) || 0)
    if (!safeId) {
      return null
    }

    const subunits = normalizeSubunits(input.subunits)
    if (!subunits.length) {
      throw new Error('Unit must contain at least one subunit.')
    }

    const current = this.db.prepare('SELECT unit_number FROM units WHERE id = ? LIMIT 1').get(safeId) as DbRow | undefined
    if (!current) {
      return null
    }

    const unitNumber = Number(current.unit_number ?? 0)
    const nowIso = new Date().toISOString()
    const transaction = this.db.transaction(() => {
      this.db.prepare(`
        UPDATE units
        SET subunit_count = ?,
            updated_at = ?
        WHERE id = ?
      `).run(subunits.length, nowIso, safeId)
      this.db.prepare('DELETE FROM unit_subunits WHERE unit_id = ?').run(safeId)
      this.insertSubunits(safeId, unitNumber, subunits, nowIso)
    })
    transaction()
    return this.getAssignmentById(safeId)
  }

  deleteAssignment(id: number): boolean {
    const safeId = Math.max(0, Number(id) || 0)
    if (!safeId) {
      return false
    }
    const result = this.db.prepare('DELETE FROM units WHERE id = ?').run(safeId)
    if (result.changes > 0) {
      this.syncSequence('units')
      this.syncSequence('unit_subunits')
    }
    return result.changes > 0
  }

  bulkDelete(ids: number[]): { deleted: number[]; not_found: number[] } {
    const safeIds = [...new Set(ids.map((id) => Math.max(0, Number(id) || 0)).filter(Boolean))]
    if (!safeIds.length) {
      return { deleted: [], not_found: [] }
    }
    const placeholders = safeIds.map(() => '?').join(', ')
    const existing = new Set<number>(
      (this.db.prepare(`SELECT id FROM units WHERE id IN (${placeholders})`).all(...safeIds) as DbRow[])
        .map((row) => Number(row.id)),
    )
    if (existing.size > 0) {
      this.db.prepare(`DELETE FROM units WHERE id IN (${placeholders})`).run(...safeIds)
      this.syncSequence('units')
      this.syncSequence('unit_subunits')
    }
    return {
      deleted: safeIds.filter((id) => existing.has(id)),
      not_found: safeIds.filter((id) => !existing.has(id)),
    }
  }

  getAssignmentsStatistics(): AssignmentsStatisticsRecord {
    const summary = this.db.prepare(`
      SELECT
        COUNT(*) AS total_units,
        COALESCE(SUM(subunit_count), 0) AS total_subunits
      FROM units
    `).get() as DbRow
    const totalUnits = Number(summary.total_units ?? 0)
    const totalSubunits = Number(summary.total_subunits ?? 0)
    const units = (this.db.prepare(`
      SELECT unit_code, subunit_count, created_at
      FROM units
      ORDER BY unit_number DESC
      LIMIT 100
    `).all() as DbRow[]).map((row) => ({
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

  exportSnapshot(): AssignmentsExportSnapshot {
    const tables: AssignmentsExportSnapshotTable[] = [
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
        rows: [],
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
        rows: [],
      },
    ]

    for (const table of tables) {
      const sql = `SELECT ${table.columns.join(', ')} FROM ${table.name} ORDER BY id ASC`
      table.rows = (this.db.prepare(sql).all() as DbRow[]).map((row) =>
        table.columns.map((column) => row[column]),
      )
    }

    return { tables }
  }

  isEmpty(): boolean {
    const unitsCount = Number((this.db.prepare('SELECT COUNT(*) AS cnt FROM units').get() as DbRow).cnt ?? 0)
    const subunitsCount = Number((this.db.prepare('SELECT COUNT(*) AS cnt FROM unit_subunits').get() as DbRow).cnt ?? 0)
    return unitsCount === 0 && subunitsCount === 0
  }

  close(): void {
    this.db.close()
  }

  private ensureSchema(): void {
    this.db.exec(`
      DROP TABLE IF EXISTS assignment_audio;
      DROP TABLE IF EXISTS assignments;

      CREATE TABLE IF NOT EXISTS units (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_code TEXT NOT NULL UNIQUE,
        unit_number INTEGER NOT NULL UNIQUE,
        subunit_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );

      CREATE TABLE IF NOT EXISTS unit_subunits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_id INTEGER NOT NULL,
        subunit_code TEXT NOT NULL,
        position INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(unit_id) REFERENCES units(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_units_unit_number
      ON units(unit_number DESC);

      CREATE INDEX IF NOT EXISTS idx_units_created_at
      ON units(created_at DESC);

      CREATE UNIQUE INDEX IF NOT EXISTS idx_unit_subunits_unit_position
      ON unit_subunits(unit_id, position);

      CREATE INDEX IF NOT EXISTS idx_unit_subunits_unit_id
      ON unit_subunits(unit_id, position ASC);
    `)
  }

  private attachSubunits(rows: DbRow[]): UnitRecord[] {
    if (!rows.length) {
      return []
    }
    const unitIds = rows.map((row) => Number(row.id))
    const subunitsByUnitId = this.listSubunitsByUnitIds(unitIds)
    return rows.map((row) => this.serializeUnit(row, subunitsByUnitId.get(Number(row.id)) ?? []))
  }

  private listSubunitsByUnitIds(unitIds: number[]): Map<number, UnitSubunitRecord[]> {
    const safeIds = [...new Set(unitIds.map((id) => Math.max(0, Number(id) || 0)).filter(Boolean))]
    if (!safeIds.length) {
      return new Map()
    }
    const placeholders = safeIds.map(() => '?').join(', ')
    const rows = this.db.prepare(`
      SELECT
        id,
        unit_id,
        subunit_code,
        position,
        content,
        created_at,
        updated_at
      FROM unit_subunits
      WHERE unit_id IN (${placeholders})
      ORDER BY unit_id ASC, position ASC
    `).all(...safeIds) as DbRow[]

    const grouped = new Map<number, UnitSubunitRecord[]>()
    for (const row of rows) {
      const unitId = Number(row.unit_id)
      const bucket = grouped.get(unitId) ?? []
      bucket.push(this.serializeSubunit(row))
      grouped.set(unitId, bucket)
    }
    return grouped
  }

  private insertSubunits(unitId: number, unitNumber: number, subunits: UnitSubunitDraft[], nowIso: string): void {
    const statement = this.db.prepare(`
      INSERT INTO unit_subunits(
        unit_id,
        subunit_code,
        position,
        content,
        created_at,
        updated_at
      )
      VALUES (?, ?, ?, ?, ?, ?)
    `)

    subunits.forEach((subunit, index) => {
      statement.run(
        unitId,
        formatSubunitCode(unitNumber, index),
        index,
        subunit.content,
        nowIso,
        nowIso,
      )
    })
  }

  private getNextUnitNumber(): number {
    const row = this.db.prepare('SELECT COALESCE(MAX(unit_number), 0) AS max_unit_number FROM units').get() as DbRow
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

  private syncSequence(tableName: string): void {
    const row = this.db.prepare(`SELECT MAX(id) AS max_id FROM ${tableName}`).get() as DbRow
    const maxId = Number(row.max_id ?? 0)
    this.db.prepare('UPDATE sqlite_sequence SET seq = ? WHERE name = ?').run(maxId, tableName)
    this.db.prepare('INSERT OR IGNORE INTO sqlite_sequence(name, seq) VALUES (?, ?)').run(tableName, maxId)
  }
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
