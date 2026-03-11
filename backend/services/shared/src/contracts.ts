function fail(message: string): never {
  throw new Error(`Internal contract violation: ${message}`)
}

function assertObject(value: unknown, label: string): asserts value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    fail(`${label} must be an object`)
  }
}

function assertString(value: unknown, label: string): asserts value is string {
  if (typeof value !== 'string') {
    fail(`${label} must be a string`)
  }
}

function assertBoolean(value: unknown, label: string): asserts value is boolean {
  if (typeof value !== 'boolean') {
    fail(`${label} must be a boolean`)
  }
}

function assertNumber(value: unknown, label: string): asserts value is number {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    fail(`${label} must be a number`)
  }
}

function assertInteger(value: unknown, label: string): asserts value is number {
  assertNumber(value, label)
  if (!Number.isInteger(value)) {
    fail(`${label} must be an integer`)
  }
}

function assertArray(value: unknown, label: string): asserts value is unknown[] {
  if (!Array.isArray(value)) {
    fail(`${label} must be an array`)
  }
}

function assertStringArray(value: unknown, label: string): asserts value is string[] {
  assertArray(value, label)
  value.forEach((item, index) => assertString(item, `${label}[${index}]`))
}

function assertNumberRecord(value: unknown, label: string): asserts value is Record<string, number> {
  assertObject(value, label)
  for (const [key, entry] of Object.entries(value)) {
    assertNumber(entry, `${label}.${key}`)
  }
}

function assertStringArrayRecord(value: unknown, label: string): asserts value is Record<string, string[]> {
  assertObject(value, label)
  for (const [key, entry] of Object.entries(value)) {
    assertStringArray(entry, `${label}.${key}`)
  }
}

export interface InternalWarmupStatus {
  running: boolean
  ready: boolean
  failed: boolean
  error_message: string
  elapsed_sec: number | null
}

export interface ParseRequestContract {
  text: string
  sync?: boolean
  third_pass_enabled?: boolean
  think_mode?: boolean
}

export interface ParseRowContract {
  index: number
  token: string
  normalized: string
  lemma: string
  categories: string
  source: string
  matched_form: string
  confidence: string
  known: string
}

export interface ParseResultContract {
  rows: ParseRowContract[]
  summary: Record<string, unknown>
  status_message: string
  error_message: string
}

export interface ExtractSentenceResultContract {
  sentence: string
}

export interface LexiconCategoryCountContract {
  name: string
  count: number
}

export interface LexiconStatisticsContract {
  total_entries: number
  counts_by_status: Record<string, number>
  counts_by_source: Record<string, number>
  categories: LexiconCategoryCountContract[]
}

export interface LexiconSearchRowContract {
  id: number
  category: string
  value: string
  normalized: string
  source: string
  confidence: number
  first_seen_at: string | null
  request_id: string | null
  status: string
  created_at: string | null
  reviewed_at: string | null
  reviewed_by: string | null
  review_note: string | null
}

export interface LexiconSearchResultContract {
  rows: LexiconSearchRowContract[]
  total_rows: number
  filtered_rows: number
  counts_by_status: Record<string, number>
  available_categories: string[]
  message: string
}

export interface RowSyncResultContract {
  status: string
  value: string
  category: string
  request_id: string
  message: string
  category_fallback_used: boolean
}

export interface CategoryMutationResultContract {
  categories: string[]
  message: string
}

export interface LexiconIndexContract {
  single_word_index: Record<string, string[]>
  multi_word_index: Record<string, string[]>
  total_rows: number
  lexicon_version: number
}

export interface ExportSnapshotTableContract {
  name: string
  columns: string[]
  rows: unknown[][]
}

export interface ExportSnapshotContract {
  tables: ExportSnapshotTableContract[]
}

export interface UnitStatisticsRowContract {
  unit_code: string
  subunit_count: number
  created_at: string
}

export interface AssignmentsStatisticsContract {
  units: UnitStatisticsRowContract[]
  total_units: number
  total_subunits: number
  average_subunits_per_unit: number | null
}

export interface AssignmentMatchContract {
  entry_id: number
  term: string
  category: string
  source: string
  occurrences: number
}

export interface AssignmentMissingWordContract {
  term: string
  occurrences: number
  example_usage: string
}

export interface AssignmentDiffChunkContract {
  operation: string
  original_text: string
  completed_text: string
}

