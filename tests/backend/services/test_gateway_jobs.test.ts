import { afterEach, describe, expect, it, vi } from 'vitest'
import { JOB_TTL_MS, createJob, nextJobEvent } from '../../../backend/services/api-gateway/src/jobs.js'

afterEach(() => {
  vi.useRealTimers()
})

describe('gateway jobs', () => {
  it('expires abandoned jobs and resolves pending waiters', async () => {
    vi.useFakeTimers()

    const jobId = createJob()
    const pendingEvent = nextJobEvent(jobId)

    await vi.advanceTimersByTimeAsync(JOB_TTL_MS)

    await expect(pendingEvent).resolves.toBeNull()
    await expect(nextJobEvent(jobId)).resolves.toBeNull()
  })

  it('does not retain job state after TTL expiry', async () => {
    vi.useFakeTimers()

    const jobId = createJob()

    expect(await Promise.race([nextJobEvent(jobId), Promise.resolve('pending')])).toBe('pending')

    await vi.advanceTimersByTimeAsync(JOB_TTL_MS)

    await expect(nextJobEvent(jobId)).resolves.toBeNull()
  })
})
