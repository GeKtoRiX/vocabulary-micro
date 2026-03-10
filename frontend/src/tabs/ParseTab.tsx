import { useCallback, useState } from 'react'
import { SortableTable, type Column } from '../components/SortableTable'
import { ContextMenu, type ContextMenuItem } from '../components/ContextMenu'
import { KpiCard } from '../components/KpiCard'
import { SectionMessage } from '../components/SectionMessage'
import { StatusBadge } from '../components/StatusBadge'
import { useSSEJob } from '../hooks/useSSEJob'
import { apiPost } from '../api/client'
import type { ParseResultSummary, ParseRow, ParseResult, SSEEvent, RowSyncResult } from '../api/types'
import { toast } from '../components/Toast'
import { formatPercent } from '../utils/format'
import '../styles/layout.css'

const COLUMNS: Column[] = [
  { key: 'index', label: '#', sortable: true, width: '40px' },
  { key: 'token', label: 'Token', sortable: true },
  { key: 'normalized', label: 'Normalized', sortable: true },
  { key: 'lemma', label: 'Lemma', sortable: true },
  { key: 'categories', label: 'Categories', sortable: true },
  { key: 'source', label: 'Source', sortable: true },
  { key: 'matched_form', label: 'Matched Form', sortable: true },
  { key: 'confidence', label: 'Confidence', sortable: true, width: '80px' },
  {
    key: 'known',
    label: 'Known',
    sortable: true,
    width: '60px',
    render: (row) => (
      <span style={{ color: row.known === 'True' || row.known === 'true' ? 'var(--accent-success)' : 'var(--text-muted)' }}>
        {row.known}
      </span>
    ),
  },
]

