'use client'

import { useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'

/**
 * Subscribes to Supabase Realtime INSERT events on `user_evaluations`.
 * Calls `router.refresh()` (debounced to max once per 3 seconds) so the
 * server component re-fetches and new jobs appear in the grid live.
 */
export function useRealtimeEvalUpdates(enabled: boolean) {
  const router = useRouter()
  const lastRefresh = useRef(0)
  const pendingTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!enabled) return

    const supabase = createClient()
    const channel = supabase
      .channel('eval-updates')
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'user_evaluations' },
        () => {
          const now = Date.now()
          const elapsed = now - lastRefresh.current

          if (elapsed >= 3000) {
            lastRefresh.current = now
            router.refresh()
          } else if (!pendingTimer.current) {
            pendingTimer.current = setTimeout(() => {
              lastRefresh.current = Date.now()
              pendingTimer.current = null
              router.refresh()
            }, 3000 - elapsed)
          }
        },
      )
      .subscribe()

    return () => {
      if (pendingTimer.current) clearTimeout(pendingTimer.current)
      supabase.removeChannel(channel)
    }
  }, [enabled, router])
}
