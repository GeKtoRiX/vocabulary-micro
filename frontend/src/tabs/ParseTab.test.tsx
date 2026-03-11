import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ParseTab } from './ParseTab'
import { renderWithClient } from '../test/render'

vi.mock('../api/client', () => ({
  apiPost: vi.fn().mockResolvedValue({ job_id: 'job-1' }),
  openSSEStream: vi.fn((_path: string, onEvent: (event: Record<string, unknown>) => void) => {
    setTimeout(() => {
      onEvent({ type: 'stage_progress', stage: 'nlp', status: 'done' })
    }, 0)
    setTimeout(() => {
      onEvent({
        type: 'result',
        rows: [
          { index: 1, token: 'hello', normalized: 'hello', lemma: 'hello', categories: 'Greeting', source: 'manual', matched_form: 'hello', confidence: '1.0', known: 'true' },
          { index: 2, token: 'planet', normalized: 'planet', lemma: 'planet', categories: '', source: 'none', matched_form: '', confidence: '0.0', known: 'false' },
        ],
        status_message: 'Done',
      })
    }, 20)
    return vi.fn()
  }),
}))

test('shows parse summary and filtered rows', async () => {
  const user = userEvent.setup()
  renderWithClient(<ParseTab />)

  await user.type(screen.getByPlaceholderText(/paste text here/i), 'hello planet')
  await user.click(screen.getByRole('button', { name: 'Parse' }))

  await waitFor(() => expect(screen.getByText('Coverage')).toBeInTheDocument())
  expect(screen.getByText('Tokens')).toBeInTheDocument()
})

test('shows popup stages during parse and hides them after result', async () => {
  const user = userEvent.setup()
  renderWithClient(<ParseTab />)

  await user.type(screen.getByPlaceholderText(/paste text here/i), 'hello planet')
  await user.click(screen.getByRole('button', { name: 'Parse' }))

  expect(screen.getByText('Processing...')).toBeInTheDocument()

  await waitFor(() => expect(screen.queryByText('Processing...')).not.toBeInTheDocument())
})
