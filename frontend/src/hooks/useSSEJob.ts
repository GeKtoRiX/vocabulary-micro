import { useCallback, useRef, useState } from 'react'
import { apiPost, openSSEStream } from '../api/client'
import type { SSEEvent } from '../api/types'

export type SSEJobStatus = 'idle' | 'pending' | 'streaming' | 'done' | 'error'

export interface SSEJobState<T> {
  status: SSEJobStatus
  progress: string
  result: T | null
  error: string | null
}

/**
 * Hook for the job+SSE pattern.
 * @param postUrl  URL to POST to start the job (e.g. '/parse')
 * @param streamPath  Function that takes jobId and returns stream path (e.g. id => `/parse/jobs/${id}/stream`)
 * @param extractResult  Function that takes the SSE result event and returns typed result
 */
export function useSSEJob<T>(
  postUrl: string,
  streamPath: (jobId: string) => string,
  extractResult: (event: SSEEvent) => T | null,
  onStageEvent?: (event: SSEEvent) => void,
) {
  const [state, setState] = useState<SSEJobState<T>>({
    status: 'idle',
    progress: '',
    result: null,
    error: null,
  })
  const cleanupRef = useRef<(() => void) | null>(null)

  const start = useCallback(
    async (body: unknown) => {
      // Cancel any existing stream
      if (cleanupRef.current) {
        cleanupRef.current()
        cleanupRef.current = null
      }

      setState({ status: 'pending', progress: 'Starting...', result: null, error: null })

      let jobId: string
      try {
        const res = await apiPost<{ job_id: string }>(postUrl, body)
        jobId = res.job_id
      } catch (err) {
        setState({ status: 'error', progress: '', result: null, error: String(err) })
        return
      }

      setState((s) => ({ ...s, status: 'streaming', progress: 'Working...' }))

      const cleanup = openSSEStream(
        streamPath(jobId),
        (rawEvent) => {
          const event = rawEvent as unknown as SSEEvent
          if (event.type === 'progress') {
            setState((s) => ({ ...s, progress: event.message || 'Working...' }))
          } else if (event.type === 'stage_progress') {
            onStageEvent?.(event)
          } else if (event.type === 'result') {
            const result = extractResult(event)
            setState({ status: 'done', progress: '', result, error: null })
          } else if (event.type === 'error') {
            setState({ status: 'error', progress: '', result: null, error: event.message || 'Unknown error' })
          } else if (event.type === 'done') {
            setState((s) => (s.status === 'streaming' ? { ...s, status: 'done' } : s))
          }
          // Закрываем EventSource при получении терминального события,
          // чтобы предотвратить автоматическое переподключение браузера
          // после закрытия SSE-соединения сервером.
          if (event.type === 'done' || event.type === 'error' || event.type === 'result') {
            cleanupRef.current?.()
            cleanupRef.current = null
          }
        },
      )
      cleanupRef.current = cleanup
    },
    [postUrl, streamPath, extractResult, onStageEvent],
  )

  const reset = useCallback(() => {
    if (cleanupRef.current) {
      cleanupRef.current()
      cleanupRef.current = null
    }
    setState({ status: 'idle', progress: '', result: null, error: null })
  }, [])

  return { ...state, start, reset }
}
