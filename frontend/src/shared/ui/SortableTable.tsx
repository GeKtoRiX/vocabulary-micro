import { useState, type ReactNode } from 'react'
import '@shared/styles/table.css'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export interface Column<T = any> {
  key: keyof T | string
  label: string
  sortable?: boolean
  render?: (row: T) => ReactNode
  width?: string
}

interface SortableTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  selectedKeys?: Set<string | number>
  onRowClick?: (row: T) => void
  onRowContextMenu?: (row: T, x: number, y: number) => void
  emptyMessage?: string
  pageSize?: number
  externalPage?: number
  externalTotal?: number
  onPageChange?: (page: number) => void
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function SortableTable<T extends Record<string, any>>({
  columns,
  rows,
  rowKey,
  selectedKeys,
  onRowClick,
  onRowContextMenu,
  emptyMessage = 'No data',
  pageSize,
  externalPage,
  externalTotal,
  onPageChange,
}: SortableTableProps<T>) {
  const [sortCol, setSortCol] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [localPage, setLocalPage] = useState(0)

  const isServerPaginated = externalPage !== undefined

  const handleSort = (col: Column<T>) => {
    if (!col.sortable) return
    const key = col.key as string
    if (sortCol === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortCol(key)
      setSortDir('asc')
    }
  }

  let displayRows = rows
  if (!isServerPaginated && sortCol) {
    displayRows = [...rows].sort((a, b) => {
      const av = a[sortCol] ?? ''
      const bv = b[sortCol] ?? ''
      const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true })
      return sortDir === 'asc' ? cmp : -cmp
    })
  }

  const page = isServerPaginated ? (externalPage ?? 0) : localPage
  const total = isServerPaginated ? (externalTotal ?? rows.length) : rows.length
  const effectivePageSize = pageSize ?? 0
  const pagedRows = effectivePageSize > 0 && !isServerPaginated
    ? displayRows.slice(page * effectivePageSize, (page + 1) * effectivePageSize)
    : displayRows
  const totalPages = effectivePageSize > 0 ? Math.ceil(total / effectivePageSize) : 1

  const changePage = (p: number) => {
    if (isServerPaginated) onPageChange?.(p)
    else setLocalPage(p)
  }

  return (
    <>
      <div className="table-container">
        <table>
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key as string}
                  style={col.width ? { width: col.width } : undefined}
                  className={
                    col.sortable && sortCol === col.key
                      ? sortDir === 'asc' ? 'sort-asc' : 'sort-desc'
                      : ''
                  }
                  onClick={() => handleSort(col)}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pagedRows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '16px' }}>
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              pagedRows.map((row) => {
                const key = rowKey(row)
                return (
                  <tr
                    key={key}
                    className={selectedKeys?.has(key) ? 'selected' : ''}
                    onClick={() => onRowClick?.(row)}
                    onContextMenu={(e) => {
                      if (onRowContextMenu) {
                        e.preventDefault()
                        onRowContextMenu(row, e.clientX, e.clientY)
                      }
                    }}
                  >
                    {columns.map((col) => (
                      <td key={col.key as string} title={String(row[col.key as string] ?? '')}>
                        {col.render ? col.render(row) : String(row[col.key as string] ?? '')}
                      </td>
                    ))}
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
      {effectivePageSize > 0 && totalPages > 1 && (
        <div className="pagination">
          <button onClick={() => changePage(0)} disabled={page === 0}>«</button>
          <button onClick={() => changePage(page - 1)} disabled={page === 0}>‹</button>
          <span>Page {page + 1} / {totalPages} ({total} total)</span>
          <button onClick={() => changePage(page + 1)} disabled={page >= totalPages - 1}>›</button>
          <button onClick={() => changePage(totalPages - 1)} disabled={page >= totalPages - 1}>»</button>
        </div>
      )}
    </>
  )
}
