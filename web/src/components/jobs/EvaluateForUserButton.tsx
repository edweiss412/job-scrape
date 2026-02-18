'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { Spinner } from '@/components/ui/spinner'

type EvalPhase =
  | 'idle'
  | 'triggering'
  | 'pending'
  | 'running'
  | 'completed'
  | 'error'

interface Props {
  /** Pre-seeded from the server — skips the first GET poll */
  initialStatus?: EvalPhase
  jobCount?: number | null
  jobsDone?: number | null
  evalStartedAt?: string | null
}

export function EvaluateForUserButton({ initialStatus = 'idle', jobCount, jobsDone: initialJobsDone, evalStartedAt }: Props) {
  const router = useRouter()
  const [phase, setPhase] = useState<EvalPhase>(initialStatus)
  const [total, setTotal] = useState<number | null>(jobCount ?? null)
  const [done, setDone] = useState<number | null>(initialJobsDone ?? null)
  const [elapsed, setElapsed] = useState(0)
  const [startedAt, setStartedAt] = useState<number | null>(
    evalStartedAt ? new Date(evalStartedAt).getTime() : null
  )
  const [errorMsg, setErrorMsg] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const refreshRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Start polling when pending/running
  useEffect(() => {
    if (phase !== 'pending' && phase !== 'running') {
      if (pollRef.current) clearInterval(pollRef.current)
      if (timerRef.current) clearInterval(timerRef.current)
      if (refreshRef.current) clearInterval(refreshRef.current)
      if (phase !== 'completed' && phase !== 'error') setElapsed(0)
      return
    }

    // Elapsed timer
    const t0 = startedAt ?? Date.now()
    timerRef.current = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000)

    // Status poll every 5s
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch('/api/scan/evaluate')
        if (!res.ok) return
        const data = await res.json()
        if (data.job_count != null) setTotal(data.job_count)
        if (data.jobs_done != null) setDone(data.jobs_done)
        if (data.status === 'completed') {
          setPhase('completed')
          router.refresh()
        } else if (data.status === 'error') {
          setPhase('error')
          setErrorMsg('Evaluation failed — check GitHub Actions logs.')
        } else if (data.status === 'running' && phase === 'pending') {
          setPhase('running')
          if (data.started_at) setStartedAt(new Date(data.started_at).getTime())
        }
      } catch { /* network hiccup — keep polling */ }
    }, 5_000)

    // Refresh the job grid every 15s while running to show new results as they land
    if (phase === 'running') {
      refreshRef.current = setInterval(() => router.refresh(), 15_000)
    }

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      if (timerRef.current) clearInterval(timerRef.current)
      if (refreshRef.current) clearInterval(refreshRef.current)
    }
  }, [phase, startedAt, router])

  async function trigger() {
    setPhase('triggering')
    setErrorMsg('')
    setDone(null)
    setTotal(null)
    try {
      const res = await fetch('/api/scan/evaluate', { method: 'POST' })
      const data = await res.json()
      if (!res.ok) {
        setPhase('error')
        setErrorMsg(data.error ?? 'Unknown error')
        return
      }
      setStartedAt(Date.now())
      setPhase('pending')
    } catch (e) {
      setPhase('error')
      setErrorMsg(String(e))
    }
  }

  function fmt(s: number) {
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
  }

  const pct = total && total > 0 && done != null ? Math.min(100, Math.round((done / total) * 100)) : null

  if (phase === 'completed') {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-emerald-900/30 bg-emerald-950/10 px-4 py-2.5">
        <svg className="h-3.5 w-3.5 shrink-0 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
        <span className="font-mono text-xs text-emerald-400">
          {total != null ? `${total} jobs evaluated` : 'Evaluation complete'}
        </span>
        <button
          onClick={() => { setPhase('idle'); router.refresh() }}
          className="ml-2 font-mono text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          refresh →
        </button>
      </div>
    )
  }

  if (phase === 'pending' || phase === 'running') {
    return (
      <div className="flex flex-col gap-1.5 rounded-lg border border-amber-900/30 bg-amber-950/10 px-4 py-2.5 min-w-[260px]">
        {/* Top row: pulse dot + label + elapsed */}
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-500 opacity-40" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
          </span>
          <span className="font-mono text-xs text-amber-400 flex-1">
            {phase === 'pending' ? 'Starting…' : (
              done != null && total != null
                ? `${done} / ${total} jobs`
                : total != null
                ? `~${total} jobs`
                : 'Evaluating…'
            )}
          </span>
          {phase === 'running' && (
            <span className="font-mono text-[10px] text-amber-600 tabular-nums">{fmt(elapsed)}</span>
          )}
        </div>

        {/* Progress bar — only when running and we have data */}
        {phase === 'running' && (
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

  if (phase === 'error') {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-red-900/30 bg-red-950/10 px-4 py-2.5">
        <span className="font-mono text-xs text-red-400">{errorMsg || 'Evaluation failed'}</span>
        <button
          onClick={() => setPhase('idle')}
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
      disabled={phase === 'triggering'}
      className="inline-flex items-center gap-2 rounded-lg border border-emerald-900/40 bg-emerald-950/20 px-4 py-2.5 text-xs font-medium text-emerald-400 transition-all hover:bg-emerald-950/40 disabled:opacity-50"
    >
      {phase === 'triggering' ? (
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
