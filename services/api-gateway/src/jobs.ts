import { randomUUID } from 'node:crypto'

export interface GatewayJobEvent extends Record<string, unknown> {
  type: string
}

interface JobState {
  queue: GatewayJobEvent[]
  waiters: Array<(event: GatewayJobEvent | null) => void>
}

export const JOB_TTL_MS = 60_000

const jobs = new Map<string, JobState>()
const jobTimers = new Map<string, ReturnType<typeof setTimeout>>()

export function createJob(): string {
  const jobId = randomUUID().replace(/-/g, '')
  jobs.set(jobId, { queue: [], waiters: [] })
  jobTimers.set(jobId, setTimeout(() => cleanupJob(jobId), JOB_TTL_MS))
  return jobId
}

export function pushJobEvent(jobId: string, event: GatewayJobEvent): void {
  const state = jobs.get(jobId)
  if (!state) {
    return
  }
  const waiter = state.waiters.shift()
  if (waiter) {
    waiter(event)
    return
  }
  state.queue.push(event)
}

export async function nextJobEvent(jobId: string): Promise<GatewayJobEvent | null> {
  const state = jobs.get(jobId)
  if (!state) {
    return null
  }
  if (state.queue.length > 0) {
    return state.queue.shift() ?? null
  }
  return new Promise((resolve) => {
    state.waiters.push(resolve)
  })
}

export function cleanupJob(jobId: string): void {
  const timer = jobTimers.get(jobId)
  if (timer) {
    clearTimeout(timer)
    jobTimers.delete(jobId)
  }
  const state = jobs.get(jobId)
  if (state) {
    while (state.waiters.length > 0) {
      const waiter = state.waiters.shift()
      waiter?.(null)
    }
  }
  jobs.delete(jobId)
}
