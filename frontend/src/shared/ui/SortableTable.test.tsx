import userEvent from '@testing-library/user-event'
import { screen } from '@testing-library/react'
import { SortableTable } from './SortableTable'
import { renderWithClient } from '@shared/test/render'

describe('SortableTable', () => {
  test('sorts rows and paginates', async () => {
    const user = userEvent.setup()
    renderWithClient(
      <SortableTable
        columns={[
          { key: 'name', label: 'Name', sortable: true },
          { key: 'score', label: 'Score' },
        ]}
        rows={[
          { id: 1, name: 'Beta', score: 2 },
          { id: 2, name: 'Alpha', score: 1 },
          { id: 3, name: 'Gamma', score: 3 },
        ]}
        rowKey={(row) => row.id}
        pageSize={2}
      />,
    )

    await user.click(screen.getByText('Name'))

    expect(screen.getByText('Alpha')).toBeInTheDocument()
    expect(screen.getByText('Page 1 / 2 (3 total)')).toBeInTheDocument()
  })

  test('shows empty message', () => {
    renderWithClient(
      <SortableTable
        columns={[{ key: 'name', label: 'Name' }]}
        rows={[]}
        rowKey={(row: { id: number }) => row.id}
        emptyMessage="Nothing here"
      />,
    )

    expect(screen.getByText('Nothing here')).toBeInTheDocument()
  })
})
