import { useQuery } from '@tanstack/react-query'
import { apiGet } from '../api/client'
import type { StatisticsData } from '../api/types'
import { useWarmup } from './useWarmup'

export function useAppOverview() {
  const warmup = useWarmup()
  const statistics = useQuery<StatisticsData>({
    queryKey: ['statistics'],
    queryFn: () => apiGet<StatisticsData>('/statistics'),
    staleTime: 30_000,
  })

  return {
    warmup,
    statistics: statistics.data,
    isLoading: statistics.isFetching,
    isReady: warmup?.ready ?? false,
    hasError: Boolean(statistics.error),
  }
}
