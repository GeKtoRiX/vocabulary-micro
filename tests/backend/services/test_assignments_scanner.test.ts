import { describe, expect, it } from 'vitest'
import { scanAssignment, suggestQuickAddCategory, type LexiconSearchRow } from '../../../backend/services/assignments-service/src/scanner.js'

function lexiconRow(overrides: Partial<LexiconSearchRow> = {}): LexiconSearchRow {
  return {
    id: 1,
    category: 'Verb',
    value: 'run',
    normalized: 'run',
    source: 'manual',
    status: 'approved',
    ...overrides,
  }
}

describe('assignments scanner', () => {
  it('matches known term and computes coverage', () => {
    const result = scanAssignment({
      assignmentId: 1,
      title: 'T',
      contentOriginal: '',
      contentCompleted: 'I run daily',
      lexiconRows: [lexiconRow()],
      completedThresholdPercent: 90,
    })

    expect(result.matches[0].term).toBe('run')
    expect(result.lexicon_coverage_percent).toBeGreaterThan(0)
  })

  it('returns zero coverage for an empty lexicon', () => {
    const result = scanAssignment({
      assignmentId: 1,
      title: 'Empty',
      contentOriginal: '',
      contentCompleted: 'I run daily',
      lexiconRows: [],
      completedThresholdPercent: 90,
    })

    expect(result.lexicon_coverage_percent).toBe(0)
    expect(result.matches).toEqual([])
  })

  it('marks fully covered content as completed', () => {
    const result = scanAssignment({
      assignmentId: 1,
      title: 'Done',
      contentOriginal: '',
      contentCompleted: 'run daily',
      lexiconRows: [
        lexiconRow(),
        lexiconRow({ id: 2, category: 'Adverb', value: 'daily', normalized: 'daily' }),
      ],
      completedThresholdPercent: 90,
    })

    expect(result.lexicon_coverage_percent).toBe(100)
    expect(result.assignment_status).toBe('COMPLETED')
  })

  it('marks uncovered content as pending', () => {
    const result = scanAssignment({
      assignmentId: 1,
      title: 'Pending',
      contentOriginal: '',
      contentCompleted: 'jump high',
      lexiconRows: [lexiconRow()],
      completedThresholdPercent: 90,
    })

    expect(result.lexicon_coverage_percent).toBe(0)
    expect(result.assignment_status).toBe('PENDING')
  })

  it('suggests noun for noun-like suffixes', () => {
    const suggestion = suggestQuickAddCategory('celebration')

    expect(suggestion.recommended_category).toBe('Noun')
    expect(suggestion.candidate_categories).toContain('Noun')
  })

  it('suggests phrasal verb for multi-word terms ending in a particle', () => {
    const suggestion = suggestQuickAddCategory('run out')

    expect(suggestion.recommended_category).toBe('Phrasal Verb')
    expect(suggestion.candidate_categories).toContain('Phrasal Verb')
  })
})
