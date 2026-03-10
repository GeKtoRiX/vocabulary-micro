import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LexiconTab } from './LexiconTab'
import { renderWithClient } from '../test/render'

vi.mock('../api/client', () => ({
  apiGet: vi.fn().mockResolvedValue({
    rows: [
      { id: 1, category: 'Verb', value: 'go', normalized: 'go', source: 'manual', confidence: 1, first_seen_at: null, request_id: null, status: 'approved', created_at: null, reviewed_at: null, reviewed_by: null, review_note: null },
    ],
    total_rows: 10,
    filtered_rows: 1,
    counts_by_status: { approved: 8, pending_review: 2, rejected: 0 },
    available_categories: ['Verb', 'Noun'],
    message: 'Loaded',
  }),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  apiPost: vi.fn(),
}))

test('renders lexicon operational summary and reset filters', async () => {
  const user = userEvent.setup()
  renderWithClient(<LexiconTab />)

  await waitFor(() => expect(screen.getByText('Lexicon Entries')).toBeInTheDocument())
  expect(screen.getByText('Approved ratio')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /reset filters/i }))
})
