import { getStatusTone } from '@shared/utils/format'
import '@shared/styles/components.css'

interface StatusBadgeProps {
  label: string
  tone?: 'success' | 'danger' | 'warning' | 'info'
}

export function StatusBadge({ label, tone }: StatusBadgeProps) {
  const resolvedTone = tone ?? getStatusTone(label)
  return <span className={`status-badge ${resolvedTone}`}>{label}</span>
}
