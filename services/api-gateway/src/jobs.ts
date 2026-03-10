import { randomUUID } from 'node:crypto'

export interface GatewayJobEvent extends Record<string, unknown> {
  type: string
}

interface JobState {
  queue: GatewayJobEvent[]
  waiters: Array<(event: GatewayJobEvent) => void>
}

const jobs = new Map<string, JobState>()

export function createJob(): string {
  const jobId = randomUUID().replace(/-/g, '')
  jobs.set(jobId, { queue: [], waiters: [] })
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
  jobs.delete(jobId)
}
