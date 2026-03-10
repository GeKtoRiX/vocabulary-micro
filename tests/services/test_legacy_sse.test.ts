import { describe, expect, it } from 'vitest'
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
})
