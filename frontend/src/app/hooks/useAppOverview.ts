import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@shared/api/client'
import type { StatisticsData } from '@shared/api/types'
import { useWarmup } from '@shared/hooks/useWarmup'

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
