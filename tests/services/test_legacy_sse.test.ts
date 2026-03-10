import { describe, expect, it, vi } from 'vitest'
import { parseSseEvents } from '../../services/shared/src/legacy.js'

describe('parseSseEvents', () => {
  it('parses multiple data frames', async () => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"progress","message":"x"}\n\n'))
        controller.enqueue(encoder.encode('data: {"type":"done"}\n\n'))
        controller.close()
      },
    })

    const events = []
    for await (const event of parseSseEvents(stream)) {
      events.push(event)
    }

    expect(events).toEqual([
      { type: 'progress', message: 'x' },
      { type: 'done' },
    ])
  })

  it('cancels the reader when iteration stops early', async () => {
    const encoder = new TextEncoder()
    const cancel = vi.fn()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"progress"}\n\n'))
      },
      cancel,
    })

    for await (const event of parseSseEvents(stream)) {
      expect(event).toEqual({ type: 'progress' })
      break
    }

    expect(cancel).toHaveBeenCalledTimes(1)
  })
})