export function ParseTab() {
  const [text, setText] = useState('')
  const [sync, setSync] = useState(false)
  const [thirdPass, setThirdPass] = useState(false)
  const [thinkMode, setThinkMode] = useState(false)
  const [filterText, setFilterText] = useState('')
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; row: ParseRow } | null>(null)
  const [selectedKeys] = useState<Set<number>>(new Set())

  const extractResult = useCallback((event: SSEEvent): ParseResult | null => {
    if (!event.rows) return null
    return {
      rows: event.rows,
      summary: event.summary || {},
      status_message: event.status_message || '',
      error_message: event.error_message || '',
    }
  }, [])

  const { status, progress, result, error, start } = useSSEJob<ParseResult>(
    '/parse',
    (jobId) => `/parse/jobs/${jobId}/stream`,
    extractResult,
  )

  const handleParse = () => {
    if (!text.trim()) return
    start({ text, sync, third_pass_enabled: thirdPass, think_mode: thinkMode })
  }

  const handleSyncRow = async (row: ParseRow) => {
    try {
      const res = await apiPost<RowSyncResult>('/parse/sync-row', {
        token: row.token,
        normalized: row.normalized,
        lemma: row.lemma,
        categories: row.categories,
      })
      toast(`Sync: ${res.message}`, res.status === 'added' || res.status === 'already_exists' ? 'success' : 'warning')
    } catch (err) {
      toast(`Sync failed: ${err}`, 'error')
    }
  }

  const filteredRows = (result?.rows ?? []).filter((r) => {
    if (!filterText) return true
    const q = filterText.toLowerCase()
    return r.token.toLowerCase().includes(q) || r.normalized.toLowerCase().includes(q) || r.categories.toLowerCase().includes(q)
  })

  const isWorking = status === 'pending' || status === 'streaming'
  const statusText = isWorking ? progress : error ? `Error: ${error}` : result?.status_message || ''
  const parseSummary: ParseResultSummary | null = result
    ? {
        totalTokens: result.rows.length,
        knownTokens: result.rows.filter((row) => String(row.known).toLowerCase() === 'true').length,
        unknownTokens: result.rows.filter((row) => String(row.known).toLowerCase() !== 'true').length,
        coveragePercent: result.rows.length
          ? (result.rows.filter((row) => String(row.known).toLowerCase() === 'true').length / result.rows.length) * 100
          : 0,
      }
    : null

  return (
    <div className="tab-panel active parse-tab">
      <div className="two-col parse-grid">
        <section className="panel panel-accent">
          <div className="panel-header">
            <div>
              <div className="panel-title">Primary Workspace</div>
              <div className="panel-heading">Text Input</div>
            </div>
            <StatusBadge label={isWorking ? 'running' : result ? 'ready' : 'idle'} />
          </div>
          <p className="panel-copy">
            Paste source text, choose validation depth, and run parse without leaving the review surface.
          </p>
          <div className="control-strip">
            <button onClick={handleParse} disabled={isWorking || !text.trim()}>
              {isWorking ? <><span className="spinner" style={{ marginRight: 6 }} />Parsing...</> : sync ? 'Parse & Sync' : 'Parse'}
            </button>
            <div className="toggle-cluster" role="group" aria-label="Parse options">
              <label className="inline-toggle">
                <input type="checkbox" checked={sync} onChange={(e) => setSync(e.target.checked)} />
                <span>Sync</span>
              </label>
              <label className="inline-toggle">
                <input type="checkbox" checked={thirdPass} onChange={(e) => setThirdPass(e.target.checked)} />
                <span>LLM Pass</span>
              </label>
              <label className="inline-toggle">
                <input type="checkbox" checked={thinkMode} onChange={(e) => setThinkMode(e.target.checked)} disabled={!thirdPass} />
                <span>Think Mode</span>
              </label>
            </div>
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste text here to review token recognition, unknown vocabulary, and sync candidates."
            className="workspace-textarea"
          />
          <div className="status-strip">
            <span className={`status-bar ${error ? 'error' : ''}`}>{statusText || 'Run parse to inspect tokens and sync candidates.'}</span>
            <span className="header-inline-note">{text.trim() ? `${text.trim().split(/\s+/).length} words queued` : 'No text queued'}</span>
          </div>
        </section>

        <section className="panel panel-secondary">
          <div className="panel-header">
            <div>
              <div className="panel-title">Analytical Snapshot</div>
              <div className="panel-heading">Latest Run Summary</div>
            </div>
          </div>
          {parseSummary ? (
            <>
              <div className="kpi-row wrap kpi-row-compact">
                <KpiCard value={parseSummary.totalTokens} label="Tokens" />
                <KpiCard value={parseSummary.knownTokens} label="Known" variant="success" />
                <KpiCard value={parseSummary.unknownTokens} label="Unknown" variant="warning" />
                <KpiCard value={formatPercent(parseSummary.coveragePercent)} label="Coverage" variant="info" />
              </div>
              <div className="summary-list">
                <div><span>Run mode</span><strong>{sync ? 'Parse + sync' : 'Parse only'}</strong></div>
                <div><span>LLM validation</span><strong>{thirdPass ? (thinkMode ? 'Enabled + think mode' : 'Enabled') : 'Disabled'}</strong></div>
                <div><span>Visible rows</span><strong>{filteredRows.length}</strong></div>
              </div>
            </>
          ) : (
            <SectionMessage
              title="No parse results yet"
              description="Enter text and run parsing to see token coverage, known vocabulary, and sync-ready items."
              tone="info"
            />
          )}
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <div className="panel-title">Data Review</div>
            <div className="panel-heading">Token Insights</div>
          </div>
          {result ? <span className="header-inline-note">{filteredRows.length} rows shown</span> : null}
        </div>
        <div className="toolbar toolbar-spread">
          <input
            placeholder="Filter rows by token, normalized form, or category..."
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            className="filter-input"
            disabled={!result}
          />
          <span className="header-inline-note">
            {result ? 'Right-click a row to sync a token.' : 'Results appear here after a parse run.'}
          </span>
        </div>
        {error ? (
          <SectionMessage
            title="Parse failed"
            description={error}
            tone="danger"
          />
        ) : result ? (
          <SortableTable
            columns={COLUMNS}
            rows={filteredRows}
            rowKey={(r) => r.index}
            selectedKeys={selectedKeys as Set<string | number>}
            onRowContextMenu={(row, x, y) => setContextMenu({ x, y, row: row as ParseRow })}
            emptyMessage="No tokens match the current filter"
          />
        ) : (
          <SectionMessage
            title="Ready to parse"
            description="This area will show token-by-token recognition details, match sources, and manual sync actions."
          />
        )}
      </section>

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          items={[
            {
              label: `Sync "${contextMenu.row.token}"`,
              onClick: () => handleSyncRow(contextMenu.row),
            } as ContextMenuItem,
          ]}
          onClose={() => setContextMenu(null)}
        />
      )}
    </div>
  )
}
