import { describe, expect, it, vi } from 'vitest'
import { proxyResponse } from '../../services/shared/src/http.js'

describe('proxyResponse', () => {
  it('cancels the upstream reader when the downstream write fails', async () => {
    const cancel = vi.fn()
    const response = new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('chunk'))
      },
      cancel,
    }))

    const reply = {
      hijack: vi.fn(),
      raw: {
        writeHead: vi.fn(),
        write: vi.fn(() => {
          throw new Error('client disconnected')
        }),
        end: vi.fn(),
      },
    }

    await expect(proxyResponse(reply as never, response)).rejects.toThrow('client disconnected')
    expect(cancel).toHaveBeenCalledTimes(1)
  })
})
