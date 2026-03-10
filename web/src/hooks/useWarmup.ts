import { useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import type { WarmupStatus } from '../api/types'

export function useWarmup() {
  const [status, setStatus] = useState<WarmupStatus | null>(null)

  useEffect(() => {
    let stopped = false

    async function poll() {
      try {
        const data = await apiGet<WarmupStatus>('/system/warmup')
        if (!stopped) {
          setStatus(data)
          // Stop polling once terminal state
          if (!data.ready && !data.failed) {
            setTimeout(poll, 2000)
          }
        }
      } catch {
        if (!stopped) setTimeout(poll, 3000)
      }
    }

    poll()
    return () => { stopped = true }
  }, [])

  return status
}
