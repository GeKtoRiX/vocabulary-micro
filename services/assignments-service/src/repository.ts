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

export interface AssignmentRecord {
  id: number
  title: string
  content_original: string
  content_completed: string
  status: string
  lexicon_coverage_percent: number
  created_at: string | null
  updated_at: string | null
}

export class AssignmentsRepository {
  private readonly db: Database.Database

  constructor(private readonly dbPath: string) {
    const resolvedPath = path.resolve(dbPath)
    fs.mkdirSync(path.dirname(resolvedPath), { recursive: true })
    this.db = new Database(resolvedPath)
    this.db.pragma('busy_timeout = 5000')
    this.db.pragma('journal_mode = WAL')
    this.ensureSchema()
  }

  saveAssignment(input: {
    title: string
    content_original: string
    content_completed: string
  }): AssignmentRecord {
    const title = this.cleanTitle(input.title)
    const nowIso = new Date().toISOString()
    const result = this.db.prepare(`
      INSERT INTO assignments(
        title,
        content_original,
        content_completed,
        status,
        lexicon_coverage_percent,
        created_at,
        updated_at
      )
      VALUES (?, ?, ?, 'PENDING', 0.0, ?, ?)
    `).run(title, String(input.content_original ?? ''), String(input.content_completed ?? ''), nowIso, nowIso)
    return this.getAssignmentById(Number(result.lastInsertRowid))!
  }

  listAssignments(limit = 50, offset = 0): AssignmentRecord[] {
    const rows = this.db.prepare(`
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
      LIMIT ? OFFSET ?
    `).all(Math.max(1, Number(limit) || 50), Math.max(0, Number(offset) || 0)) as DbRow[]
    return rows.map((row) => this.serializeAssignment(row))
  }

  getAssignmentById(id: number): AssignmentRecord | null {
    const row = this.db.prepare(`
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
      WHERE id = ?
      LIMIT 1
    `).get(Math.max(0, Number(id) || 0)) as DbRow | undefined
    return row ? this.serializeAssignment(row) : null
  }

  updateAssignmentContent(input: {
    assignment_id: number
    title: string
    content_original: string
    content_completed: string
  }): AssignmentRecord | null {
    const safeId = Math.max(0, Number(input.assignment_id) || 0)
    if (!safeId) {
      return null
    }
    const nowIso = new Date().toISOString()
    const result = this.db.prepare(`
      UPDATE assignments
      SET title = ?,
          content_original = ?,
          content_completed = ?,
          updated_at = ?
      WHERE id = ?
    `).run(
      this.cleanTitle(input.title),
      String(input.content_original ?? ''),
      String(input.content_completed ?? ''),
      nowIso,
      safeId,
    )
    if (result.changes <= 0) {
      return null
    }
    return this.getAssignmentById(safeId)
  }

  updateAssignmentStatus(input: {
    assignment_id: number
    status: string
    lexicon_coverage_percent: number
  }): AssignmentRecord | null {
    const safeId = Math.max(0, Number(input.assignment_id) || 0)
    if (!safeId) {
      return null
    }
    const nowIso = new Date().toISOString()
    this.db.prepare(`
      UPDATE assignments
      SET status = ?,
          lexicon_coverage_percent = ?,
          updated_at = ?
      WHERE id = ?
    `).run(
      String(input.status ?? 'PENDING').trim().toUpperCase() || 'PENDING',
      Number(input.lexicon_coverage_percent ?? 0),
      nowIso,
      safeId,
    )
    return this.getAssignmentById(safeId)
  }

  deleteAssignment(id: number): boolean {
    const safeId = Math.max(0, Number(id) || 0)
    if (!safeId) {
      return false
    }
    const result = this.db.prepare('DELETE FROM assignments WHERE id = ?').run(safeId)
    if (result.changes > 0) {
      this.syncSequence('assignments')
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
      (this.db.prepare(`SELECT id FROM assignments WHERE id IN (${placeholders})`).all(...safeIds) as DbRow[])
        .map((row) => Number(row.id)),
    )
    if (existing.size > 0) {
      this.db.prepare(`DELETE FROM assignments WHERE id IN (${placeholders})`).run(...safeIds)
      this.syncSequence('assignments')
    }
    return {
      deleted: safeIds.filter((id) => existing.has(id)),
      not_found: safeIds.filter((id) => !existing.has(id)),
    }
  }

  getCoverageStats(): Array<{ title: string; coverage_pct: number; created_at: string }> {
    return (this.db.prepare(`
      SELECT title, lexicon_coverage_percent, created_at
      FROM assignments
      ORDER BY created_at DESC
      LIMIT 100
    `).all() as DbRow[]).map((row) => ({
      title: String(row.title ?? ''),
      coverage_pct: Number(row.lexicon_coverage_percent ?? 0),
      created_at: String(row.created_at ?? ''),
    }))
  }

  exportSnapshot(): AssignmentsExportSnapshot {
    const tables: AssignmentsExportSnapshotTable[] = [
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
        rows: [],
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
    const assignmentsCount = Number((this.db.prepare('SELECT COUNT(*) AS cnt FROM assignments').get() as DbRow).cnt ?? 0)
    const audioCount = Number((this.db.prepare('SELECT COUNT(*) AS cnt FROM assignment_audio').get() as DbRow).cnt ?? 0)
    return assignmentsCount === 0 && audioCount === 0
  }

  close(): void {
    this.db.close()
  }

  private ensureSchema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content_original TEXT NOT NULL,
        content_completed TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        lexicon_coverage_percent REAL NOT NULL DEFAULT 0.0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
      CREATE INDEX IF NOT EXISTS idx_assignments_created_at
      ON assignments(created_at DESC);
      CREATE INDEX IF NOT EXISTS idx_assignments_status
      ON assignments(status);
      CREATE TABLE IF NOT EXISTS assignment_audio (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assignment_id INTEGER NOT NULL,
        audio_path TEXT NOT NULL,
        audio_format TEXT NOT NULL DEFAULT 'wav',
        voice TEXT NOT NULL DEFAULT 'af_heart',
        style_preset TEXT NOT NULL DEFAULT 'neutral',
        duration_sec REAL NOT NULL DEFAULT 0.0,
        sample_rate INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
      CREATE INDEX IF NOT EXISTS idx_assignment_audio_assignment_id_created
      ON assignment_audio(assignment_id, created_at DESC);
    `)
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

  private syncSequence(tableName: string): void {
    const row = this.db.prepare(`SELECT MAX(id) AS max_id FROM ${tableName}`).get() as DbRow
    const maxId = Number(row.max_id ?? 0)
    this.db.prepare(`UPDATE sqlite_sequence SET seq = ? WHERE name = ?`).run(maxId, tableName)
    this.db.prepare(`INSERT OR IGNORE INTO sqlite_sequence(name, seq) VALUES (?, ?)`).run(tableName, maxId)
  }
}
