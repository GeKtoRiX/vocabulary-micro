import { screen, waitFor } from '@testing-library/react'
import { StatisticsTab } from './StatisticsTab'
import { renderWithClient } from '../test/render'

vi.mock('../api/client', () => ({
  apiGet: vi.fn().mockResolvedValue({
    total_entries: 20,
    counts_by_status: { approved: 10, pending_review: 5, rejected: 5 },
    counts_by_source: { manual: 12, parse: 8 },
    categories: [{ name: 'Verb', count: 8 }, { name: 'Noun', count: 6 }],
    assignment_coverage: [
      { title: 'Essay 1', coverage_pct: 55, created_at: '2026-03-03T10:00:00' },
      { title: 'Essay 2', coverage_pct: 92, created_at: '2026-03-03T11:00:00' },
    ],
    overview: {
      total_assignments: 2,
      average_assignment_coverage: 73.5,
      pending_review_count: 5,
      approved_count: 10,
      low_coverage_count: 1,
      top_category: { name: 'Verb', count: 8 },
    },
  }),
}))

test('renders derived statistics insights', async () => {
  renderWithClient(<StatisticsTab />)

  await waitFor(() => expect(screen.getByText('Coverage Overview')).toBeInTheDocument())
  expect(screen.getByText('Low Coverage Assignments')).toBeInTheDocument()
  expect(screen.getByText('Top Categories')).toBeInTheDocument()
})
