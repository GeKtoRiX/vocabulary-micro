import { useEffect, useRef, useState } from 'react'
import '../styles/components.css'

export type ToastType = 'info' | 'success' | 'error' | 'warning'

interface ToastItem {
  id: number
  message: string
  type: ToastType
}

let _addToast: ((msg: string, type: ToastType) => void) | null = null

export function toast(message: string, type: ToastType = 'info') {
  _addToast?.(message, type)
}

export function ToastContainer() {
  const [items, setItems] = useState<ToastItem[]>([])
  const counterRef = useRef(0)

  useEffect(() => {
    _addToast = (message, type) => {
      const id = ++counterRef.current
      setItems((prev) => [...prev, { id, message, type }])
      setTimeout(() => {
        setItems((prev) => prev.filter((t) => t.id !== id))
      }, 4000)
    }
    return () => { _addToast = null }
  }, [])

  if (!items.length) return null

  return (
    <div className="toast-container">
      {items.map((item) => (
        <div key={item.id} className={`toast ${item.type}`}>
          {item.message}
        </div>
      ))}
    </div>
  )
}
