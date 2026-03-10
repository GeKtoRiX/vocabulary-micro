import { apiDelete, apiGet, apiPatch, apiPost, openSSEStream } from './client'

describe('api client', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  test('serializes query params for GET', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await apiGet('/statistics', { status: 'all', page: 2, empty: '', active: true })

    expect(fetchMock).toHaveBeenCalledWith('/api/statistics?status=all&page=2&active=true')
  })

  test('throws response body on request failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      text: async () => 'broken',
      statusText: 'bad',
    }))

    await expect(apiPost('/parse', { text: 'x' })).rejects.toThrow('broken')
    await expect(apiPatch('/parse', { text: 'x' })).rejects.toThrow('broken')
    await expect(apiDelete('/parse', { text: 'x' })).rejects.toThrow('broken')
  })

  test('opens and closes SSE stream', () => {
    const close = vi.fn()
    let instance: MockEventSource | undefined
    class MockEventSource {
      url: string
      onmessage: ((event: MessageEvent) => void) | null = null
      onerror: ((event: Event) => void) | null = null
      constructor(url: string) {
        this.url = url
        instance = this
      }
      close = close
    }
    vi.stubGlobal('EventSource', MockEventSource as unknown as typeof EventSource)

    const onEvent = vi.fn()
    const onError = vi.fn()
    const cleanup = openSSEStream('/jobs/1/stream', onEvent, onError)
    instance?.onmessage?.({ data: JSON.stringify({ type: 'progress' }) } as MessageEvent)
    cleanup()

    expect(onEvent).toHaveBeenCalledWith({ type: 'progress' })
    expect(close).toHaveBeenCalled()
  })
})
