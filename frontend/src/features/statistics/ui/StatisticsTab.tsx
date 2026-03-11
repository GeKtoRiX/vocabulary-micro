import { useQuery } from '@tanstack/react-query'
import { KpiCard } from '@shared/ui/KpiCard'
import { SectionMessage } from '@shared/ui/SectionMessage'
import { StatusBadge } from '@shared/ui/StatusBadge'
import { apiGet } from '@shared/api/client'
import type { StatisticsData } from '@shared/api/types'
import { formatDateTime } from '@shared/utils/format'
import '@shared/styles/layout.css'

function UnitList({ data }: { data: Array<{ unit_code: string; subunit_count: number; created_at: string }> }) {
  const top = data.slice(0, 8)
  if (!top.length) {
    return <SectionMessage title="No units yet" description="Saved units will appear here after the first draft is stored." />
  }

  return (
    <div className="summary-list">
      {top.map((item) => (
        <div key={`${item.unit_code}-${item.created_at}`}>
          <span>{item.unit_code}<small>{formatDateTime(item.created_at)}</small></span>
          <strong>{item.subunit_count} subunits</strong>
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

  const topCategories = data?.categories.slice(0, 6) ?? []

  return (
    <div className="tab-panel active" style={{ gap: '12px', overflowY: 'auto' }}>
      <div className="toolbar">
        <button onClick={() => refetch()} className="btn-ghost" disabled={isFetching}>
          {isFetching ? <><span className="spinner" style={{ marginRight: 6 }} />Loading...</> : 'Refresh'}
        </button>
        {data ? <span className="header-inline-note">{data.overview.total_units} units tracked</span> : null}
      </div>

      {data ? (
        <>
          <div className="kpi-row wrap">
            <KpiCard value={data.total_entries} label="Total Entries" />
            <KpiCard value={data.overview.total_units} label="Units" />
            <KpiCard value={data.overview.total_subunits} label="Subunits" variant="info" />
            <KpiCard value={data.overview.average_subunits_per_unit} label="Avg Subunits/Unit" variant="info" />
            <KpiCard value={data.overview.pending_review_count} label="Pending Review" variant="warning" />
          </div>

          <div className="two-col" style={{ flex: 'none' }}>
            <div className="panel">
              <div className="panel-title">Recent Units</div>
              <UnitList data={data.units} />
            </div>

            <div className="panel">
              <div className="panel-title">Operational Insights</div>
              <div className="summary-list">
                <div><span>Top category</span><strong>{data.overview.top_category.name || '—'}</strong></div>
                <div><span>Approved entries</span><strong>{data.overview.approved_count}</strong></div>
                <div><span>Source types</span><strong>{Object.keys(data.counts_by_source).length}</strong></div>
                <div><span>Avg subunits / unit</span><strong>{data.overview.average_subunits_per_unit}</strong></div>
              </div>
              <div className="toolbar" style={{ marginTop: 12 }}>
                <StatusBadge label={`${data.overview.pending_review_count} pending`} tone="warning" />
                <StatusBadge label={`${data.overview.total_subunits} subunits`} tone="info" />
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

          <div className="panel" style={{ flex: 'none' }}>
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
        </>
      ) : (
        <SectionMessage title="Statistics unavailable" description="Refresh to load lexicon and unit metrics." tone="info" />
      )}
    </div>
  )
}
