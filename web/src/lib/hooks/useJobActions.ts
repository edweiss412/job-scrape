'use client'

import useSWR from 'swr'
import { useCallback, useMemo } from 'react'
import { JobAction } from '@/lib/types'

interface ActionRow {
  job_id: string
  action: JobAction
}

const fetcher = (url: string) => fetch(url).then((r) => r.json())

export function useJobActions() {
  const { data, mutate, isLoading } = useSWR<ActionRow[]>('/api/job-actions', fetcher)

  const actions = useMemo(() => {
    const map = new Map<string, JobAction>()
    if (Array.isArray(data)) {
      for (const row of data) {
        map.set(row.job_id, row.action)
      }
    }
    return map
  }, [data])

  const toggle = useCallback(
    async (jobId: string, action: JobAction) => {
      const current = actions.get(jobId)
      const willDelete = current === action

      // Optimistic update
      const optimistic = willDelete
        ? (data ?? []).filter((r) => r.job_id !== jobId)
        : [
            ...(data ?? []).filter((r) => r.job_id !== jobId),
            { job_id: jobId, action },
          ]

      mutate(optimistic, false)

      try {
        await fetch('/api/job-actions', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ job_id: jobId, action }),
        })
        mutate()
      } catch {
        mutate() // revert on error
      }
    },
    [actions, data, mutate],
  )

  return { actions, toggle, isLoading }
}
