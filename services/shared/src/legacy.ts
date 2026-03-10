import { buildUrl } from './http.js'

export interface LegacyJobBridgeOptions<TBody> {
  baseUrl: string
  startPath: string
  streamPath: (jobId: string) => string
  body: TBody
  headers?: Record<string, string>
  onEvent: (event: Record<string, unknown>) => void | Promise<void>
}

export async function bridgeLegacyJob<TBody>(
  options: LegacyJobBridgeOptions<TBody>,
): Promise<void> {
  const startResponse = await fetch(buildUrl(options.baseUrl, options.startPath), {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(options.headers ?? {}),
    },
    body: JSON.stringify(options.body ?? {}),
  })
  if (!startResponse.ok) {
    throw new Error(await startResponse.text() || startResponse.statusText)
  }
  const startPayload = await startResponse.json() as { job_id?: string }
  const jobId = String(startPayload.job_id || '')
  if (!jobId) {
    throw new Error(`Legacy job start returned no job_id for ${options.startPath}`)
  }

  const streamResponse = await fetch(buildUrl(options.baseUrl, options.streamPath(jobId)), {
    method: 'GET',
    headers: options.headers,
  })
  if (!streamResponse.ok || !streamResponse.body) {
    throw new Error(await streamResponse.text() || streamResponse.statusText)
  }

  for await (const event of parseSseEvents(streamResponse.body)) {
    await options.onEvent(event)
  }
}

export async function awaitLegacyJobResult<TBody, TResult>(
  options: Omit<LegacyJobBridgeOptions<TBody>, 'onEvent'>,
): Promise<TResult> {
  let result: TResult | undefined
  let failure: string | undefined
  await bridgeLegacyJob({
    ...options,
    onEvent(event) {
      if (event.type === 'result') {
        result = ('data' in event ? event.data : event) as TResult
      }
      if (event.type === 'error') {
        failure = String(event.message || 'Legacy job failed')
      }
    },
  })
  if (failure) {
    throw new Error(failure)
  }
  if (result === undefined) {
    throw new Error(`Legacy job ${options.startPath} completed without a result event`)
  }
  return result
}

export async function* parseSseEvents(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<Record<string, unknown>> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const chunk = await reader.read()
      if (chunk.done) {
        break
      }
      buffer += decoder.decode(chunk.value, { stream: true })
      while (true) {
        const frameEnd = buffer.indexOf('\n\n')
        if (frameEnd === -1) {
          break
        }
        const frame = buffer.slice(0, frameEnd)
        buffer = buffer.slice(frameEnd + 2)
        const dataLines = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trim())
        if (!dataLines.length) {
          continue
        }
        const raw = dataLines.join('\n')
        try {
          yield JSON.parse(raw) as Record<string, unknown>
        } catch {
          yield { type: 'error', message: raw }
        }
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined)
  }
}
