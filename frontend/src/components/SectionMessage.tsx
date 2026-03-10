import type { ReactNode } from 'react'
import '../styles/components.css'

interface SectionMessageProps {
  title: string
  description: string
  tone?: 'neutral' | 'info' | 'warning' | 'danger'
  action?: ReactNode
}

export function SectionMessage({ title, description, tone = 'neutral', action }: SectionMessageProps) {
  return (
    <div className={`section-message ${tone}`}>
      <div>
        <div className="section-message-title">{title}</div>
        <div className="section-message-description">{description}</div>
      </div>
      {action ? <div className="section-message-action">{action}</div> : null}
    </div>
  )
}
