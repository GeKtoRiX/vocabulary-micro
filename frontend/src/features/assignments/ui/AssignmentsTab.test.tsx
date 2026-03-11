import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AssignmentsTab } from './AssignmentsTab'
import { renderWithClient } from '@shared/test/render'

const apiGet = vi.fn()
const apiPost = vi.fn()
const apiPut = vi.fn()
const apiDelete = vi.fn()

vi.mock('@shared/api/client', () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
  apiPost: (...args: unknown[]) => apiPost(...args),
  apiPut: (...args: unknown[]) => apiPut(...args),
  apiDelete: (...args: unknown[]) => apiDelete(...args),
}))

beforeEach(() => {
  apiGet.mockResolvedValue([
    {
      id: 1,
      unit_code: 'Unit01',
      unit_number: 1,
      subunit_count: 2,
      subunits: [
        {
          id: 11,
          unit_id: 1,
          subunit_code: '1A',
          position: 0,
          content: 'Alpha block',
          created_at: '2026-03-03T10:00:00',
          updated_at: '2026-03-03T10:00:00',
        },
        {
          id: 12,
          unit_id: 1,
          subunit_code: '1B',
          position: 1,
          content: 'Beta block',
          created_at: '2026-03-03T10:00:00',
          updated_at: '2026-03-03T10:00:00',
        },
      ],
      created_at: '2026-03-03T10:00:00',
      updated_at: '2026-03-03T10:00:00',
    },
  ])
  apiPost.mockResolvedValue({
    id: 2,
    unit_code: 'Unit02',
    unit_number: 2,
    subunit_count: 2,
    subunits: [],
    created_at: '2026-03-03T11:00:00',
    updated_at: '2026-03-03T11:00:00',
  })
  apiPut.mockResolvedValue({
    id: 1,
    unit_code: 'Unit01',
    unit_number: 1,
    subunit_count: 2,
    subunits: [],
    created_at: '2026-03-03T10:00:00',
    updated_at: '2026-03-03T12:00:00',
  })
  apiDelete.mockResolvedValue({ deleted: true, message: 'Unit deleted.' })
})

test('creates a unit from subunits and resets draft to next unit', async () => {
  const user = userEvent.setup()
  renderWithClient(<AssignmentsTab />)

  await waitFor(() => expect(screen.getByText('Unit02')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Add Subunit' }))
  await user.type(screen.getByPlaceholderText(/enter content for 2a/i), 'First subunit')
  await user.click(screen.getByRole('button', { name: 'Add Subunit' }))
  await user.type(screen.getByPlaceholderText(/enter content for 2b/i), 'Second subunit')
  await user.click(screen.getByRole('button', { name: 'Save Unit' }))

  await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/assignments', {
    subunits: [{ content: 'First subunit' }, { content: 'Second subunit' }],
  }))
  await waitFor(() => expect(screen.getByText('Current unit')).toBeInTheDocument())
  expect(screen.getByText('Unit03')).toBeInTheDocument()
})

test('loads saved unit for editing and shows expanded subunits', async () => {
  const user = userEvent.setup()
  renderWithClient(<AssignmentsTab />)

  await waitFor(() => expect(screen.getByRole('button', { name: 'Show' })).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Show' }))
  expect(screen.getByText('Alpha block')).toBeInTheDocument()
  expect(screen.getByText('Beta block')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Edit' }))
  expect(screen.getByDisplayValue('Alpha block')).toBeInTheDocument()
  expect(screen.getByDisplayValue('Beta block')).toBeInTheDocument()

  await user.clear(screen.getByDisplayValue('Alpha block'))
  await user.type(screen.getByPlaceholderText(/enter content for 1a/i), 'Updated alpha')
  await user.click(screen.getByRole('button', { name: 'Save Unit' }))

  await waitFor(() => expect(apiPut).toHaveBeenCalledWith('/assignments/1', {
    subunits: [{ content: 'Updated alpha' }, { content: 'Beta block' }],
  }))
})
