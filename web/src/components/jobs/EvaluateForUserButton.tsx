'use client'

import { usePathname } from 'next/navigation'
import Link from 'next/link'
import { Spinner } from '@/components/ui/spinner'
import { useEvalStatus } from '@/lib/contexts/EvalStatusContext'

export function EvaluateForUserButton() {
  const { status, total, done, elapsed, errorMsg, trigger, cancel, dismiss } = useEvalStatus()
  const pathname = usePathname()

  function fmt(s: number) {
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
  }

  const pct = total && total > 0 && done != null ? Math.min(100, Math.round((done / total) * 100)) : null

  if (status === 'completed') {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-emerald-900/30 bg-emerald-950/10 px-4 py-2.5">
        <svg className="h-3.5 w-3.5 shrink-0 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
        <span className="font-mono text-xs text-emerald-400">
          Evaluation complete
        </span>
        {pathname === '/profile' ? (
          <Link
            href="/opportunities/fulltime"
            className="ml-2 font-mono text-[10px] text-emerald-500 hover:text-emerald-300 transition-colors"
          >
            View your matches →
          </Link>
        ) : (
          <button
            onClick={dismiss}
            className="ml-2 font-mono text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            refresh →
          </button>
        )}
      </div>
    )
  }

  if (status === 'cancelled') {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900/50 px-4 py-2.5">
        <span className="font-mono text-xs text-zinc-400">
          Evaluation cancelled{done != null ? ` — ${done} jobs scored` : ''}
        </span>
        <button
          onClick={dismiss}
          className="ml-2 font-mono text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors"
        >
          dismiss
        </button>
      </div>
    )
  }

  if (status === 'pending' || status === 'running' || status === 'cancelling') {
    return (
      <div className="flex flex-col gap-1.5 rounded-lg border border-amber-900/30 bg-amber-950/10 px-4 py-2.5 min-w-65">
        {/* Top row: pulse dot + label + elapsed + cancel */}
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-500 opacity-40" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
          </span>
          <span className="font-mono text-xs text-amber-400 flex-1">
            {status === 'cancelling' ? 'Cancelling…' : status === 'pending' ? 'Queuing evaluation' : (
              done != null && total != null
                ? `${done} / ${total} jobs`
                : total != null
                ? `~${total} jobs`
                : 'Evaluating…'
            )}
          </span>
          <span className="font-mono text-[10px] text-amber-600 tabular-nums">{fmt(elapsed)}</span>
          {status !== 'cancelling' && (
            <button
              onClick={cancel}
              className="font-mono text-[10px] text-red-400/60 transition-colors hover:text-red-400"
            >
              cancel
            </button>
          )}
        </div>

        {/* Subtitle */}
        <p className="text-[10px] text-amber-700 font-mono">
          {status === 'cancelling'
            ? 'Stopping evaluation…'
            : status === 'pending'
            ? 'Step 1 of 2 — typically 30–60s to start'
            : total != null
            ? `Step 2 of 2 — scoring ${total} jobs against your resume`
            : 'Step 2 of 2 — scoring jobs against your resume'}
        </p>

        {/* Progress bar — only when running and we have data */}
        {(status === 'running' || status === 'cancelling') && (
          <div className="h-px w-full bg-amber-950/60 rounded-full overflow-hidden">
            <div
              className="h-full bg-amber-500/60 rounded-full transition-all duration-700 ease-out"
              style={{ width: pct != null ? `${pct}%` : '0%' }}
            />
          </div>
        )}
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-red-900/30 bg-red-950/10 px-4 py-2.5">
        <span className="font-mono text-xs text-red-400">{errorMsg || 'Evaluation failed'}</span>
        <button
          onClick={dismiss}
          className="ml-2 font-mono text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors"
        >
          dismiss
        </button>
      </div>
    )
  }

  return (
    <button
      onClick={trigger}
      disabled={status === 'triggering'}
      className="inline-flex items-center gap-2 rounded-lg border border-emerald-900/40 bg-emerald-950/20 px-4 py-2.5 text-xs font-medium text-emerald-400 transition-all hover:bg-emerald-950/40 disabled:opacity-50"
    >
      {status === 'triggering' ? (
        <>
          <Spinner className="h-3 w-3" />
          Starting…
        </>
      ) : (
        <>
          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
          Evaluate jobs against my resume
        </>
      )}
    </button>
  )
}
