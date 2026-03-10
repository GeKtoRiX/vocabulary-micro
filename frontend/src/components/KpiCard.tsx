import '../styles/components.css'

interface KpiCardProps {
  value: string | number
  label: string
  variant?: 'success' | 'danger' | 'warning' | 'info' | ''
}

export function KpiCard({ value, label, variant = '' }: KpiCardProps) {
  return (
    <div className={`kpi-card ${variant}`}>
      <div className="kpi-value">{value}</div>
      <div className="kpi-label">{label}</div>
    </div>
  )
}