export interface AssignmentScanResultContract {
  assignment_id: number | null
  title: string
  content_original: string
  content_completed: string
  word_count: number
  known_token_count: number
  unknown_token_count: number
  lexicon_coverage_percent: number
  assignment_status: string
  message: string
  duration_ms: number
  matches: AssignmentMatchContract[]
  missing_words: AssignmentMissingWordContract[]
  diff_chunks: AssignmentDiffChunkContract[]
}

export interface BulkRescanResultContract {
  success_count: number
  failed_count: number
  message: string
}

export interface QuickAddSuggestionContract {
  term: string
  recommended_category: string
  candidate_categories: string[]
  confidence: number
  rationale: string
  suggested_example_usage: string
}

export interface MutationMessageContract {
  message: string
}

export interface InsertManyResultContract extends MutationMessageContract {
  inserted_count: number
}

export interface MweExpressionMutationContract {
  expression_id: number
}

export interface MweSenseMutationContract {
  sense_id: number
}

export function assertWarmupStatusContract(value: unknown): asserts value is InternalWarmupStatus {
  assertObject(value, 'WarmupStatus')
  assertBoolean(value.running, 'WarmupStatus.running')
  assertBoolean(value.ready, 'WarmupStatus.ready')
  assertBoolean(value.failed, 'WarmupStatus.failed')
  assertString(value.error_message, 'WarmupStatus.error_message')
  if (value.elapsed_sec !== null) {
    assertNumber(value.elapsed_sec, 'WarmupStatus.elapsed_sec')
  }
}

export function assertParseResultContract(value: unknown): asserts value is ParseResultContract {
  assertObject(value, 'ParseResult')
  assertArray(value.rows, 'ParseResult.rows')
  value.rows.forEach((row, index) => {
    assertObject(row, `ParseResult.rows[${index}]`)
    assertInteger(row.index, `ParseResult.rows[${index}].index`)
    assertString(row.token, `ParseResult.rows[${index}].token`)
    assertString(row.normalized, `ParseResult.rows[${index}].normalized`)
    assertString(row.lemma, `ParseResult.rows[${index}].lemma`)
    assertString(row.categories, `ParseResult.rows[${index}].categories`)
    assertString(row.source, `ParseResult.rows[${index}].source`)
    assertString(row.matched_form, `ParseResult.rows[${index}].matched_form`)
    assertString(row.confidence, `ParseResult.rows[${index}].confidence`)
    assertString(row.known, `ParseResult.rows[${index}].known`)
  })
  assertObject(value.summary, 'ParseResult.summary')
  assertString(value.status_message, 'ParseResult.status_message')
  assertString(value.error_message, 'ParseResult.error_message')
}

export function assertExtractSentenceResultContract(value: unknown): asserts value is ExtractSentenceResultContract {
  assertObject(value, 'ExtractSentenceResult')
  assertString(value.sentence, 'ExtractSentenceResult.sentence')
}

export function assertLexiconStatisticsContract(value: unknown): asserts value is LexiconStatisticsContract {
  assertObject(value, 'LexiconStatistics')
  assertInteger(value.total_entries, 'LexiconStatistics.total_entries')
  assertNumberRecord(value.counts_by_status, 'LexiconStatistics.counts_by_status')
  assertNumberRecord(value.counts_by_source, 'LexiconStatistics.counts_by_source')
  assertArray(value.categories, 'LexiconStatistics.categories')
  value.categories.forEach((item, index) => {
    assertObject(item, `LexiconStatistics.categories[${index}]`)
    assertString(item.name, `LexiconStatistics.categories[${index}].name`)
    assertInteger(item.count, `LexiconStatistics.categories[${index}].count`)
  })
}

