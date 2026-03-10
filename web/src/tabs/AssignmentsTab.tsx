import { useCallback, useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { SortableTable, type Column } from '../components/SortableTable'
import { Modal } from '../components/Modal'
import { KpiCard } from '../components/KpiCard'
import { ContextMenu, type ContextMenuItem } from '../components/ContextMenu'
import { SectionMessage } from '../components/SectionMessage'
import { StatusBadge } from '../components/StatusBadge'
import { useSSEJob } from '../hooks/useSSEJob'
import { apiGet, apiDelete, apiPost } from '../api/client'
import type { Assignment, ScanResult, SSEEvent, QuickAddSuggestion, MissingWord } from '../api/types'
import { toast } from '../components/Toast'
import { formatDurationMs, formatPercent } from '../utils/format'
import '../styles/layout.css'

const HISTORY_COLS: Column[] = [
  { key: 'id', label: 'ID', width: '40px' },
  { key: 'title', label: 'Title', sortable: true },
  { key: 'status', label: 'Status', sortable: true, width: '90px' },
  {
    key: 'lexicon_coverage_percent', label: 'Coverage', sortable: true, width: '80px',
    render: (r) => `${Number(r.lexicon_coverage_percent).toFixed(1)}%`,
  },
  { key: 'created_at', label: 'Created', sortable: true },
]

const MATCH_COLS: Column[] = [
  { key: 'term', label: 'Term', sortable: true },
  { key: 'category', label: 'Category', sortable: true },
  { key: 'source', label: 'Source', sortable: true },
  { key: 'occurrences', label: 'Count', sortable: true, width: '55px' },
]

const MISSING_COLS: Column[] = [
  { key: 'term', label: 'Term', sortable: true },
  { key: 'occurrences', label: 'Count', sortable: true, width: '55px' },
  { key: 'example_usage', label: 'Example' },
]

type AssignmentContextState =
  | { kind: 'history'; x: number; y: number; row: Assignment }
  | { kind: 'missing'; x: number; y: number; row: MissingWord }

export function AssignmentsTab() {
  const queryClient = useQueryClient()

  const [title, setTitle] = useState('')
  const [original, setOriginal] = useState('')
  const [completed, setCompleted] = useState('')
  const [scanResult, setScanResult] = useState<ScanResult | null>(null)

  const [editModal, setEditModal] = useState<Assignment | null>(null)
  const [editForm, setEditForm] = useState({ title: '', content_original: '', content_completed: '' })
  const [deleteConfirm, setDeleteConfirm] = useState<Assignment | null>(null)
  const [quickAddModal, setQuickAddModal] = useState<MissingWord | null>(null)
  const [quickAddCategory, setQuickAddCategory] = useState('')
  const [suggestion, setSuggestion] = useState<QuickAddSuggestion | null>(null)
  const [contextMenu, setContextMenu] = useState<AssignmentContextState | null>(null)

  const extractResult = useCallback((event: SSEEvent): ScanResult | null => {
    const d = event.data as ScanResult | null
    return d ?? null
  }, [])

  const { status, progress, result, error, start } = useSSEJob<ScanResult>(
    '/assignments/scan',
    (jobId) => `/assignments/scan/jobs/${jobId}/stream`,
    extractResult,
  )

  useEffect(() => {
    if (result) {
      setScanResult(result)
      queryClient.invalidateQueries({ queryKey: ['assignments'] })
    }
  }, [result, queryClient])

  const { data: history = [] } = useQuery<Assignment[]>({
    queryKey: ['assignments'],
    queryFn: () => apiGet<Assignment[]>('/assignments'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => apiDelete<{ deleted: boolean; message: string }>(`/assignments/${id}`),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ['assignments'] })
      if (scanResult?.assignment_id === id) setScanResult(null)
      toast('Assignment deleted', 'success')
    },
    onError: (e) => toast(`Delete failed: ${e}`, 'error'),
  })

  const quickAddMutation = useMutation({
    mutationFn: (body: { term: string; content_completed: string; category: string; assignment_id: number | null }) =>
      apiPost('/assignments/quick-add', body),
    onSuccess: () => {
      toast('Word added to lexicon', 'success')
      setQuickAddModal(null)
      // Re-scan after quick add
      if (scanResult) {
        start({ title, content_original: original, content_completed: completed })
      }
    },
    onError: (e) => toast(`Quick add failed: ${e}`, 'error'),
  })

  const openQuickAdd = async (word: MissingWord) => {
    setQuickAddModal(word)
    setQuickAddCategory('')
    setSuggestion(null)
    try {
      const res = await apiPost<QuickAddSuggestion>('/assignments/suggest-category', {
        term: word.term,
        content_completed: completed,
        available_categories: [],
      })
      setSuggestion(res)
      setQuickAddCategory(res.recommended_category)
    } catch {}
  }

  const isWorking = status === 'pending' || status === 'streaming'

  return (
    <div className="tab-panel active" style={{ gap: '8px' }}>
      <div className="two-col" style={{ flex: 'none' }}>
        <div className="panel">
          <div className="panel-title">Assignment</div>
          <div className="form-group">
            <label>Title</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Assignment title..." />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label>Original Text</label>
            <textarea value={original} onChange={(e) => setOriginal(e.target.value)} style={{ minHeight: 80, resize: 'vertical', width: '100%' }} />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label>Completed Text</label>
            <textarea value={completed} onChange={(e) => setCompleted(e.target.value)} style={{ minHeight: 80, resize: 'vertical', width: '100%' }} />
          </div>
          <button
            onClick={() => start({ title, content_original: original, content_completed: completed })}
            disabled={isWorking || !completed.trim()}
          >
            {isWorking ? <><span className="spinner" style={{ marginRight: 6 }} />{progress}</> : 'Scan Assignment'}
          </button>
          {error ? <div className="status-bar error">{error}</div> : <div className="status-bar">{scanResult?.message || 'Load a saved assignment or paste new text to analyze coverage.'}</div>}
        </div>

        <div className="panel">
          <div className="panel-title">Latest Scan Summary</div>
          {scanResult ? (
            <>
              <div className="kpi-row wrap">
                <KpiCard value={scanResult.known_token_count} label="Known" variant="success" />
                <KpiCard value={scanResult.unknown_token_count} label="Missing" variant="danger" />
                <KpiCard value={formatPercent(scanResult.lexicon_coverage_percent)} label="Coverage" variant={scanResult.lexicon_coverage_percent >= 90 ? 'success' : 'warning'} />
                <KpiCard value={scanResult.word_count} label="Words" />
              </div>
              <div className="toolbar">
                <StatusBadge label={scanResult.assignment_status.toLowerCase()} />
                <span className="header-inline-note">{formatDurationMs(scanResult.duration_ms)} runtime</span>
              </div>
              <div className="summary-list">
                <div><span>Matches</span><strong>{scanResult.matches.length}</strong></div>
                <div><span>Missing words</span><strong>{scanResult.missing_words.length}</strong></div>
                <div><span>Assignment title</span><strong>{scanResult.title || 'Untitled Assignment'}</strong></div>
              </div>
              <div style={{ marginTop: 8 }}>
                <div className="panel-title">Audio</div>
                <SectionMessage
                  title="Audio not available"
                  description="The backend currently returns no generated audio for assignments. Coverage analysis and quick-add actions are still available."
                  tone="warning"
                />
              </div>
            </>
          ) : (
            <SectionMessage
              title="No scan selected"
              description="Run a scan to review missing words, coverage, diff chunks, and follow-up actions."
              tone="info"
            />
          )}
        </div>
      </div>

      {scanResult && (
        <div className="two-col">
          <div className="panel">
            <div className="panel-title">Matches ({scanResult.matches.length})</div>
            <SortableTable
              columns={MATCH_COLS}
              rows={scanResult.matches}
              rowKey={(r) => r.entry_id}
              emptyMessage="No matches"
              pageSize={50}
            />
          </div>
          <div className="panel">
            <div className="panel-title">Missing Words ({scanResult.missing_words.length})</div>
            <SortableTable
              columns={MISSING_COLS}
              rows={scanResult.missing_words}
              rowKey={(r) => r.term}
              emptyMessage="No missing words"
              pageSize={50}
              onRowContextMenu={(row, x, y) => setContextMenu({ kind: 'missing', x, y, row: row as MissingWord })}
            />
          </div>
        </div>
      )}

      {scanResult?.diff_chunks?.length ? (
        <div className="panel" style={{ flex: 'none' }}>
          <div className="panel-title">Diff Highlights</div>
          <div className="diff-list">
            {scanResult.diff_chunks.slice(0, 8).map((chunk, index) => (
              <div key={`${chunk.operation}-${index}`} className="diff-card">
                <StatusBadge label={chunk.operation} tone={chunk.operation === 'replace' ? 'warning' : 'info'} />
                <div className="diff-columns">
                  <div>
                    <span>Original</span>
                    <p>{chunk.original_text || '—'}</p>
                  </div>
                  <div>
                    <span>Completed</span>
                    <p>{chunk.completed_text || '—'}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="panel" style={{ flex: 'none', maxHeight: 220 }}>
        <div className="panel-title">Assignment History ({history.length})</div>
        <SortableTable
          columns={HISTORY_COLS}
          rows={history}
          rowKey={(r) => r.id}
          emptyMessage="No assignments saved"
          pageSize={20}
          onRowContextMenu={(row, x, y) => setContextMenu({ kind: 'history', x, y, row: row as Assignment })}
          onRowClick={(row) => {
            setTitle(row.title)
            setOriginal(row.content_original)
            setCompleted(row.content_completed)
          }}
        />
      </div>

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          items={[
            ...(contextMenu.kind === 'missing'
              ? [{ label: `Quick Add "${contextMenu.row.term}"`, onClick: () => openQuickAdd(contextMenu.row) } as ContextMenuItem]
              : [
                  { label: 'Load', onClick: () => { const r = contextMenu.row; setTitle(r.title); setOriginal(r.content_original); setCompleted(r.content_completed) } } as ContextMenuItem,
                  { separator: true } as { separator: true },
                  { label: 'Edit', onClick: () => { const r = contextMenu.row; setEditForm({ title: r.title, content_original: r.content_original, content_completed: r.content_completed }); setEditModal(r) } } as ContextMenuItem,
                  { label: 'Delete', danger: true, onClick: () => setDeleteConfirm(contextMenu.row) } as ContextMenuItem,
                ]
            ),
          ]}
          onClose={() => setContextMenu(null)}
        />
      )}

      <Modal
        open={!!editModal}
        onClose={() => setEditModal(null)}
        title={`Edit Assignment #${editModal?.id}`}
        footer={
          <>
            <button className="btn-ghost" onClick={() => setEditModal(null)}>Cancel</button>
            <button onClick={() => {
              if (!editModal) return
              setTitle(editForm.title)
              setOriginal(editForm.content_original)
              setCompleted(editForm.content_completed)
              start({ title: editForm.title, content_original: editForm.content_original, content_completed: editForm.content_completed })
              setEditModal(null)
            }}>Save & Rescan</button>
          </>
        }
      >
        <div className="form-group">
          <label>Title</label>
          <input value={editForm.title} onChange={(e) => setEditForm((f) => ({ ...f, title: e.target.value }))} />
        </div>
        <div className="form-group">
          <label>Original Text</label>
          <textarea value={editForm.content_original} onChange={(e) => setEditForm((f) => ({ ...f, content_original: e.target.value }))} style={{ width: '100%', minHeight: 80 }} />
        </div>
        <div className="form-group">
          <label>Completed Text</label>
          <textarea value={editForm.content_completed} onChange={(e) => setEditForm((f) => ({ ...f, content_completed: e.target.value }))} style={{ width: '100%', minHeight: 80 }} />
        </div>
      </Modal>

      <Modal
        open={!!deleteConfirm}
        onClose={() => setDeleteConfirm(null)}
        title="Delete assignment?"
        footer={
          <>
            <button className="btn-ghost" onClick={() => setDeleteConfirm(null)}>Cancel</button>
            <button className="btn-danger" onClick={() => { if (deleteConfirm) { deleteMutation.mutate(deleteConfirm.id); setDeleteConfirm(null) } }}>Delete</button>
          </>
        }
      >
        <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
          Delete "{deleteConfirm?.title}"?
        </p>
      </Modal>

      <Modal
        open={!!quickAddModal}
        onClose={() => setQuickAddModal(null)}
        title={`Quick Add "${quickAddModal?.term}"`}
        footer={
          <>
            <button className="btn-ghost" onClick={() => setQuickAddModal(null)}>Cancel</button>
            <button onClick={() => {
              if (!quickAddModal) return
              quickAddMutation.mutate({
                term: quickAddModal.term,
                content_completed: completed,
                category: quickAddCategory,
                assignment_id: scanResult?.assignment_id ?? null,
              })
            }}>Add to Lexicon</button>
          </>
        }
      >
        {suggestion && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
            Suggestion: {suggestion.rationale}
          </div>
        )}
        <div className="form-group">
          <label>Category</label>
          <input
            value={quickAddCategory}
            onChange={(e) => setQuickAddCategory(e.target.value)}
            placeholder="Category..."
            list="quick-add-cats"
          />
          <datalist id="quick-add-cats">
            {(suggestion?.candidate_categories ?? []).map((c) => <option key={c} value={c} />)}
          </datalist>
        </div>
        {suggestion?.suggested_example_usage && (
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            Example: "{suggestion.suggested_example_usage}"
          </div>
        )}
      </Modal>
    </div>
  )
}
