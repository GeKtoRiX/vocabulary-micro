import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { SortableTable, type Column } from '@shared/ui/SortableTable'
import { Modal } from '@shared/ui/Modal'
import { ContextMenu, type ContextMenuItem } from '@shared/ui/ContextMenu'
import { KpiCard } from '@shared/ui/KpiCard'
import { SectionMessage } from '@shared/ui/SectionMessage'
import { StatusBadge } from '@shared/ui/StatusBadge'
import { apiGet, apiPatch, apiDelete, apiPost } from '@shared/api/client'
import type { LexiconEntry, LexiconSearchResponse } from '@shared/api/types'
import { toast } from '@shared/ui/Toast'
import { formatPercent, ratio } from '@shared/utils/format'
import '@shared/styles/layout.css'

const PAGE_SIZE = 100

const STATUSES = ['all', 'pending_review', 'approved', 'rejected']
const SOURCES = ['all', 'parse', 'manual']

const COLUMNS: Column[] = [
  { key: 'id', label: 'ID', sortable: true, width: '50px' },
  { key: 'category', label: 'Category', sortable: true },
  { key: 'value', label: 'Value', sortable: true },
  { key: 'normalized', label: 'Normalized', sortable: true },
  { key: 'source', label: 'Source', sortable: true, width: '70px' },
  { key: 'confidence', label: 'Conf.', sortable: true, width: '55px' },
  {
    key: 'status', label: 'Status', sortable: true, width: '90px',
    render: (row) => {
      const cls = row.status === 'approved' ? 'badge-approved' : row.status === 'rejected' ? 'badge-rejected' : 'badge-pending'
      return <span className={`badge ${cls}`}>{row.status}</span>
    },
  },
  { key: 'created_at', label: 'Created', sortable: true },
  { key: 'review_note', label: 'Note' },
]

interface SearchParams {
  status: string
  value_filter: string
  category_filter: string
  source_filter: string
  page: number
}

