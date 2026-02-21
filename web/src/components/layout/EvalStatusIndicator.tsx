'use client'

import Link from 'next/link'
import { useEvalStatus } from '@/lib/contexts/EvalStatusContext'

export function EvalStatusIndicator() {
  const { status, total, done, cancel } = useEvalStatus()

  if (status === 'idle' || status === 'triggering') return null

  if (status === 'completed') {
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

  if (status === 'cancelled') {
    return (
      <div className="flex items-center gap-1.5 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1">
        <span className="font-mono text-[10px] text-zinc-500">Cancelled</span>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="flex items-center gap-1.5 rounded-md border border-red-900/40 bg-red-950/15 px-2 py-1">
        <span className="font-mono text-[10px] text-red-400">Eval failed</span>
      </div>
    )
  }

  // pending / running / cancelling
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
        {status === 'cancelling' ? 'Cancelling…' : status === 'pending' ? 'Evaluating…' : progress ? `Eval ${progress}` : 'Evaluating…'}
      </span>

      {/* Cancel link */}
      {status !== 'cancelling' && (
        <button
          onClick={cancel}
          className="font-mono text-[10px] text-red-400/60 transition-colors hover:text-red-400"
        >
          ✕
        </button>
      )}
    </div>
  )
}
