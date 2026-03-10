export async function apiGet<T>(url: string, params?: Record<string, string | number | boolean | null | undefined>): Promise<T> {
  const query = params
    ? '?' + Object.entries(params)
        .filter(([, v]) => v !== null && v !== undefined && v !== '')
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&')
    : ''
  const res = await fetch(`/api${url}${query}`)
  if (!res.ok) {
    const body = await res.text()
    throw new Error(body || res.statusText)
  }
  return res.json()
}

export async function apiPost<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${url}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  return res.json()
}

export async function apiPatch<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${url}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  return res.json()
}

export async function apiDelete<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${url}`, {
    method: 'DELETE',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  return res.json()
}

/** Open an SSE job stream. Calls onEvent for each event. Returns cleanup fn. */
export function openSSEStream(
  jobStreamUrl: string,
  onEvent: (event: Record<string, unknown>) => void,
  onError?: (err: Event) => void,
): () => void {
  const es = new EventSource(`/api${jobStreamUrl}`)
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data))
    } catch {}
  }
  if (onError) es.onerror = onError
  return () => es.close()
}