export function LexiconTab() {
  const queryClient = useQueryClient()

  const [params, setParams] = useState<SearchParams>({
    status: 'all', value_filter: '', category_filter: '', source_filter: 'all', page: 0,
  })
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; row: LexiconEntry } | null>(null)
  const [editModal, setEditModal] = useState<LexiconEntry | null>(null)
  const [editForm, setEditForm] = useState({ status: '', category: '', value: '' })
  const [addModal, setAddModal] = useState(false)
  const [addForm, setAddForm] = useState({ value: '', category: '', source: 'manual' })
  const [catModal, setCatModal] = useState(false)
  const [newCatName, setNewCatName] = useState('')
  const [deleteConfirm, setDeleteConfirm] = useState(false)

  const queryKey = ['lexicon', params]

  const { data, isFetching } = useQuery<LexiconSearchResponse>({
    queryKey,
    queryFn: () => apiGet<LexiconSearchResponse>('/lexicon/entries', {
      status: params.status,
      value_filter: params.value_filter,
      category_filter: params.category_filter,
      source_filter: params.source_filter,
      limit: PAGE_SIZE,
      offset: params.page * PAGE_SIZE,
    }),
  })

  const currentQuery = {
    status: params.status,
    value_filter: params.value_filter,
    category_filter: params.category_filter,
    source_filter: params.source_filter,
    limit: PAGE_SIZE,
    offset: params.page * PAGE_SIZE,
  }

  const updateMutation = useMutation({
    mutationFn: (vars: { entry_id: number; status: string; category: string; value: string }) =>
      apiPatch(`/lexicon/entries/${vars.entry_id}`, { ...vars, query: currentQuery }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['lexicon'] }); toast('Entry updated', 'success') },
    onError: (e) => toast(`Update failed: ${e}`, 'error'),
  })

  const deleteMutation = useMutation({
    mutationFn: (ids: number[]) =>
      apiDelete('/lexicon/entries', { entry_ids: ids, query: currentQuery }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lexicon'] })
      setSelectedIds(new Set())
      toast('Entries deleted', 'success')
    },
    onError: (e) => toast(`Delete failed: ${e}`, 'error'),
  })

  const addEntryMutation = useMutation({
    mutationFn: (body: { value: string; category: string; source: string }) =>
      apiPost('/lexicon/entries', body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['lexicon'] }); toast('Entry added', 'success') },
    onError: (e) => toast(`Add failed: ${e}`, 'error'),
  })

  const addCatMutation = useMutation({
    mutationFn: (name: string) => apiPost('/lexicon/categories', { name }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['lexicon'] }); toast('Category created', 'success') },
    onError: (e) => toast(`Failed: ${e}`, 'error'),
  })

  const deleteCatMutation = useMutation({
    mutationFn: (name: string) => apiDelete(`/lexicon/categories/${encodeURIComponent(name)}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['lexicon'] }); toast('Category deleted', 'success') },
    onError: (e) => toast(`Failed: ${e}`, 'error'),
  })

  const openEdit = (row: LexiconEntry) => {
    setEditForm({ status: row.status, category: row.category, value: row.value })
    setEditModal(row)
  }

  const handleDelete = (ids: number[]) => {
    deleteMutation.mutate(ids)
    setDeleteConfirm(false)
  }
  const activeFilterCount = [
    params.value_filter,
    params.category_filter,
    params.status !== 'all' ? params.status : '',
    params.source_filter !== 'all' ? params.source_filter : '',
  ].filter(Boolean).length
  const approvedCount = data?.counts_by_status.approved ?? 0
  const pendingCount = data?.counts_by_status.pending_review ?? 0
  const approvedRatio = data ? ratio(approvedCount, data.total_rows) : 0

  return (
    <div className="tab-panel active" style={{ gap: '8px' }}>
      <div className="three-col">
        <KpiCard value={data?.total_rows ?? '—'} label="Total rows" />
        <KpiCard value={data?.filtered_rows ?? '—'} label="Filtered rows" variant="info" />
        <KpiCard value={pendingCount || '—'} label="Pending review" variant="warning" />
        <KpiCard value={formatPercent(approvedRatio)} label="Approved ratio" variant="success" />
        <KpiCard value={data?.available_categories.length ?? '—'} label="Categories" />
      </div>

      <details className="collapsible" open>
        <summary>Search & Filter</summary>
        <div className="collapsible-content toolbar" style={{ flexWrap: 'wrap', gap: 8 }}>
          <input
            placeholder="Value filter..."
            value={params.value_filter}
            onChange={(e) => setParams((p) => ({ ...p, value_filter: e.target.value, page: 0 }))}
            style={{ width: 160 }}
          />
          <select value={params.category_filter} onChange={(e) => setParams((p) => ({ ...p, category_filter: e.target.value, page: 0 }))}>
            <option value="">All categories</option>
            {(data?.available_categories ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={params.status} onChange={(e) => setParams((p) => ({ ...p, status: e.target.value, page: 0 }))}>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={params.source_filter} onChange={(e) => setParams((p) => ({ ...p, source_filter: e.target.value, page: 0 }))}>
            {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <button
            className="btn-ghost"
            onClick={() => setParams({ status: 'all', value_filter: '', category_filter: '', source_filter: 'all', page: 0 })}
            disabled={activeFilterCount === 0}
          >
            Reset filters
          </button>
          <span className="header-inline-note">{activeFilterCount} active filters</span>
        </div>
      </details>

      <div className="two-col" style={{ flex: 'none' }}>
        <section className="panel">
          <div className="panel-title">Entry Actions</div>
          <div className="toolbar">
            <button onClick={() => setAddModal(true)}>+ Add Entry</button>
            <button onClick={() => setCatModal(true)} className="btn-ghost">Manage Categories</button>
            <a href="/api/lexicon/export" download>
              <button className="btn-ghost">Export Excel</button>
            </a>
          </div>
          <div className="summary-list">
            <div><span>Selection</span><strong>{selectedIds.size} rows</strong></div>
            <div><span>Query</span><strong>{data?.message || 'Ready'}</strong></div>
            <div><span>Categories</span><strong>{data?.available_categories.length ?? 0}</strong></div>
          </div>
          {selectedIds.size > 0 ? (
            <div className="toolbar">
              <button className="btn-danger" onClick={() => setDeleteConfirm(true)}>
                Delete {selectedIds.size} selected
              </button>
            </div>
          ) : null}
        </section>

        <section className="panel">
          <div className="panel-title">Review Health</div>
          {data ? (
            <>
              <div className="toolbar">
                <StatusBadge label={`${approvedCount} approved`} tone="success" />
                <StatusBadge label={`${pendingCount} pending`} tone="warning" />
                <StatusBadge label={`${data.counts_by_status.rejected ?? 0} rejected`} tone="danger" />
              </div>
              <p className="header-inline-note">
                Page {params.page + 1} of {Math.max(1, Math.ceil((data.filtered_rows || 0) / PAGE_SIZE))}. {isFetching ? 'Refreshing data...' : 'Use filters to narrow operational review queues.'}
              </p>
            </>
          ) : (
            <SectionMessage
              title="Loading lexicon"
              description="This panel will summarize review workload and current result scope."
              tone="info"
            />
          )}
        </section>
      </div>

      <section className="panel">
        <div className="panel-title">Lexicon Entries</div>
        {data ? (
          <SortableTable
            columns={COLUMNS}
            rows={data.rows}
            rowKey={(r) => r.id}
            selectedKeys={selectedIds as Set<string | number>}
            onRowClick={(row) => {
              setSelectedIds((prev) => {
                const next = new Set(prev)
                if (next.has(row.id)) next.delete(row.id)
                else next.add(row.id)
                return next
              })
            }}
            onRowContextMenu={(row, x, y) => { setSelectedIds(new Set([row.id])); setContextMenu({ x, y, row: row as LexiconEntry }) }}
            emptyMessage="No entries found"
            pageSize={PAGE_SIZE}
            externalPage={params.page}
            externalTotal={data.filtered_rows}
            onPageChange={(p) => setParams((prev) => ({ ...prev, page: p }))}
          />
        ) : (
          <SectionMessage
            title="No lexicon data yet"
            description="When the query loads, this table will show entries, review status, source, and edit actions."
          />
        )}
      </section>

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          items={[
            { label: 'Edit', onClick: () => openEdit(contextMenu.row) } as ContextMenuItem,
            { separator: true },
            { label: 'Delete', danger: true, onClick: () => handleDelete([contextMenu.row.id]) } as ContextMenuItem,
          ]}
          onClose={() => setContextMenu(null)}
        />
      )}

      {/* Edit modal */}
      <Modal
        open={!!editModal}
        onClose={() => setEditModal(null)}
        title={`Edit Entry #${editModal?.id}`}
        footer={
          <>
            <button className="btn-ghost" onClick={() => setEditModal(null)}>Cancel</button>
            <button onClick={() => {
              if (!editModal) return
              updateMutation.mutate({ entry_id: editModal.id, ...editForm })
              setEditModal(null)
            }}>Save</button>
          </>
        }
      >
        <div className="form-group">
          <label>Status</label>
          <select value={editForm.status} onChange={(e) => setEditForm((f) => ({ ...f, status: e.target.value }))}>
            <option value="pending_review">pending_review</option>
            <option value="approved">approved</option>
            <option value="rejected">rejected</option>
          </select>
        </div>
        <div className="form-group">
          <label>Category</label>
          <select value={editForm.category} onChange={(e) => setEditForm((f) => ({ ...f, category: e.target.value }))}>
            {(data?.available_categories ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="form-group">
          <label>Value</label>
          <input value={editForm.value} onChange={(e) => setEditForm((f) => ({ ...f, value: e.target.value }))} />
        </div>
      </Modal>

      {/* Add entry modal */}
      <Modal
        open={addModal}
        onClose={() => setAddModal(false)}
        title="Add Entry"
        footer={
          <>
            <button className="btn-ghost" onClick={() => setAddModal(false)}>Cancel</button>
            <button onClick={() => { addEntryMutation.mutate(addForm); setAddModal(false) }}>Add</button>
          </>
        }
      >
        <div className="form-group">
          <label>Value</label>
          <input value={addForm.value} onChange={(e) => setAddForm((f) => ({ ...f, value: e.target.value }))} />
        </div>
        <div className="form-group">
          <label>Category</label>
          <select value={addForm.category} onChange={(e) => setAddForm((f) => ({ ...f, category: e.target.value }))}>
            <option value="">— select —</option>
            {(data?.available_categories ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="form-group">
          <label>Source</label>
          <input value={addForm.source} onChange={(e) => setAddForm((f) => ({ ...f, source: e.target.value }))} />
        </div>
      </Modal>

      {/* Manage categories modal */}
      <Modal open={catModal} onClose={() => setCatModal(false)} title="Manage Categories">
        <div className="flex gap-2 mt-2">
          <input placeholder="New category name..." value={newCatName} onChange={(e) => setNewCatName(e.target.value)} />
          <button onClick={() => { addCatMutation.mutate(newCatName); setNewCatName('') }}>Create</button>
        </div>
        <div style={{ marginTop: 12, maxHeight: 200, overflowY: 'auto' }}>
          {(data?.available_categories ?? []).map((c) => (
            <div key={c} className="flex items-center justify-between" style={{ padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
              <span style={{ fontSize: 12 }}>{c}</span>
              <button className="btn-danger" style={{ padding: '2px 8px', fontSize: 11 }} onClick={() => deleteCatMutation.mutate(c)}>×</button>
            </div>
          ))}
        </div>
      </Modal>

      {/* Delete confirm modal */}
      <Modal
        open={deleteConfirm}
        onClose={() => setDeleteConfirm(false)}
        title={`Delete ${selectedIds.size} entries?`}
        footer={
          <>
            <button className="btn-ghost" onClick={() => setDeleteConfirm(false)}>Cancel</button>
            <button className="btn-danger" onClick={() => handleDelete([...selectedIds])}>Delete</button>
          </>
        }
      >
        <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
          This will permanently delete {selectedIds.size} selected entries.
        </p>
      </Modal>
    </div>
  )
}
