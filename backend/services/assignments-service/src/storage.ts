import type {
  AssignmentsExportSnapshot,
  AssignmentsStatisticsRecord,
  UnitRecord,
  UnitSubunitDraft,
} from './repository.js'

export type Awaitable<T> = T | Promise<T>

export interface AssignmentsStore {
  createUnit(input: { subunits: UnitSubunitDraft[] }): Awaitable<UnitRecord>
  listAssignments(limit?: number, offset?: number): Awaitable<UnitRecord[]>
  getAssignmentById(id: number): Awaitable<UnitRecord | null>
  getAssignmentsByIds(ids: number[]): Awaitable<UnitRecord[]>
  updateAssignment(input: {
    assignment_id: number
    subunits: UnitSubunitDraft[]
  }): Awaitable<UnitRecord | null>
  deleteAssignment(id: number): Awaitable<boolean>
  bulkDelete(ids: number[]): Awaitable<{ deleted: number[]; not_found: number[] }>
  getAssignmentsStatistics(): Awaitable<AssignmentsStatisticsRecord>
  exportSnapshot(): Awaitable<AssignmentsExportSnapshot>
  isEmpty(): Awaitable<boolean>
  close(): Awaitable<void>
}
