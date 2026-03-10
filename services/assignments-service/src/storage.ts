import type { AssignmentRecord, AssignmentsExportSnapshot } from './repository.js'

export type Awaitable<T> = T | Promise<T>

export interface AssignmentsStore {
  saveAssignment(input: {
    title: string
    content_original: string
    content_completed: string
  }): Awaitable<AssignmentRecord>
  listAssignments(limit?: number, offset?: number): Awaitable<AssignmentRecord[]>
  getAssignmentById(id: number): Awaitable<AssignmentRecord | null>
  getAssignmentsByIds(ids: number[]): Awaitable<AssignmentRecord[]>
  updateAssignmentContent(input: {
    assignment_id: number
    title: string
    content_original: string
    content_completed: string
  }): Awaitable<AssignmentRecord | null>
  updateAssignmentStatus(input: {
    assignment_id: number
    status: string
    lexicon_coverage_percent: number
  }): Awaitable<AssignmentRecord | null>
  deleteAssignment(id: number): Awaitable<boolean>
  bulkDelete(ids: number[]): Awaitable<{ deleted: number[]; not_found: number[] }>
  getCoverageStats(): Awaitable<Array<{ title: string; coverage_pct: number; created_at: string }>>
  exportSnapshot(): Awaitable<AssignmentsExportSnapshot>
  isEmpty(): Awaitable<boolean>
  close(): Awaitable<void>
}
