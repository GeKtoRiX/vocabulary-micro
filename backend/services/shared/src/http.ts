import type { FastifyReply, FastifyRequest } from 'fastify'

export function buildUrl(
  baseUrl: string,
  path: string,
  query?: Record<string, unknown>,
): string {
  const url = new URL(path, baseUrl)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === '') {
        continue
      }
      if (Array.isArray(value)) {
        for (const item of value) {
          url.searchParams.append(key, String(item))
        }
        continue
      }
      url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

export function extractForwardHeaders(
  request: FastifyRequest,
  requestId: string,
): Record<string, string> {
  const headers: Record<string, string> = {
    'x-request-id': requestId,
  }
  const contentType = request.headers['content-type']
  if (typeof contentType === 'string' && contentType.trim()) {
    headers['content-type'] = contentType
  }
  const accept = request.headers.accept
  if (typeof accept === 'string' && accept.trim()) {
    headers.accept = accept
  }
  return headers
}

export async function requestJson<T>(
  baseUrl: string,
  path: string,
  init: RequestInit & {
    query?: Record<string, unknown>
  } = {},
): Promise<T> {
  const response = await fetch(buildUrl(baseUrl, path, init.query), init)
  if (!response.ok) {
    throw await toHttpError(response)
  }
  return response.json() as Promise<T>
}

export async function requestBuffer(
  baseUrl: string,
  path: string,
  init: RequestInit & {
    query?: Record<string, unknown>
  } = {},
): Promise<Response> {
  const response = await fetch(buildUrl(baseUrl, path, init.query), init)
  if (!response.ok) {
    throw await toHttpError(response)
  }
  return response
}

export async function proxyJson(
  reply: FastifyReply,
  baseUrl: string,
  path: string,
  init: RequestInit & {
    query?: Record<string, unknown>
  } = {},
): Promise<void> {
  try {
    const response = await fetch(buildUrl(baseUrl, path, init.query), init)
    if (!response.ok) {
      const text = await response.text()
      reply.code(response.status).send(text ? safeJson(text) : { detail: response.statusText })
      return
    }
    const payload = await response.json()
    reply.code(response.status).send(payload)
  } catch (error) {
    reply.code(502).send({ detail: error instanceof Error ? error.message : String(error) })
  }
}

export async function proxyResponse(reply: FastifyReply, response: Response): Promise<void> {
  reply.hijack()
  const headers: Record<string, string> = {}
  const contentType = response.headers.get('content-type')
  if (contentType) {
    headers['content-type'] = contentType
  }
  const disposition = response.headers.get('content-disposition')
  if (disposition) {
    headers['content-disposition'] = disposition
  }
  reply.raw.writeHead(response.status, headers)
  const body = response.body
  if (!body) {
    reply.raw.end()
    return
  }
  const reader = body.getReader()
  try {
    while (true) {
      const chunk = await reader.read()
      if (chunk.done) {
        break
      }
      reply.raw.write(Buffer.from(chunk.value))
    }
  } finally {
    await reader.cancel().catch(() => undefined)
  }
  reply.raw.end()
}

async function toHttpError(response: Response): Promise<Error> {
  const text = await response.text()
  return new Error(text || response.statusText || `HTTP ${response.status}`)
}

function safeJson(raw: string): unknown {
  try {
    return JSON.parse(raw)
  } catch {
    return { detail: raw }
  }
}
