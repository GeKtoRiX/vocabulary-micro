import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useAppOverview } from './hooks/useAppOverview'
import { ParseTab } from './tabs/ParseTab'
import { LexiconTab } from './tabs/LexiconTab'
import { AssignmentsTab } from './tabs/AssignmentsTab'
import { StatisticsTab } from './tabs/StatisticsTab'
import { ToastContainer } from './components/Toast'
import { StatusBadge } from './components/StatusBadge'
import { KpiCard } from './components/KpiCard'
import { formatPercent } from './utils/format'
import './styles/globals.css'
import './styles/layout.css'
import './styles/table.css'
import './styles/components.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

type TabId = 'parse' | 'lexicon' | 'assignments' | 'statistics'

const TABS: { id: TabId; label: string; description: string }[] = [
  { id: 'parse', label: 'Parse & Sync', description: 'Analyze text, review token matches, and sync new vocabulary.' },
  { id: 'lexicon', label: 'Lexicon', description: 'Curate entries, review statuses, and manage categories.' },
  { id: 'assignments', label: 'Assignments', description: 'Scan assignment text, close gaps, and follow up on missing terms.' },
  { id: 'statistics', label: 'Statistics', description: 'Track vocabulary health, coverage, and operational risks.' },
]

function AppInner() {
  const [activeTab, setActiveTab] = useState<TabId>('parse')
  const { warmup, statistics } = useAppOverview()
  const activeTabMeta = TABS.find((tab) => tab.id === activeTab) ?? TABS[0]

  const warmupLabel = !warmup
    ? 'Connecting'
    : warmup.ready
      ? `AI ready${warmup.elapsed_sec ? ` in ${warmup.elapsed_sec}s` : ''}`
      : warmup.failed
        ? 'AI failed'
        : `AI warming${warmup.elapsed_sec ? ` ${warmup.elapsed_sec}s` : ''}`

  const navMeta: Record<TabId, string> = {
    parse: warmup?.ready ? 'AI online' : warmup?.failed ? 'Check warmup' : 'Preparing AI',
    lexicon: statistics ? `${statistics.total_entries} entries` : 'Loading',
    assignments: statistics ? `${statistics.overview.total_assignments} tracked` : 'Loading',
    statistics: statistics ? formatPercent(statistics.overview.average_assignment_coverage) : 'Loading',
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-main">
          <div className="app-eyebrow">Vocabulary Operations Console</div>
          <h1>Operational vocabulary workspace</h1>
          <p>{activeTabMeta.description}</p>
        </div>
        <div className="app-header-side">
          <StatusBadge
            label={warmupLabel}
            tone={!warmup ? 'info' : warmup.ready ? 'success' : warmup.failed ? 'danger' : 'warning'}
          />
          {warmup?.failed ? <div className="header-inline-note">{warmup.error_message || 'Warmup failed.'}</div> : null}
        </div>
      </header>

      <section className="overview-strip">
        <KpiCard value={statistics?.total_entries ?? '—'} label="Lexicon entries" />
        <KpiCard value={statistics?.overview.pending_review_count ?? '—'} label="Pending review" variant="warning" />
        <KpiCard value={statistics?.overview.total_assignments ?? '—'} label="Assignments" />
        <KpiCard value={statistics ? formatPercent(statistics.overview.average_assignment_coverage) : '—'} label="Avg coverage" variant="info" />
        <KpiCard
          value={statistics?.overview.top_category.name || '—'}
          label={statistics?.overview.top_category.name ? `Top category (${statistics.overview.top_category.count})` : 'Top category'}
        />
      </section>

      <nav className="tab-nav">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`tab-btn${activeTab === tab.id ? ' active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            <span>{tab.label}</span>
            <small>{navMeta[tab.id]}</small>
          </button>
        ))}
      </nav>
      <div className="tab-panels">
        {activeTab === 'parse' && <ParseTab />}
        {activeTab === 'lexicon' && <LexiconTab />}
        {activeTab === 'assignments' && <AssignmentsTab />}
        {activeTab === 'statistics' && <StatisticsTab />}
      </div>
      <ToastContainer />
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppInner />
    </QueryClientProvider>
  )
}
