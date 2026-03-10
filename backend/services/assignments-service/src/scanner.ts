const TOKEN_PATTERN = /[A-Za-z]+(?:['-][A-Za-z]+)?/g
const SENTENCE_SPLIT_PATTERN = /(?<=[.!?])\s+/g
const DEFAULT_KNOWN_STATUSES = new Set(['approved', 'pending_review'])
const PHRASAL_PARTICLES = new Set([
  'up', 'out', 'off', 'in', 'on', 'down', 'over', 'away', 'back', 'through', 'around', 'along',
  'about', 'after', 'apart', 'aside', 'forward',
])

export interface LexiconSearchRow {
  id: number
  category: string
  value: string
  normalized: string
  source: string
  status: string
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
  matches: Array<{
    entry_id: number
    term: string
    category: string
    source: string
    occurrences: number
  }>
  missing_words: Array<{
    term: string
    occurrences: number
    example_usage: string
  }>
  diff_chunks: Array<{
    operation: string
    original_text: string
    completed_text: string
  }>
}

export function scanAssignment(input: {
  assignmentId?: number | null
  title: string
  contentOriginal: string
  contentCompleted: string
  lexiconRows: LexiconSearchRow[]
  completedThresholdPercent: number
}): ScanResult {
  const started = performance.now()
  const completedTokens = normalizeTokens(tokenize(input.contentCompleted))
  const originalTokens = tokenize(input.contentOriginal)
  const knownRows = input.lexiconRows.filter((row) => DEFAULT_KNOWN_STATUSES.has(String(row.status ?? '').trim().toLowerCase()))

  const matches = matchTerms(knownRows, completedTokens)
  const knownMask = buildKnownMask(knownRows, completedTokens)
  const knownTokenCount = knownMask.filter(Boolean).length
  const wordCount = completedTokens.length
  const unknownTokenCount = Math.max(0, wordCount - knownTokenCount)
  const coverage = wordCount > 0 ? Number(((knownTokenCount / wordCount) * 100).toFixed(2)) : 0
  const assignmentStatus = coverage >= input.completedThresholdPercent ? 'COMPLETED' : 'PENDING'

  return {
    assignment_id: input.assignmentId ?? null,
    title: String(input.title ?? '').trim(),
    content_original: String(input.contentOriginal ?? ''),
    content_completed: String(input.contentCompleted ?? ''),
    word_count: wordCount,
    known_token_count: knownTokenCount,
    unknown_token_count: unknownTokenCount,
    lexicon_coverage_percent: coverage,
    assignment_status: assignmentStatus,
    message: 'Assignment scan completed.',
    duration_ms: Number((performance.now() - started).toFixed(3)),
    matches,
    missing_words: collectMissingWords(input.contentCompleted, completedTokens, knownMask),
    diff_chunks: buildDiffChunks(originalTokens, tokenize(input.contentCompleted)),
  }
}

export function suggestQuickAddCategory(term: string, autoAddCategory = 'Auto Added'): {
  recommended_category: string
  candidate_categories: string[]
  confidence: number
  rationale: string
} {
  const parts = String(term ?? '').trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (parts.length > 1 && PHRASAL_PARTICLES.has(parts[parts.length - 1])) {
    return {
      recommended_category: 'Phrasal Verb',
      candidate_categories: ['Phrasal Verb', 'Verb', autoAddCategory],
      confidence: 0.91,
      rationale: 'Detected a multi-word expression ending with a phrasal particle.',
    }
  }
  if (parts.length > 1 && parts.length >= 3) {
    return {
      recommended_category: 'Idiom',
      candidate_categories: ['Idiom', autoAddCategory],
      confidence: 0.74,
      rationale: 'Detected a multi-word expression likely used as an idiom.',
    }
  }
  const base = parts[0] ?? ''
  if (PHRASAL_PARTICLES.has(base)) {
    return {
      recommended_category: 'Particle',
      candidate_categories: ['Particle', 'Preposition', autoAddCategory],
      confidence: 0.78,
      rationale: 'Detected a particle/preposition candidate token.',
    }
  }
  if (base.endsWith('ly')) {
    return {
      recommended_category: 'Adverb',
      candidate_categories: ['Adverb', autoAddCategory],
      confidence: 0.72,
      rationale: 'Detected an adverb-like suffix (-ly).',
    }
  }
  if (base.endsWith('ing') || base.endsWith('ed')) {
    return {
      recommended_category: 'Verb',
      candidate_categories: ['Verb', autoAddCategory],
      confidence: 0.68,
      rationale: 'Detected a verb-like inflection suffix (-ing/-ed).',
    }
  }
  if (/(tion|ment|ness|ity|ship|ism|age)$/.test(base)) {
    return {
      recommended_category: 'Noun',
      candidate_categories: ['Noun', autoAddCategory],
      confidence: 0.66,
      rationale: 'Detected a noun-like derivational suffix.',
    }
  }
  return {
    recommended_category: autoAddCategory,
    candidate_categories: [autoAddCategory, 'Noun', 'Verb'],
    confidence: 0.5,
    rationale: 'No strong morphological signal detected; using safe default.',
  }
}

export function extractSentence(text: string, term: string): string {
  const cleanText = String(text ?? '').trim()
  const cleanTerm = String(term ?? '').trim().toLowerCase()
  if (!cleanText || !cleanTerm) {
    return ''
  }
  for (const sentence of cleanText.split(SENTENCE_SPLIT_PATTERN)) {
    const cleanSentence = sentence.trim()
    if (cleanSentence && cleanSentence.toLowerCase().includes(cleanTerm)) {
      return cleanSentence
    }
  }
  return ''
}

function tokenize(content: string): string[] {
  return Array.from(String(content ?? '').matchAll(TOKEN_PATTERN), (match) => match[0].toLowerCase())
}

function normalizeTokens(tokens: string[]): string[] {
  return tokens.map((token) => token.trim().toLowerCase()).filter(Boolean)
}

function matchTerms(rows: LexiconSearchRow[], completedTokens: string[]) {
  if (!rows.length || !completedTokens.length) {
    return []
  }
  const termRows = new Map<string, LexiconSearchRow[]>()
  let maxTermLength = 1
  for (const row of rows) {
    const normalized = String(row.normalized ?? '').trim().toLowerCase()
    if (!normalized) {
      continue
    }
    const bucket = termRows.get(normalized) ?? []
    bucket.push(row)
    termRows.set(normalized, bucket)
    maxTermLength = Math.max(maxTermLength, normalized.split(/\s+/).length)
  }
  maxTermLength = Math.max(1, Math.min(maxTermLength, 6))

  const ngramCounters = buildNgramCounters(completedTokens, maxTermLength)
  const matches: ScanResult['matches'] = []
  for (const [term, mappedRows] of termRows.entries()) {
    const size = term.split(/\s+/).length
    const occurrences = ngramCounters.get(size)?.get(term) ?? 0
    if (!occurrences) {
      continue
    }
    for (const row of mappedRows) {
      matches.push({
        entry_id: Number(row.id),
        term,
        category: String(row.category ?? ''),
        source: String(row.source ?? ''),
        occurrences,
      })
    }
  }
  return matches.sort((a, b) => b.occurrences - a.occurrences || a.term.localeCompare(b.term) || a.category.localeCompare(b.category) || a.entry_id - b.entry_id)
}

function buildNgramCounters(tokens: string[], maxLength: number) {
  const counters = new Map<number, Map<string, number>>()
  for (let size = 1; size <= maxLength; size += 1) {
    const counter = new Map<string, number>()
    for (let index = 0; index <= tokens.length - size; index += 1) {
      const key = tokens.slice(index, index + size).join(' ')
      counter.set(key, (counter.get(key) ?? 0) + 1)
    }
    counters.set(size, counter)
  }
  return counters
}

function buildKnownMask(rows: LexiconSearchRow[], completedTokens: string[]): boolean[] {
  const mask = new Array<boolean>(completedTokens.length).fill(false)
  if (!rows.length || !completedTokens.length) {
    return mask
  }
  const terms = new Set<string>()
  let maxLength = 1
  for (const row of rows) {
    const normalized = String(row.normalized ?? '').trim().toLowerCase()
    if (!normalized) {
      continue
    }
    terms.add(normalized)
    maxLength = Math.max(maxLength, normalized.split(/\s+/).length)
  }
  maxLength = Math.max(1, Math.min(maxLength, 6))
  let index = 0
  while (index < completedTokens.length) {
    let matchedLength = 0
    for (let size = Math.min(maxLength, completedTokens.length - index); size >= 1; size -= 1) {
      const candidate = completedTokens.slice(index, index + size).join(' ')
      if (terms.has(candidate)) {
        matchedLength = size
        break
      }
    }
    if (!matchedLength) {
      index += 1
      continue
    }
    for (let offset = 0; offset < matchedLength; offset += 1) {
      mask[index + offset] = true
    }
    index += matchedLength
  }
  return mask
}

function collectMissingWords(text: string, tokens: string[], knownMask: boolean[]) {
  const counts = new Map<string, number>()
  for (let index = 0; index < tokens.length; index += 1) {
    if (knownMask[index]) {
      continue
    }
    const token = tokens[index]
    if (token.length < 2) {
      continue
    }
    counts.set(token, (counts.get(token) ?? 0) + 1)
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([term, occurrences]) => ({
      term,
      occurrences,
      example_usage: extractSentence(text, term),
    }))
}

function buildDiffChunks(originalTokens: string[], completedTokens: string[]) {
  const dp: number[][] = Array.from({ length: originalTokens.length + 1 }, () =>
    Array.from({ length: completedTokens.length + 1 }, () => 0),
  )
  for (let i = originalTokens.length - 1; i >= 0; i -= 1) {
    for (let j = completedTokens.length - 1; j >= 0; j -= 1) {
      dp[i][j] = originalTokens[i] === completedTokens[j]
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const chunks: Array<{ operation: string; original_text: string; completed_text: string }> = []
  let i = 0
  let j = 0
  while (i < originalTokens.length || j < completedTokens.length) {
    if (i < originalTokens.length && j < completedTokens.length && originalTokens[i] === completedTokens[j]) {
      let startI = i
      let startJ = j
      while (i < originalTokens.length && j < completedTokens.length && originalTokens[i] === completedTokens[j]) {
        i += 1
        j += 1
      }
      chunks.push({
        operation: 'equal',
        original_text: originalTokens.slice(startI, i).join(' '),
        completed_text: completedTokens.slice(startJ, j).join(' '),
      })
      continue
    }
    const nextDelete = i < originalTokens.length ? dp[i + 1][j] : -1
    const nextInsert = j < completedTokens.length ? dp[i][j + 1] : -1
    if (j >= completedTokens.length || (i < originalTokens.length && nextDelete >= nextInsert)) {
      const start = i
      i += 1
      while (i < originalTokens.length && (j >= completedTokens.length || dp[i + 1]?.[j] >= dp[i]?.[j + 1])) {
        if (j < completedTokens.length && originalTokens[i] === completedTokens[j]) {
          break
        }
        i += 1
      }
      chunks.push({
        operation: 'delete',
        original_text: originalTokens.slice(start, i).join(' '),
        completed_text: '',
      })
    } else {
      const start = j
      j += 1
      while (
        j < completedTokens.length
        && (
          i >= originalTokens.length
          || dp[i][j + 1] > (dp[i + 1]?.[j] ?? -1)
        )
      ) {
        if (i < originalTokens.length && originalTokens[i] === completedTokens[j]) {
          break
        }
        j += 1
      }
      chunks.push({
        operation: 'insert',
        original_text: '',
        completed_text: completedTokens.slice(start, j).join(' '),
      })
    }
  }
  return mergeReplaceChunks(chunks)
}

function mergeReplaceChunks(chunks: Array<{ operation: string; original_text: string; completed_text: string }>) {
  const merged: typeof chunks = []
  for (const chunk of chunks) {
    const prev = merged[merged.length - 1]
    if (prev && ((prev.operation === 'delete' && chunk.operation === 'insert') || (prev.operation === 'insert' && chunk.operation === 'delete'))) {
      merged[merged.length - 1] = {
        operation: 'replace',
        original_text: [prev.original_text, chunk.original_text].filter(Boolean).join(' ').trim(),
        completed_text: [prev.completed_text, chunk.completed_text].filter(Boolean).join(' ').trim(),
      }
      continue
    }
    merged.push(chunk)
  }
  return merged
}