export function assertLexiconSearchResultContract(value: unknown): asserts value is LexiconSearchResultContract {
  assertObject(value, 'LexiconSearchResult')
  assertArray(value.rows, 'LexiconSearchResult.rows')
  value.rows.forEach((row, index) => {
    assertObject(row, `LexiconSearchResult.rows[${index}]`)
    assertInteger(row.id, `LexiconSearchResult.rows[${index}].id`)
    assertString(row.category, `LexiconSearchResult.rows[${index}].category`)
    assertString(row.value, `LexiconSearchResult.rows[${index}].value`)
    assertString(row.normalized, `LexiconSearchResult.rows[${index}].normalized`)
    assertString(row.source, `LexiconSearchResult.rows[${index}].source`)
    assertNumber(row.confidence, `LexiconSearchResult.rows[${index}].confidence`)
    if (row.first_seen_at !== null) {
      assertString(row.first_seen_at, `LexiconSearchResult.rows[${index}].first_seen_at`)
    }
    if (row.request_id !== null) {
      assertString(row.request_id, `LexiconSearchResult.rows[${index}].request_id`)
    }
    assertString(row.status, `LexiconSearchResult.rows[${index}].status`)
    if (row.created_at !== null) {
      assertString(row.created_at, `LexiconSearchResult.rows[${index}].created_at`)
    }
    if (row.reviewed_at !== null) {
      assertString(row.reviewed_at, `LexiconSearchResult.rows[${index}].reviewed_at`)
    }
    if (row.reviewed_by !== null) {
      assertString(row.reviewed_by, `LexiconSearchResult.rows[${index}].reviewed_by`)
    }
    if (row.review_note !== null) {
      assertString(row.review_note, `LexiconSearchResult.rows[${index}].review_note`)
    }
  })
  assertInteger(value.total_rows, 'LexiconSearchResult.total_rows')
  assertInteger(value.filtered_rows, 'LexiconSearchResult.filtered_rows')
  assertNumberRecord(value.counts_by_status, 'LexiconSearchResult.counts_by_status')
  assertStringArray(value.available_categories, 'LexiconSearchResult.available_categories')
  assertString(value.message, 'LexiconSearchResult.message')
}

export function assertRowSyncResultContract(value: unknown): asserts value is RowSyncResultContract {
  assertObject(value, 'RowSyncResult')
  assertString(value.status, 'RowSyncResult.status')
  assertString(value.value, 'RowSyncResult.value')
  assertString(value.category, 'RowSyncResult.category')
  assertString(value.request_id, 'RowSyncResult.request_id')
  assertString(value.message, 'RowSyncResult.message')
  assertBoolean(value.category_fallback_used, 'RowSyncResult.category_fallback_used')
}

export function assertCategoryMutationResultContract(value: unknown): asserts value is CategoryMutationResultContract {
  assertObject(value, 'CategoryMutationResult')
  assertStringArray(value.categories, 'CategoryMutationResult.categories')
  assertString(value.message, 'CategoryMutationResult.message')
}

export function assertLexiconIndexContract(value: unknown): asserts value is LexiconIndexContract {
  assertObject(value, 'LexiconIndex')
  assertStringArrayRecord(value.single_word_index, 'LexiconIndex.single_word_index')
  assertStringArrayRecord(value.multi_word_index, 'LexiconIndex.multi_word_index')
  assertInteger(value.total_rows, 'LexiconIndex.total_rows')
  assertInteger(value.lexicon_version, 'LexiconIndex.lexicon_version')
}

export function assertExportSnapshotContract(value: unknown): asserts value is ExportSnapshotContract {
  assertObject(value, 'ExportSnapshot')
  assertArray(value.tables, 'ExportSnapshot.tables')
  value.tables.forEach((table, index) => {
    assertObject(table, `ExportSnapshot.tables[${index}]`)
    assertString(table.name, `ExportSnapshot.tables[${index}].name`)
    assertStringArray(table.columns, `ExportSnapshot.tables[${index}].columns`)
    assertArray(table.rows, `ExportSnapshot.tables[${index}].rows`)
    table.rows.forEach((row, rowIndex) => assertArray(row, `ExportSnapshot.tables[${index}].rows[${rowIndex}]`))
  })
}

export function assertAssignmentsStatisticsContract(value: unknown): asserts value is AssignmentsStatisticsContract {
  assertObject(value, 'AssignmentsStatistics')
  assertArray(value.units, 'AssignmentsStatistics.units')
  value.units.forEach((item, index) => {
    assertObject(item, `AssignmentsStatistics.units[${index}]`)
    assertString(item.unit_code, `AssignmentsStatistics.units[${index}].unit_code`)
    assertInteger(item.subunit_count, `AssignmentsStatistics.units[${index}].subunit_count`)
    assertString(item.created_at, `AssignmentsStatistics.units[${index}].created_at`)
  })
  assertInteger(value.total_units, 'AssignmentsStatistics.total_units')
  assertInteger(value.total_subunits, 'AssignmentsStatistics.total_subunits')
  if (value.average_subunits_per_unit !== null) {
    assertNumber(value.average_subunits_per_unit, 'AssignmentsStatistics.average_subunits_per_unit')
  }
}

