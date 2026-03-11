import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Modal } from '@shared/ui/Modal'
import { SectionMessage } from '@shared/ui/SectionMessage'
import { StatusBadge } from '@shared/ui/StatusBadge'
import { toast } from '@shared/ui/Toast'
import { apiDelete, apiGet, apiPost, apiPut } from '@shared/api/client'
import type { Assignment } from '@shared/api/types'
import { formatDateTime } from '@shared/utils/format'
import '@shared/styles/layout.css'

interface DraftSubunit {
  key: string
  content: string
}

interface DraftState {
  assignmentId: number | null
  unitNumber: number
  subunits: DraftSubunit[]
}

export function AssignmentsTab() {
  const queryClient = useQueryClient()
  const draftKeyRef = useRef(0)
  const [expandedUnitIds, setExpandedUnitIds] = useState<Set<number>>(new Set())
  const [deleteConfirm, setDeleteConfirm] = useState<Assignment | null>(null)
  const [draft, setDraft] = useState<DraftState>(() => createEmptyDraft(1))

  const { data: history = [] } = useQuery<Assignment[]>({
    queryKey: ['assignments'],
    queryFn: () => apiGet<Assignment[]>('/assignments'),
  })

  useEffect(() => {
    const nextNumber = nextUnitNumber(history)
    setDraft((current) => {
      if (current.assignmentId !== null || current.subunits.length > 0 || current.unitNumber === nextNumber) {
        return current
      }
      return {
        ...current,
        unitNumber: nextNumber,
      }
    })
  }, [history])

  const createDraftSubunit = (content = ''): DraftSubunit => {
    draftKeyRef.current += 1
    return {
      key: `draft-subunit-${draftKeyRef.current}`,
      content,
    }
  }

  const resetDraft = (unitNumber = nextUnitNumber(history)) => {
    setDraft(createEmptyDraft(unitNumber))
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        subunits: normalizeDraftSubunits(draft.subunits).map((content) => ({ content })),
      }
      if (!payload.subunits.length) {
        throw new Error('Add at least one non-empty subunit before saving.')
      }
      if (draft.assignmentId === null) {
        return apiPost<Assignment>('/assignments', payload)
      }
      return apiPut<Assignment>(`/assignments/${draft.assignmentId}`, payload)
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ['assignments'] })
      const nextNumber = Math.max(saved.unit_number, ...history.map((item) => item.unit_number)) + 1
      setExpandedUnitIds((current) => new Set(current).add(saved.id))
      resetDraft(nextNumber)
      toast(draft.assignmentId === null ? `${saved.unit_code} saved` : `${saved.unit_code} updated`, 'success')
    },
    onError: (error) => {
      toast(`Save failed: ${error}`, 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => apiDelete<{ deleted: boolean; message: string }>(`/assignments/${id}`),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ['assignments'] })
      setExpandedUnitIds((current) => {
        const next = new Set(current)
        next.delete(id)
        return next
      })
      if (draft.assignmentId === id) {
        resetDraft(nextUnitNumber(history.filter((item) => item.id !== id)))
      }
      toast('Unit deleted', 'success')
    },
    onError: (error) => {
      toast(`Delete failed: ${error}`, 'error')
    },
  })

  const draftUnitCode = formatUnitCode(draft.unitNumber)
  const canSave = normalizeDraftSubunits(draft.subunits).length > 0 && !saveMutation.isPending

  return (
    <div className="tab-panel active" style={{ gap: '12px' }}>
      <div className="two-col" style={{ alignItems: 'flex-start' }}>
        <div className="panel">
          <div className="toolbar">
            <div className="panel-title" style={{ marginBottom: 0 }}>Unit Editor</div>
            <StatusBadge label={draft.assignmentId === null ? 'new unit' : 'editing'} tone={draft.assignmentId === null ? 'info' : 'warning'} />
          </div>

          <div className="summary-list" style={{ marginBottom: 12 }}>
            <div><span>Current unit</span><strong>{draftUnitCode}</strong></div>
            <div><span>Draft subunits</span><strong>{draft.subunits.length}</strong></div>
          </div>

          <div className="toolbar" style={{ marginBottom: 12 }}>
            <button className="btn-ghost" onClick={() => setDraft((current) => ({
              ...current,
              subunits: [...current.subunits, createDraftSubunit('')],
            }))}>
              Add Subunit
            </button>
            <button className="btn-ghost" onClick={() => resetDraft()} disabled={saveMutation.isPending}>
              {draft.assignmentId === null ? 'Clear Draft' : 'Cancel Edit'}
            </button>
            <button onClick={() => saveMutation.mutate()} disabled={!canSave}>
              {saveMutation.isPending ? <><span className="spinner" style={{ marginRight: 6 }} />Saving...</> : 'Save Unit'}
            </button>
          </div>

          {draft.subunits.length ? (
            <div style={{ display: 'grid', gap: 12 }}>
              {draft.subunits.map((subunit, index) => (
                <div key={subunit.key} className="panel" style={{ margin: 0 }}>
                  <div className="toolbar">
                    <div className="panel-title" style={{ marginBottom: 0 }}>{formatSubunitCode(draft.unitNumber, index)}</div>
                    <button
                      className="btn-danger"
                      onClick={() => setDraft((current) => ({
                        ...current,
                        subunits: current.subunits.filter((_, itemIndex) => itemIndex !== index),
                      }))}
                    >
                      Remove
                    </button>
                  </div>
                  <textarea
                    value={subunit.content}
                    onChange={(event) => setDraft((current) => ({
                      ...current,
                      subunits: current.subunits.map((item, itemIndex) =>
                        itemIndex === index
                          ? { ...item, content: event.target.value }
                          : item,
                      ),
                    }))}
                    placeholder={`Enter content for ${formatSubunitCode(draft.unitNumber, index)}...`}
                    style={{ minHeight: 140, resize: 'vertical', width: '100%' }}
                  />
                </div>
              ))}
            </div>
          ) : (
            <SectionMessage
              title="No subunits yet"
              description="Start with Add Subunit. The editor will create 1A, 1B, 1C and so on automatically."
              tone="info"
            />
          )}
        </div>

        <div className="panel">
          <div className="panel-title">Unit History ({history.length})</div>
          {history.length ? (
            <div style={{ display: 'grid', gap: 10 }}>
              {history.map((unit) => {
                const isExpanded = expandedUnitIds.has(unit.id)
                return (
                  <div key={unit.id} className="panel" style={{ margin: 0 }}>
                    <div className="toolbar">
                      <div>
                        <strong>{unit.unit_code}</strong>
                        <div className="header-inline-note">{unit.subunit_count} subunits • {formatDateTime(unit.updated_at ?? unit.created_at)}</div>
                      </div>
                      <div className="toolbar">
                        <button
                          className="btn-ghost"
                          onClick={() => setExpandedUnitIds((current) => {
                            const next = new Set(current)
                            if (next.has(unit.id)) next.delete(unit.id)
                            else next.add(unit.id)
                            return next
                          })}
                        >
                          {isExpanded ? 'Hide' : 'Show'}
                        </button>
                        <button
                          className="btn-ghost"
                          onClick={() => setDraft({
                            assignmentId: unit.id,
                            unitNumber: unit.unit_number,
                            subunits: unit.subunits
                              .slice()
                              .sort((left, right) => left.position - right.position)
                              .map((subunit) => createDraftSubunit(subunit.content)),
                          })}
                        >
                          Edit
                        </button>
                        <button className="btn-danger" onClick={() => setDeleteConfirm(unit)}>Delete</button>
                      </div>
                    </div>

                    {isExpanded ? (
                      <div style={{ display: 'grid', gap: 10, marginTop: 10 }}>
                        {unit.subunits
                          .slice()
                          .sort((left, right) => left.position - right.position)
                          .map((subunit) => (
                            <div key={subunit.id} className="diff-card">
                              <div className="toolbar" style={{ marginBottom: 6 }}>
                                <StatusBadge label={subunit.subunit_code} tone="info" />
                                <span className="header-inline-note">Position {subunit.position + 1}</span>
                              </div>
                              <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{subunit.content}</p>
                            </div>
                          ))}
                      </div>
                    ) : null}
                  </div>
                )
              })}
            </div>
          ) : (
            <SectionMessage
              title="No saved units"
              description="Save the first unit to start building a reusable history."
              tone="info"
            />
          )}
        </div>
      </div>

      <Modal
        open={!!deleteConfirm}
        onClose={() => setDeleteConfirm(null)}
        title="Delete unit?"
        footer={
          <>
            <button className="btn-ghost" onClick={() => setDeleteConfirm(null)}>Cancel</button>
            <button
              className="btn-danger"
              onClick={() => {
                if (!deleteConfirm) return
                deleteMutation.mutate(deleteConfirm.id)
                setDeleteConfirm(null)
              }}
            >
              Delete
            </button>
          </>
        }
      >
        <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
          Delete {deleteConfirm?.unit_code} and all of its subunits?
        </p>
      </Modal>
    </div>
  )
}

function createEmptyDraft(unitNumber: number): DraftState {
  return {
    assignmentId: null,
    unitNumber: Math.max(1, unitNumber),
    subunits: [],
  }
}

function nextUnitNumber(history: Assignment[]): number {
  if (!history.length) {
    return 1
  }
  return Math.max(...history.map((item) => item.unit_number)) + 1
}

function normalizeDraftSubunits(subunits: DraftSubunit[]): string[] {
  return subunits
    .map((subunit) => subunit.content.trim())
    .filter((content) => content.length > 0)
}

function formatUnitCode(unitNumber: number): string {
  return `Unit${String(Math.max(1, unitNumber)).padStart(2, '0')}`
}

function formatSubunitCode(unitNumber: number, index: number): string {
  return `${Math.max(1, unitNumber)}${toAlphaIndex(index)}`
}

function toAlphaIndex(index: number): string {
  let value = Math.max(0, index)
  let result = ''
  do {
    result = String.fromCharCode(65 + (value % 26)) + result
    value = Math.floor(value / 26) - 1
  } while (value >= 0)
  return result
}
