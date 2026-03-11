import { screen } from '@testing-library/react'
import { SectionMessage } from './SectionMessage'
import { renderWithClient } from '@shared/test/render'

test('renders section message content', () => {
  renderWithClient(<SectionMessage title="Missing data" description="Load data to continue." tone="warning" />)

  expect(screen.getByText('Missing data')).toBeInTheDocument()
  expect(screen.getByText('Load data to continue.')).toBeInTheDocument()
})
