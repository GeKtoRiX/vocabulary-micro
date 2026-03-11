import { useEffect } from 'react'
import '@shared/styles/components.css'

export interface ContextMenuItem {
  label: string
  onClick: () => void
  danger?: boolean
  separator?: never
}
export interface ContextMenuSeparator {
  separator: true
  label?: never
  onClick?: never
}

interface ContextMenuProps {
  x: number
  y: number
  items: (ContextMenuItem | ContextMenuSeparator)[]
  onClose: () => void
}

export function ContextMenu({ x, y, items, onClose }: ContextMenuProps) {
  useEffect(() => {
    const close = () => onClose()
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', close)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', close)
    }
  }, [onClose])

  return (
    <div
      className="context-menu"
      style={{ left: x, top: y }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {items.map((item, i) =>
        'separator' in item && item.separator ? (
          <div key={i} className="context-menu-separator" />
        ) : (
          <button
            key={i}
            className={`context-menu-item${(item as ContextMenuItem).danger ? ' danger' : ''}`}
            onClick={() => { onClose(); (item as ContextMenuItem).onClick() }}
          >
            {(item as ContextMenuItem).label}
          </button>
        ),
      )}
    </div>
  )
}
