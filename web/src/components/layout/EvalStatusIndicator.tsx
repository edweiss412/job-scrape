'use client'

import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'

type IndicatorState = 'hidden' | 'pending' | 'running' | 'cancelled' | 'completed'

export function EvalStatusIndicator() {
  const [state, setState] = useState<IndicatorState>('hidden')
  const [total, setTotal] = useState<number | null>(null)
  const [done, setDone] = useState<number | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const prevActiveRef = useRef(false)

  useEffect(() => {
    async function poll() {
      try {
        const res = await fetch('/api/scan/evaluate')
        if (!res.ok) return
        const data = await res.json()

        if (data.status === 'pending' || data.status === 'running') {
          setState(data.status)
          if (data.job_count != null) setTotal(data.job_count)
          if (data.jobs_done != null) setDone(data.jobs_done)
          setCancelling(false)
          prevActiveRef.current = true
        } else if (data.status === 'cancelled') {
          setState('cancelled')
          setCancelling(false)
          prevActiveRef.current = false
          if (hideTimerRef.current) clearTimeout(hideTimerRef.current)
          hideTimerRef.current = setTimeout(() => setState('hidden'), 4000)
        } else {
          // Status is idle/completed/error — check if we were previously active
          if (prevActiveRef.current) {
            setState('completed')
            prevActiveRef.current = false
            if (hideTimerRef.current) clearTimeout(hideTimerRef.current)
            hideTimerRef.current = setTimeout(() => setState('hidden'), 6000)
          } else {
            setState('hidden')
          }
        }
      } catch { /* network hiccup */ }
    }

    poll()
    pollRef.current = setInterval(poll, 5_000)

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current)
    }
  }, [])

  async function handleCancel() {
    setCancelling(true)
    try {
      await fetch('/api/scan/evaluate/cancel', { method: 'POST' })
    } catch {
      setCancelling(false)
    }
  }

  if (state === 'hidden') return null

  if (state === 'completed') {
    return (
      <Link
        href="/opportunities/fulltime"
        className="flex items-center gap-1.5 rounded-md border border-emerald-900/40 bg-emerald-950/15 px-2 py-1 transition-colors hover:bg-emerald-950/30"
      >
        <svg className="h-3.5 w-3.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
        <span className="font-mono text-[10px] text-emerald-400">Eval complete</span>
      </Link>
    )
  }

  if (state === 'cancelled') {
    return (
      <div className="flex items-center gap-1.5 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1">
        <span className="font-mono text-[10px] text-zinc-500">Cancelled</span>
      </div>
    )
  }

  const progress = done != null && total != null && total > 0
    ? `${done}/${total}`
    : total != null
    ? `~${total}`
    : null

  return (
    <div className="flex items-center gap-1.5 rounded-md border border-amber-900/40 bg-amber-950/15 px-2 py-1">
      {/* Pulsing dot */}
      <span className="relative flex h-1.5 w-1.5 shrink-0">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-500 opacity-40" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" />
      </span>

      <span className="font-mono text-[10px] text-amber-400">
        {state === 'pending' ? 'Evaluating…' : progress ? `Eval ${progress}` : 'Evaluating…'}
      </span>

      {/* Cancel link */}
      <button
        onClick={handleCancel}
        disabled={cancelling}
        className="font-mono text-[10px] text-red-400/60 transition-colors hover:text-red-400 disabled:opacity-40"
      >
        {cancelling ? '…' : '✕'}
      </button>
    </div>
  )
}
