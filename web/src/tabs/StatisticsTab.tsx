import { useQuery } from '@tanstack/react-query'
import { KpiCard } from '../components/KpiCard'
import { SectionMessage } from '../components/SectionMessage'
import { StatusBadge } from '../components/StatusBadge'
import { apiGet } from '../api/client'
import type { StatisticsData } from '../api/types'
import { formatDateTime, formatPercent } from '../utils/format'
import '../styles/layout.css'

function CoverageBars({ data }: { data: Array<{ title: string; coverage_pct: number }> }) {
  const top = data.slice(0, 8)
  if (!top.length) {
    return <SectionMessage title="No assignment coverage yet" description="Coverage bars will appear after assignment scans are saved." />
  }

  return (
    <div className="coverage-bars">
      {top.map((item) => (
        <div key={item.title} className="coverage-bar-row">
          <div className="coverage-bar-meta">
            <strong>{item.title}</strong>
            <span>{formatPercent(item.coverage_pct)}</span>
          </div>
          <div className="coverage-bar-track">
            <div className="coverage-bar-fill" style={{ width: `${Math.min(100, Math.max(0, item.coverage_pct))}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function StatisticsTab() {
  const { data, isFetching, refetch } = useQuery<StatisticsData>({
    queryKey: ['statistics'],
    queryFn: () => apiGet<StatisticsData>('/statistics'),
    staleTime: 30_000,
  })

  const lowCoverageAssignments = data?.assignment_coverage.filter((item) => item.coverage_pct < 60) ?? []
  const topCategories = data?.categories.slice(0, 6) ?? []

  return (
    <div className="tab-panel active" style={{ gap: '12px', overflowY: 'auto' }}>
      <div className="toolbar">
        <button onClick={() => refetch()} className="btn-ghost" disabled={isFetching}>
          {isFetching ? <><span className="spinner" style={{ marginRight: 6 }} />Loading...</> : 'Refresh'}
        </button>
        {data ? <span className="header-inline-note">{data.overview.total_assignments} assignments monitored</span> : null}
      </div>

      {data ? (
        <>
          <div className="kpi-row wrap">
            <KpiCard value={data.total_entries} label="Total Entries" />
            <KpiCard value={data.overview.total_assignments} label="Assignments" />
            <KpiCard value={formatPercent(data.overview.average_assignment_coverage)} label="Avg Coverage" variant="info" />
            <KpiCard value={data.overview.pending_review_count} label="Pending Review" variant="warning" />
            <KpiCard value={data.overview.low_coverage_count} label="Low Coverage" variant="danger" />
          </div>

          <div className="two-col" style={{ flex: 'none' }}>
            <div className="panel">
              <div className="panel-title">Coverage Overview</div>
              <CoverageBars data={data.assignment_coverage} />
            </div>

            <div className="panel">
              <div className="panel-title">Operational Insights</div>
              <div className="summary-list">
                <div><span>Top category</span><strong>{data.overview.top_category.name || '—'}</strong></div>
                <div><span>Approved entries</span><strong>{data.overview.approved_count}</strong></div>
                <div><span>Source types</span><strong>{Object.keys(data.counts_by_source).length}</strong></div>
              </div>
              <div className="toolbar" style={{ marginTop: 12 }}>
                <StatusBadge label={`${data.overview.pending_review_count} pending`} tone="warning" />
                <StatusBadge label={`${data.overview.low_coverage_count} low coverage`} tone="danger" />
              </div>
            </div>
          </div>

          <div className="two-col" style={{ flex: 'none' }}>
            <div className="panel">
              <div className="panel-title">Status Breakdown</div>
              <div className="summary-list">
                {Object.entries(data.counts_by_status).map(([status, count]) => (
                  <div key={status}><span>{status}</span><strong>{count}</strong></div>
                ))}
              </div>
            </div>

            <div className="panel">
              <div className="panel-title">Source Breakdown</div>
              <div className="summary-list">
                {Object.entries(data.counts_by_source).map(([source, count]) => (
                  <div key={source}><span>{source}</span><strong>{count}</strong></div>
                ))}
              </div>
            </div>
          </div>

          <div className="two-col" style={{ flex: 'none' }}>
            <div className="panel">
              <div className="panel-title">Top Categories</div>
              {topCategories.length ? (
                <div className="summary-list">
                  {topCategories.map((category) => (
                    <div key={category.name}><span>{category.name}</span><strong>{category.count}</strong></div>
                  ))}
                </div>
              ) : (
                <SectionMessage title="No category data" description="Category usage will appear as the lexicon grows." />
              )}
            </div>

            <div className="panel">
              <div className="panel-title">Low Coverage Assignments</div>
              {lowCoverageAssignments.length ? (
                <div className="summary-list">
                  {lowCoverageAssignments.map((assignment) => (
                    <div key={`${assignment.title}-${assignment.created_at}`}>
                      <span>{assignment.title}<small>{formatDateTime(assignment.created_at)}</small></span>
                      <strong>{formatPercent(assignment.coverage_pct)}</strong>
                    </div>
                  ))}
                </div>
              ) : (
                <SectionMessage title="No immediate risks" description="Assignments below 60% coverage will surface here for follow-up." tone="info" />
              )}
            </div>
          </div>
        </>
      ) : (
        <SectionMessage title="Statistics unavailable" description="Refresh to load lexicon and assignment health metrics." tone="info" />
      )}
    </div>
  )
}
