export interface WarmupStatus {
  running: boolean
  ready: boolean
  failed: boolean
  error_message: string
  elapsed_sec: number | null
}

export interface ParseRow {
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

export interface ParseResult {
  rows: ParseRow[]
  summary: Record<string, unknown>
  status_message: string
  error_message: string
}

export interface ParseResultSummary {
  totalTokens: number
  knownTokens: number
  unknownTokens: number
  coveragePercent: number
}

export interface LexiconEntry {
  id: number
  category: string
  value: string
  normalized: string
  source: string
  confidence: number | null
  first_seen_at: string | null
  request_id: string | null
  status: string
  created_at: string | null
  reviewed_at: string | null
  reviewed_by: string | null
  review_note: string | null
}

export interface LexiconSearchResponse {
  rows: LexiconEntry[]
  total_rows: number
  filtered_rows: number
  counts_by_status: Record<string, number>
  available_categories: string[]
  message: string
}

export interface AssignmentMatch {
  entry_id: number
  term: string
  category: string
  source: string
  occurrences: number
}

export interface MissingWord {
  term: string
  occurrences: number
  example_usage: string
}

export interface DiffChunk {
  operation: string
  original_text: string
  completed_text: string
}

export interface ScanResult {
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
  matches: AssignmentMatch[]
  missing_words: MissingWord[]
  diff_chunks: DiffChunk[]
}

export interface Assignment {
  id: number
  title: string
  content_original: string
  content_completed: string
  status: string
  lexicon_coverage_percent: number
  created_at: string | null
  updated_at: string | null
}

export interface QuickAddSuggestion {
  term: string
  recommended_category: string
  candidate_categories: string[]
  confidence: number
  rationale: string
  suggested_example_usage: string
}

export interface RowSyncResult {
  status: string
  value: string
  category: string
  request_id: string
  message: string
  category_fallback_used: boolean
}

export interface StatisticsData {
  total_entries: number
  counts_by_status: Record<string, number>
  counts_by_source: Record<string, number>
  categories: Array<{ name: string; count: number }>
  assignment_coverage: Array<{ title: string; coverage_pct: number; created_at: string }>
  overview: {
    total_assignments: number
    average_assignment_coverage: number
    pending_review_count: number
    approved_count: number
    low_coverage_count: number
    top_category: {
      name: string
      count: number
    }
  }
}

export interface SSEEvent {
  type: 'progress' | 'result' | 'error' | 'done'
  message?: string
  data?: unknown
  rows?: ParseRow[]
  summary?: Record<string, unknown>
  status_message?: string
  error_message?: string
  success_count?: number
  failed_count?: number
}
