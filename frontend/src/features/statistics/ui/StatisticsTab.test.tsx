import { screen, waitFor } from '@testing-library/react'
import { StatisticsTab } from './StatisticsTab'
import { renderWithClient } from '@shared/test/render'

vi.mock('@shared/api/client', () => ({
  apiGet: vi.fn().mockResolvedValue({
    total_entries: 20,
    counts_by_status: { approved: 10, pending_review: 5, rejected: 5 },
    counts_by_source: { manual: 12, parse: 8 },
    categories: [{ name: 'Verb', count: 8 }, { name: 'Noun', count: 6 }],
    units: [
      { unit_code: 'Unit03', subunit_count: 4, created_at: '2026-03-03T10:00:00' },
      { unit_code: 'Unit02', subunit_count: 3, created_at: '2026-03-03T09:00:00' },
    ],
    overview: {
      total_units: 2,
      total_subunits: 7,
      average_subunits_per_unit: 3.5,
      pending_review_count: 5,
      approved_count: 10,
      top_category: { name: 'Verb', count: 8 },
    },
  }),
}))

test('renders unit-focused statistics insights', async () => {
  renderWithClient(<StatisticsTab />)

  await waitFor(() => expect(screen.getByText('Recent Units')).toBeInTheDocument())
  expect(screen.getByText('Top Categories')).toBeInTheDocument()
  expect(screen.getByText('Operational Insights')).toBeInTheDocument()
  expect(screen.getByText('Unit03')).toBeInTheDocument()
})
