'use client'

import { useEffect, useRef } from 'react'
import { createClient } from '@/lib/supabase/client'

/**
 * Subscribes to Supabase Realtime INSERT events on `api_usage_log`.
 * Calls the provided `onNewEntry` callback (debounced to max once per 3 seconds)
 * so the cost dashboard refreshes live as new API calls are logged.
 */
export function useRealtimeCostUpdates(
  enabled: boolean,
  onNewEntry: () => void,
) {
  const lastRefresh = useRef(0)
  const pendingTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const callbackRef = useRef(onNewEntry)
  callbackRef.current = onNewEntry

  useEffect(() => {
    if (!enabled) return

    const supabase = createClient()
    const channel = supabase
      .channel('cost-updates')
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'api_usage_log' },
        () => {
          const now = Date.now()
          const elapsed = now - lastRefresh.current

          if (elapsed >= 3000) {
            lastRefresh.current = now
            callbackRef.current()
          } else if (!pendingTimer.current) {
            pendingTimer.current = setTimeout(() => {
              lastRefresh.current = Date.now()
              pendingTimer.current = null
              callbackRef.current()
            }, 3000 - elapsed)
          }
        },
      )
      .subscribe()

    return () => {
      if (pendingTimer.current) clearTimeout(pendingTimer.current)
      supabase.removeChannel(channel)
    }
  }, [enabled])
}
