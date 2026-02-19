'use client'

import { ReactNode } from 'react'
import { useRealtimeEvalUpdates } from '@/lib/hooks/useRealtimeEvalUpdates'

interface Props {
  scanIsActive: boolean
  evalIsActive: boolean
  children: ReactNode
}

/**
 * Thin client wrapper that activates Supabase Realtime subscriptions
 * when a scan or evaluation is in progress, so new jobs appear in
 * the grid without a manual page refresh.
 */
export function LiveJobGridWrapper({ scanIsActive, evalIsActive, children }: Props) {
  useRealtimeEvalUpdates(scanIsActive || evalIsActive)
  return <>{children}</>
}
