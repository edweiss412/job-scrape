'use client'

import { useState } from 'react'
import { useEvalStatus } from '@/lib/contexts/EvalStatusContext'
import { Spinner } from '@/components/ui/spinner'

interface StatusBarProps {
  unevaluatedCount: number
  latestScrapeDate: string | null
  isStale: boolean
  lastEvalAt: string | null
}

export function StatusBar({ unevaluatedCount, latestScrapeDate, isStale, lastEvalAt }: StatusBarProps) {
  const { status, total, done, elapsed, errorMsg, trigger, cancel, dismiss } = useEvalStatus()
  const [newJobsDismissed, setNewJobsDismissed] = useState(false)

  const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
  const pct = total && total > 0 && done != null ? Math.min(100, Math.round((done / total) * 100)) : null

  // ── Priority 1: Eval in-progress / terminal states ──────────────────────

  if (status === 'triggering') {
    return (
      <div className="mb-5 flex items-center gap-3 rounded-lg border border-amber-900/30 bg-amber-950/10 px-4 py-2.5">
        <Spinner className="h-3.5 w-3.5 text-amber-500" />
        <span className="font-mono text-xs text-amber-400">Starting evaluation…</span>
      </div>
    )
  }

  if (status === 'pending' || status === 'running' || status === 'cancelling') {
    return (
      <div className="mb-5 rounded-lg border border-amber-900/30 bg-amber-950/10 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-500 opacity-40" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
          </span>
          <span className="font-mono text-xs text-amber-400 flex-1">
            {status === 'cancelling' ? 'Cancelling…' : status === 'pending' ? 'Queuing evaluation…' : (
              done != null && total != null ? `Evaluating — ${done} / ${total} jobs` :
              total != null ? `Evaluating ~${total} jobs…` : 'Evaluating…'
            )}
          </span>
          <span className="font-mono text-[10px] text-amber-600 tabular-nums">{fmt(elapsed)}</span>
          {status !== 'cancelling' && (
            <button onClick={cancel} className="font-mono text-[10px] text-red-400/60 transition-colors hover:text-red-400">
              cancel
            </button>
          )}
        </div>
        {(status === 'running' || status === 'cancelling') && (
          <div className="mt-2 h-px w-full rounded-full bg-amber-950/60 overflow-hidden">
            <div
              className="h-full rounded-full bg-amber-500/60 transition-all duration-700 ease-out"
              style={{ width: pct != null ? `${pct}%` : '0%' }}
            />
          </div>
        )}
      </div>
    )
  }

  if (status === 'completed') {
    return (
      <div className="mb-5 flex items-center gap-3 rounded-lg border border-emerald-900/30 bg-emerald-950/10 px-4 py-2.5">
        <svg className="h-3.5 w-3.5 shrink-0 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
        <span className="font-mono text-xs text-emerald-400 flex-1">
          {total != null ? `${total} jobs evaluated` : 'Evaluation complete'}
        </span>
        <button onClick={dismiss} className="font-mono text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors">
          refresh →
        </button>
      </div>
    )
  }

  if (status === 'cancelled') {
    return (
      <div className="mb-5 flex items-center gap-3 rounded-lg border border-zinc-700 bg-zinc-900/50 px-4 py-2.5">
        <span className="font-mono text-xs text-zinc-400 flex-1">
          Evaluation cancelled{done != null ? ` — ${done} jobs scored` : ''}
        </span>
        <button onClick={dismiss} className="font-mono text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors">
          dismiss
        </button>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="mb-5 flex items-center gap-3 rounded-lg border border-red-900/30 bg-red-950/10 px-4 py-2.5">
        <span className="font-mono text-xs text-red-400 flex-1">{errorMsg || 'Evaluation failed'}</span>
        <button onClick={dismiss} className="font-mono text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors">
          dismiss
        </button>
      </div>
    )
  }

  // ── Priority 2: New jobs available ──────────────────────────────────────

  if (unevaluatedCount > 0 && !newJobsDismissed) {
    const scrapeDate = latestScrapeDate
      ? new Date(latestScrapeDate + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      : null

    return (
      <div className="mb-5 flex items-center gap-3 rounded-lg border border-emerald-900/30 bg-emerald-950/10 px-4 py-2.5">
        <svg className="h-3.5 w-3.5 shrink-0 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
        </svg>
        <span className="text-xs text-emerald-300 flex-1">
          {unevaluatedCount} new job{unevaluatedCount !== 1 ? 's' : ''}
          {scrapeDate && <span className="text-emerald-600"> since {scrapeDate}</span>}
        </span>
        <button
          onClick={trigger}
          className="shrink-0 rounded-md border border-emerald-800/40 bg-emerald-950/30 px-3 py-1 font-mono text-[10px] font-medium text-emerald-400 transition-colors hover:bg-emerald-950/50"
        >
          Evaluate
        </button>
        <button
          onClick={() => setNewJobsDismissed(true)}
          className="p-0.5 text-zinc-600 transition-colors hover:text-zinc-400"
          aria-label="Dismiss"
        >
          <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    )
  }

  // ── Priority 3: Stale scores ────────────────────────────────────────────

  if (isStale) {
    return (
      <div className="mb-5 flex items-center gap-3 rounded-lg border border-amber-900/30 bg-amber-950/10 px-4 py-2.5">
        <svg className="h-3.5 w-3.5 shrink-0 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span className="text-xs text-amber-400 flex-1">
          Scores last updated {lastEvalAt ? new Date(lastEvalAt).toLocaleDateString() : 'a while ago'}
        </span>
        <button
          onClick={trigger}
          className="shrink-0 rounded-md border border-amber-800/40 bg-amber-950/30 px-3 py-1 font-mono text-[10px] font-medium text-amber-400 transition-colors hover:bg-amber-950/50"
        >
          Re-evaluate
        </button>
      </div>
    )
  }

  return null
}
