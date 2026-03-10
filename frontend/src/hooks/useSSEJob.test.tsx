import { act, renderHook } from '@testing-library/react'
import { useSSEJob } from './useSSEJob'
import * as client from '../api/client'

describe('useSSEJob', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  test('handles progress and result lifecycle', async () => {
    let pushEvent: ((event: Record<string, unknown>) => void) | undefined
    vi.spyOn(client, 'apiPost').mockResolvedValue({ job_id: 'job-1' })
    vi.spyOn(client, 'openSSEStream').mockImplementation((_path: string, onEvent: (event: Record<string, unknown>) => void) => {
      pushEvent = onEvent
      return vi.fn()
    })

    const { result } = renderHook(() => useSSEJob('/parse', (id) => `/jobs/${id}`, (event) => event.data as { done: boolean }))

    await act(async () => {
      await result.current.start({ text: 'hello' })
    })

    act(() => {
      pushEvent?.({ type: 'progress', message: 'Working' })
      pushEvent?.({ type: 'result', data: { done: true } })
    })

    expect(result.current.status).toBe('done')
    expect(result.current.result).toEqual({ done: true })
    expect(result.current.error).toBeNull()
  })

  test('closes EventSource on result to prevent reconnect', async () => {
    let pushEvent: ((event: Record<string, unknown>) => void) | undefined
    const cleanup = vi.fn()
    vi.spyOn(client, 'apiPost').mockResolvedValue({ job_id: 'job-2' })
    vi.spyOn(client, 'openSSEStream').mockImplementation((_path, onEvent) => {
      pushEvent = onEvent
      return cleanup
    })

    const { result } = renderHook(() => useSSEJob('/parse', (id) => `/jobs/${id}`, (event) => event.data as { done: boolean }))
    await act(async () => { await result.current.start({ text: 'hello' }) })

    act(() => { pushEvent?.({ type: 'result', data: { done: true } }) })

    expect(cleanup).toHaveBeenCalledTimes(1)
    expect(result.current.status).toBe('done')
  })

  test('closes EventSource on error to prevent "Job not found" overwrite', async () => {
    let pushEvent: ((event: Record<string, unknown>) => void) | undefined
    const cleanup = vi.fn()
    vi.spyOn(client, 'apiPost').mockResolvedValue({ job_id: 'job-3' })
    vi.spyOn(client, 'openSSEStream').mockImplementation((_path, onEvent) => {
      pushEvent = onEvent
      return cleanup
    })

    const { result } = renderHook(() => useSSEJob('/parse', (id) => `/jobs/${id}`, () => null))
    await act(async () => { await result.current.start({ text: 'hello' }) })

    act(() => { pushEvent?.({ type: 'error', message: 'Parse failed' }) })

    expect(cleanup).toHaveBeenCalledTimes(1)
    expect(result.current.status).toBe('error')
    expect(result.current.error).toBe('Parse failed')
  })

  test('stores API start failure', async () => {
    vi.spyOn(client, 'apiPost').mockRejectedValue(new Error('start failed'))

    const { result } = renderHook(() => useSSEJob('/parse', (id) => `/jobs/${id}`, () => null))

    await act(async () => {
      await result.current.start({ text: 'hello' })
    })

    expect(result.current.status).toBe('error')
    expect(result.current.error).toContain('start failed')
  })
})
