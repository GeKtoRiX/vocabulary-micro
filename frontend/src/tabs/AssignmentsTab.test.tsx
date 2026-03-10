import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AssignmentsTab } from './AssignmentsTab'
import { renderWithClient } from '../test/render'

vi.mock('../api/client', () => ({
  apiGet: vi.fn().mockResolvedValue([
    {
      id: 1,
      title: 'Essay 1',
      content_original: 'a',
      content_completed: 'b',
      status: 'PENDING',
      lexicon_coverage_percent: 55,
      created_at: '2026-03-03T10:00:00',
      updated_at: '2026-03-03T10:00:00',
    },
  ]),
  apiDelete: vi.fn(),
  apiPost: vi.fn().mockImplementation((url: string) => {
    if (url === '/assignments/scan') return Promise.resolve({ job_id: 'scan-1' })
    if (url === '/assignments/suggest-category') return Promise.resolve({ recommended_category: 'Verb', candidate_categories: ['Verb'], confidence: 0.9, rationale: 'common verb', suggested_example_usage: 'run fast' })
    return Promise.resolve({})
  }),
  openSSEStream: vi.fn((_path: string, onEvent: (event: Record<string, unknown>) => void) => {
    setTimeout(() => {
      onEvent({
        type: 'result',
        data: {
          assignment_id: 1,
          title: 'Essay 1',
          content_original: 'a',
          content_completed: 'b',
          word_count: 10,
          known_token_count: 7,
          unknown_token_count: 3,
          lexicon_coverage_percent: 70,
          assignment_status: 'PENDING',
          message: 'Scanned',
          duration_ms: 250,
          matches: [],
          missing_words: [{ term: 'planet', occurrences: 1, example_usage: 'planet earth' }],
          diff_chunks: [{ operation: 'replace', original_text: 'a', completed_text: 'b' }],
        },
      })
    }, 0)
    return vi.fn()
  }),
}))

test('renders latest scan summary and empty audio state', async () => {
  const user = userEvent.setup()
  renderWithClient(<AssignmentsTab />)

  await user.type(screen.getByPlaceholderText(/assignment title/i), 'Essay 1')
  await user.type(screen.getAllByRole('textbox')[2], 'Completed content')
  await user.click(screen.getByRole('button', { name: 'Scan Assignment' }))

  await waitFor(() => expect(screen.getByText('Audio not available')).toBeInTheDocument())
  expect(screen.getByText('Diff Highlights')).toBeInTheDocument()
})
