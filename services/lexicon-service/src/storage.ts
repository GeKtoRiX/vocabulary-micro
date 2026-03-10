import type {
  AddEntryRequest,
  BulkAddEntriesRequest,
  BulkStatusRequest,
  CategoryRequest,
  DeleteEntriesRequest,
  LexiconSearchQuery,
  RowSyncRequest,
  UpdateEntryRequest,
  UpsertMweExpressionRequest,
  UpsertMweSenseRequest,
} from './repository.js'

export type Awaitable<T> = T | Promise<T>

export interface LexiconStore {
  searchEntries(query: LexiconSearchQuery): Awaitable<Record<string, unknown>>
  addEntry(request: AddEntryRequest): Awaitable<{ message: string }>
  addEntries(request: BulkAddEntriesRequest): Awaitable<{ inserted_count: number; message: string }>
  updateEntry(entryId: number, request: UpdateEntryRequest): Awaitable<Record<string, unknown>>
  deleteEntries(request: DeleteEntriesRequest): Awaitable<Record<string, unknown>>
  bulkUpdateStatus(request: BulkStatusRequest): Awaitable<Record<string, unknown>>
  createCategory(request: CategoryRequest): Awaitable<Record<string, unknown>>
  deleteCategory(name: string): Awaitable<Record<string, unknown>>
  listCategories(): Awaitable<string[]>
  getStatistics(): Awaitable<Record<string, unknown>>
  buildIndex(): Awaitable<Record<string, unknown>>
  exportSnapshot(): Awaitable<{ tables: Array<{ name: string; columns: string[]; rows: unknown[][] }> }>
  upsertMweExpression(request: UpsertMweExpressionRequest): Awaitable<{ expression_id: number }>
  upsertMweSense(request: UpsertMweSenseRequest): Awaitable<{ sense_id: number }>
  syncRow(request: RowSyncRequest): Awaitable<Record<string, unknown>>
  close(): Awaitable<void>
}