export function assertAssignmentScanResultContract(value: unknown): asserts value is AssignmentScanResultContract {
  assertObject(value, 'AssignmentScanResult')
  if (value.assignment_id !== null) {
    assertInteger(value.assignment_id, 'AssignmentScanResult.assignment_id')
  }
  assertString(value.title, 'AssignmentScanResult.title')
  assertString(value.content_original, 'AssignmentScanResult.content_original')
  assertString(value.content_completed, 'AssignmentScanResult.content_completed')
  assertInteger(value.word_count, 'AssignmentScanResult.word_count')
  assertInteger(value.known_token_count, 'AssignmentScanResult.known_token_count')
  assertInteger(value.unknown_token_count, 'AssignmentScanResult.unknown_token_count')
  assertNumber(value.lexicon_coverage_percent, 'AssignmentScanResult.lexicon_coverage_percent')
  assertString(value.assignment_status, 'AssignmentScanResult.assignment_status')
  assertString(value.message, 'AssignmentScanResult.message')
  assertNumber(value.duration_ms, 'AssignmentScanResult.duration_ms')
  assertArray(value.matches, 'AssignmentScanResult.matches')
  value.matches.forEach((item, index) => {
    assertObject(item, `AssignmentScanResult.matches[${index}]`)
    assertInteger(item.entry_id, `AssignmentScanResult.matches[${index}].entry_id`)
    assertString(item.term, `AssignmentScanResult.matches[${index}].term`)
    assertString(item.category, `AssignmentScanResult.matches[${index}].category`)
    assertString(item.source, `AssignmentScanResult.matches[${index}].source`)
    assertInteger(item.occurrences, `AssignmentScanResult.matches[${index}].occurrences`)
  })
  assertArray(value.missing_words, 'AssignmentScanResult.missing_words')
  value.missing_words.forEach((item, index) => {
    assertObject(item, `AssignmentScanResult.missing_words[${index}]`)
    assertString(item.term, `AssignmentScanResult.missing_words[${index}].term`)
    assertInteger(item.occurrences, `AssignmentScanResult.missing_words[${index}].occurrences`)
    assertString(item.example_usage, `AssignmentScanResult.missing_words[${index}].example_usage`)
  })
  assertArray(value.diff_chunks, 'AssignmentScanResult.diff_chunks')
  value.diff_chunks.forEach((item, index) => {
    assertObject(item, `AssignmentScanResult.diff_chunks[${index}]`)
    assertString(item.operation, `AssignmentScanResult.diff_chunks[${index}].operation`)
    assertString(item.original_text, `AssignmentScanResult.diff_chunks[${index}].original_text`)
    assertString(item.completed_text, `AssignmentScanResult.diff_chunks[${index}].completed_text`)
  })
}

export function assertBulkRescanResultContract(value: unknown): asserts value is BulkRescanResultContract {
  assertObject(value, 'BulkRescanResult')
  assertInteger(value.success_count, 'BulkRescanResult.success_count')
  assertInteger(value.failed_count, 'BulkRescanResult.failed_count')
  assertString(value.message, 'BulkRescanResult.message')
}

export function assertQuickAddSuggestionContract(value: unknown): asserts value is QuickAddSuggestionContract {
  assertObject(value, 'QuickAddSuggestion')
  assertString(value.term, 'QuickAddSuggestion.term')
  assertString(value.recommended_category, 'QuickAddSuggestion.recommended_category')
  assertStringArray(value.candidate_categories, 'QuickAddSuggestion.candidate_categories')
  assertNumber(value.confidence, 'QuickAddSuggestion.confidence')
  assertString(value.rationale, 'QuickAddSuggestion.rationale')
  assertString(value.suggested_example_usage, 'QuickAddSuggestion.suggested_example_usage')
}

export function assertMutationMessageContract(value: unknown): asserts value is MutationMessageContract {
  assertObject(value, 'MutationMessage')
  assertString(value.message, 'MutationMessage.message')
}

export function assertInsertManyResultContract(value: unknown): asserts value is InsertManyResultContract {
  assertObject(value, 'InsertManyResult')
  assertInteger(value.inserted_count, 'InsertManyResult.inserted_count')
  assertString(value.message, 'InsertManyResult.message')
}

export function assertMweExpressionMutationContract(value: unknown): asserts value is MweExpressionMutationContract {
  assertObject(value, 'MweExpressionMutation')
  assertInteger(value.expression_id, 'MweExpressionMutation.expression_id')
}

export function assertMweSenseMutationContract(value: unknown): asserts value is MweSenseMutationContract {
  assertObject(value, 'MweSenseMutation')
  assertInteger(value.sense_id, 'MweSenseMutation.sense_id')
}
