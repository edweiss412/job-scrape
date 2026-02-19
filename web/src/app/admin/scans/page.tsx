'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Nav } from '@/components/layout/nav'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'

/* ── Types ── */

interface WorkflowRun {
  id: number
  workflow: 'fulltime' | 'freelance' | 'evaluate'
  status: string
  conclusion: string | null
  event: string
  created_at: string
  run_started_at: string
  updated_at: string
  html_url: string
  duration_seconds: number | null
  actor: string | null
}

interface UserEvalInfo {
  user_id: string
  email: string | null
  eval_status: string
  eval_started_at: string | null
  eval_completed_at: string | null
  eval_job_count: number | null
  eval_jobs_done: number | null
}

interface FreelanceInputs {
  category: string
  max_companies: number
  no_verify: boolean
}

type TriggerState =
  | { phase: 'idle' }
  | { phase: 'inputs' }
  | { phase: 'triggering' }
  | { phase: 'done'; success: boolean; message: string }

/* ── Constants ── */

const FREELANCE_CATEGORIES = [
  { value: '', label: 'All categories' },
  { value: 'av_rental', label: 'AV Rental' },
  { value: 'production_co', label: 'Production Co' },
  { value: 'venue', label: 'Venue' },
  { value: 'touring', label: 'Touring' },
  { value: 'corporate_av', label: 'Corporate AV' },
  { value: 'university', label: 'University' },
]

const WORKFLOW_BADGE: Record<string, string> = {
  fulltime: 'border-amber-900/50 bg-amber-950/30 text-amber-500',
  freelance: 'border-blue-900/50 bg-blue-950/30 text-blue-400',
  evaluate: 'border-violet-900/50 bg-violet-950/30 text-violet-400',
}

const WORKFLOW_LABEL: Record<string, string> = {
  fulltime: 'Fulltime',
  freelance: 'Freelance',
  evaluate: 'Evaluate',
}

function statusBadgeClass(status: string, conclusion: string | null): string {
  if (status === 'completed') {
    if (conclusion === 'success') return 'border-emerald-900/40 bg-emerald-950/20 text-emerald-500'
    if (conclusion === 'cancelled') return 'border-zinc-700 bg-zinc-900 text-zinc-500'
    return 'border-red-900/40 bg-red-950/20 text-red-400'
  }
  if (status === 'in_progress') return 'border-amber-900/50 bg-amber-950/30 text-amber-500'
  if (status === 'queued' || status === 'waiting') return 'border-zinc-700 bg-zinc-900 text-zinc-400'
  return 'border-zinc-700 bg-zinc-900 text-zinc-500'
}

function statusLabel(status: string, conclusion: string | null): string {
  if (status === 'completed') return conclusion ?? 'completed'
  return status.replace('_', ' ')
}

function evalStatusBadge(status: string): string {
  if (status === 'running') return 'border-amber-900/50 bg-amber-950/30 text-amber-500'
  if (status === 'pending') return 'border-zinc-700 bg-zinc-900 text-zinc-400'
  if (status === 'completed') return 'border-emerald-900/40 bg-emerald-950/20 text-emerald-500'
  if (status === 'error') return 'border-red-900/40 bg-red-950/20 text-red-400'
  return 'border-zinc-800 bg-zinc-900/50 text-zinc-600'
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

function formatDateShort(dateStr: string | null): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

/* ── Component ── */

export default function AdminScansPage() {
  const pathname = usePathname()
  const [runs, setRuns] = useState<WorkflowRun[]>([])
  const [evaluations, setEvaluations] = useState<UserEvalInfo[]>([])
  const [loadingRuns, setLoadingRuns] = useState(true)
  const [loadingEvals, setLoadingEvals] = useState(true)
  const [cancelling, setCancelling] = useState<number | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)

  // Trigger state per scan type
  const [fulltimeTrigger, setFulltimeTrigger] = useState<TriggerState>({ phase: 'idle' })
  const [freelanceTrigger, setFreelanceTrigger] = useState<TriggerState>({ phase: 'idle' })
  const [freelanceInputs, setFreelanceInputs] = useState<FreelanceInputs>({
    category: '',
    max_companies: 100,
    no_verify: false,
  })

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  /* ── Data fetching ── */

  const fetchRuns = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/scans')
      if (!res.ok) return
      const data = await res.json()
      setRuns(data.runs ?? [])
    } finally {
      setLoadingRuns(false)
    }
  }, [])

  const fetchEvals = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/scans/evaluations')
      if (!res.ok) return
      const data = await res.json()
      setEvaluations(Array.isArray(data) ? data : [])
    } finally {
      setLoadingEvals(false)
    }
  }, [])

  useEffect(() => {
    fetchRuns()
    fetchEvals()
  }, [fetchRuns, fetchEvals])

  /* ── Polling ── */

  useEffect(() => {
    const hasActive = runs.some((r) => r.status === 'in_progress' || r.status === 'queued' || r.status === 'waiting')
    const hasRunningEval = evaluations.some((e) => e.eval_status === 'running' || e.eval_status === 'pending')
    const interval = hasActive || hasRunningEval ? 10_000 : 60_000

    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(() => {
      fetchRuns()
      fetchEvals()
    }, interval)

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [runs, evaluations, fetchRuns, fetchEvals])

  /* ── Trigger scan ── */

  async function triggerScan(type: 'fulltime' | 'freelance') {
    const setTrigger = type === 'fulltime' ? setFulltimeTrigger : setFreelanceTrigger
    setTrigger({ phase: 'triggering' })

    const body: Record<string, unknown> = { type }
    if (type === 'freelance') {
      if (freelanceInputs.category) body.category = freelanceInputs.category
      body.max_companies = freelanceInputs.max_companies
      if (freelanceInputs.no_verify) body.no_verify = true
    }

    try {
      const res = await fetch('/api/scan/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setTrigger({ phase: 'done', success: false, message: data.error ?? 'Unknown error' })
      } else {
        setTrigger({ phase: 'done', success: true, message: 'Dispatched' })
        // Refresh runs after a brief delay for GH to register the new run
        setTimeout(fetchRuns, 3000)
      }
    } catch {
      setTrigger({ phase: 'done', success: false, message: 'Network error' })
    }

    setTimeout(() => setTrigger({ phase: 'idle' }), 4000)
  }

  /* ── Cancel run ── */

  async function cancelRun(runId: number) {
    setCancelling(runId)
    try {
      await fetch('/api/admin/scans/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: runId }),
      })
      // Refresh after cancellation
      setTimeout(fetchRuns, 2000)
    } finally {
      setCancelling(null)
    }
  }

  /* ── Delete runs ── */

  async function deleteRuns(runIds: number[]) {
    if (!runIds.length) return
    setDeleting(true)
    try {
      const res = await fetch('/api/admin/scans/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_ids: runIds }),
      })
      if (res.ok) {
        const data = await res.json()
        const deletedSet = new Set(data.deleted as number[])
        setRuns((prev) => prev.filter((r) => !deletedSet.has(r.id)))
        setSelected((prev) => {
          const next = new Set(prev)
          for (const id of deletedSet) next.delete(id)
          return next
        })
      }
    } finally {
      setDeleting(false)
    }
  }

  function toggleSelect(runId: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(runId) ? next.delete(runId) : next.add(runId)
      return next
    })
  }

  function toggleSelectAll() {
    if (selected.size === runs.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(runs.map((r) => r.id)))
    }
  }

  /* ── Derived ── */

  const activeCount = runs.filter((r) => r.status === 'in_progress' || r.status === 'queued').length
  const recentSuccessCount = runs.filter((r) => r.conclusion === 'success').length
  const recentFailCount = runs.filter((r) => r.conclusion === 'failure').length

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-4xl px-4 py-8">

        {/* Sub-nav */}
        <div className="mb-6 flex items-center gap-1 border-b border-border pb-4">
          <Link href="/admin/feedback" className={cn('rounded-md px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider transition-colors', pathname === '/admin/feedback' ? 'bg-amber-950/40 text-amber-400' : 'text-zinc-600 hover:bg-surface-2 hover:text-zinc-400')}>Feedback</Link>
          <Link href="/admin/users" className={cn('rounded-md px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider transition-colors', pathname === '/admin/users' ? 'bg-amber-950/40 text-amber-400' : 'text-zinc-600 hover:bg-surface-2 hover:text-zinc-400')}>Users</Link>
          <Link href="/admin/scans" className={cn('rounded-md px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider transition-colors', pathname === '/admin/scans' ? 'bg-amber-950/40 text-amber-400' : 'text-zinc-600 hover:bg-surface-2 hover:text-zinc-400')}>Scans</Link>
        </div>

        {/* Header */}
        <div className="mb-6">
          <div className="mb-1 flex items-center gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-widest text-amber-500">Admin</span>
            <span className="font-mono text-[10px] text-zinc-700">/</span>
            <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">Scans</span>
          </div>
          <h1 className="text-xl font-bold text-white" style={{ fontFamily: 'Syne, sans-serif' }}>
            Scan Management
          </h1>
          <p className="mt-0.5 text-sm text-zinc-600">{runs.length} recent runs</p>
        </div>

        {/* Summary chips */}
        <div className="mb-5 flex flex-wrap gap-2">
          {activeCount > 0 && (
            <span className="rounded-full border border-amber-900/50 bg-amber-950/30 px-2.5 py-1 font-mono text-[10px] text-amber-500">
              {activeCount} active
            </span>
          )}
          <span className="rounded-full border border-emerald-900/40 bg-emerald-950/20 px-2.5 py-1 font-mono text-[10px] text-emerald-500">
            {recentSuccessCount} succeeded
          </span>
          {recentFailCount > 0 && (
            <span className="rounded-full border border-red-900/40 bg-red-950/20 px-2.5 py-1 font-mono text-[10px] text-red-400">
              {recentFailCount} failed
            </span>
          )}
        </div>

        {/* ── Section 1: Trigger Controls ── */}
        <div className="mb-8">
          <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-zinc-600">Trigger Scans</p>
          <div className="grid grid-cols-2 gap-3">
            {/* Fulltime */}
            <div className="rounded-xl border border-border bg-[#111] p-4">
              <div className="mb-3 flex items-center gap-2">
                <span className={cn('rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase', WORKFLOW_BADGE.fulltime)}>
                  Fulltime
                </span>
                <span className="font-mono text-[10px] text-zinc-700">scrape.yml</span>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => triggerScan('fulltime')}
                disabled={fulltimeTrigger.phase === 'triggering'}
              >
                {fulltimeTrigger.phase === 'triggering' ? (
                  <><Spinner className="h-3 w-3" /> Starting…</>
                ) : 'Run Scan'}
              </Button>
              {fulltimeTrigger.phase === 'done' && (
                <p className={cn('mt-2 font-mono text-[10px]', fulltimeTrigger.success ? 'text-emerald-500' : 'text-red-400')}>
                  {fulltimeTrigger.message}
                </p>
              )}
            </div>

            {/* Freelance */}
            <div className="rounded-xl border border-border bg-[#111] p-4">
              <div className="mb-3 flex items-center gap-2">
                <span className={cn('rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase', WORKFLOW_BADGE.freelance)}>
                  Freelance
                </span>
                <span className="font-mono text-[10px] text-zinc-700">freelance.yml</span>
              </div>

              {freelanceTrigger.phase === 'inputs' ? (
                <div className="space-y-3">
                  {/* Category */}
                  <div>
                    <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">
                      Category
                    </label>
                    <select
                      value={freelanceInputs.category}
                      onChange={(e) => setFreelanceInputs((f) => ({ ...f, category: e.target.value }))}
                      className="w-full rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-3 py-1.5 text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
                    >
                      {FREELANCE_CATEGORIES.map((c) => (
                        <option key={c.value} value={c.value}>{c.label}</option>
                      ))}
                    </select>
                  </div>

                  {/* Max companies */}
                  <div>
                    <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">
                      Max companies
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={500}
                      value={freelanceInputs.max_companies}
                      onChange={(e) => setFreelanceInputs((f) => ({ ...f, max_companies: Number(e.target.value) }))}
                      className="w-full rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-3 py-1.5 text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
                    />
                  </div>

                  {/* Skip verification */}
                  <div className="flex items-center justify-between">
                    <label className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">
                      Skip verification
                    </label>
                    <button
                      type="button"
                      onClick={() => setFreelanceInputs((f) => ({ ...f, no_verify: !f.no_verify }))}
                      className={cn(
                        'flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[10px] transition-all',
                        freelanceInputs.no_verify
                          ? 'border-emerald-900/50 bg-emerald-950/20 text-emerald-500'
                          : 'border-[#2a2a2a] text-zinc-600 hover:border-[#333] hover:text-zinc-400',
                      )}
                    >
                      <span className={cn('h-1.5 w-1.5 rounded-full transition-colors', freelanceInputs.no_verify ? 'bg-emerald-500' : 'bg-zinc-700')} />
                      {freelanceInputs.no_verify ? 'skipped' : 'verify'}
                    </button>
                  </div>

                  <div className="flex items-center gap-3 pt-1">
                    <button
                      onClick={() => triggerScan('freelance')}
                      className="flex-1 rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-black transition-opacity hover:opacity-90"
                    >
                      Start Scan
                    </button>
                    <button
                      onClick={() => setFreelanceTrigger({ phase: 'idle' })}
                      className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setFreelanceTrigger({ phase: 'inputs' })}
                    disabled={freelanceTrigger.phase === 'triggering'}
                  >
                    {freelanceTrigger.phase === 'triggering' ? (
                      <><Spinner className="h-3 w-3" /> Starting…</>
                    ) : 'Run Scan'}
                  </Button>
                  {freelanceTrigger.phase === 'done' && (
                    <p className={cn('mt-2 font-mono text-[10px]', freelanceTrigger.success ? 'text-emerald-500' : 'text-red-400')}>
                      {freelanceTrigger.message}
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
        </div>

        {/* ── Section 2: Workflow Run History ── */}
        <div className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-600">Workflow Run History</p>
              {selected.size > 0 && (
                <button
                  onClick={() => deleteRuns(Array.from(selected))}
                  disabled={deleting}
                  className="rounded-md border border-red-900/40 bg-red-950/20 px-2 py-0.5 font-mono text-[10px] text-red-400 transition-colors hover:bg-red-950/40 disabled:opacity-40"
                >
                  {deleting ? 'Deleting…' : `Delete ${selected.size} run${selected.size > 1 ? 's' : ''}`}
                </button>
              )}
            </div>
            <button
              onClick={() => { setLoadingRuns(true); fetchRuns() }}
              className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-zinc-400"
            >
              refresh
            </button>
          </div>

          {loadingRuns ? (
            <div className="py-12 text-center font-mono text-xs text-zinc-700">Loading…</div>
          ) : !runs.length ? (
            <div className="rounded-xl border border-border bg-[#111] p-12 text-center text-sm text-zinc-600">
              No workflow runs found.
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-border bg-[#111]">
              {/* Table header */}
              <div className="grid grid-cols-[28px_80px_70px_90px_110px_60px_70px_auto] gap-3 border-b border-border px-4 py-2.5">
                <input
                  type="checkbox"
                  checked={selected.size === runs.length && runs.length > 0}
                  onChange={toggleSelectAll}
                  className="h-3 w-3 cursor-pointer accent-amber-500"
                />
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Workflow</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Event</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Status</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Started</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Duration</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Actor</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 text-right">Actions</span>
              </div>

              {/* Rows */}
              {runs.map((run, i) => {
                const isActive = run.status === 'in_progress' || run.status === 'queued' || run.status === 'waiting'
                const isCancelling = cancelling === run.id

                return (
                  <div
                    key={run.id}
                    className={cn(
                      'grid grid-cols-[28px_80px_70px_90px_110px_60px_70px_auto] items-center gap-3 px-4 py-2.5 transition-colors hover:bg-[#141414]',
                      i !== runs.length - 1 && 'border-b border-border',
                    )}
                  >
                    {/* Checkbox */}
                    <input
                      type="checkbox"
                      checked={selected.has(run.id)}
                      onChange={() => toggleSelect(run.id)}
                      className="h-3 w-3 cursor-pointer accent-amber-500"
                    />

                    {/* Workflow badge */}
                    <span className={cn('inline-flex w-fit rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase', WORKFLOW_BADGE[run.workflow] ?? 'border-zinc-700 text-zinc-500')}>
                      {WORKFLOW_LABEL[run.workflow] ?? run.workflow}
                    </span>

                    {/* Event */}
                    <span className="truncate font-mono text-[10px] text-zinc-600">
                      {run.event === 'workflow_dispatch' ? 'dispatch' : run.event}
                    </span>

                    {/* Status badge */}
                    <span className="inline-flex items-center gap-1.5">
                      {isActive && (
                        <span className="relative flex h-1.5 w-1.5 shrink-0">
                          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-500 opacity-40" />
                          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" />
                        </span>
                      )}
                      <span className={cn('rounded-full border px-1.5 py-0.5 font-mono text-[10px] font-semibold', statusBadgeClass(run.status, run.conclusion))}>
                        {statusLabel(run.status, run.conclusion)}
                      </span>
                    </span>

                    {/* Started */}
                    <span className="font-mono text-[10px] text-zinc-600">{formatDate(run.run_started_at)}</span>

                    {/* Duration */}
                    <span className="font-mono text-[10px] text-zinc-600">
                      {run.status === 'completed' ? formatDuration(run.duration_seconds) : isActive ? '…' : '—'}
                    </span>

                    {/* Actor */}
                    <span className="truncate font-mono text-[10px] text-zinc-600">{run.actor ?? '—'}</span>

                    {/* Actions */}
                    <div className="flex items-center justify-end gap-2">
                      {isActive && (
                        <button
                          onClick={() => cancelRun(run.id)}
                          disabled={isCancelling}
                          className="font-mono text-[10px] text-red-400/70 transition-colors hover:text-red-400 disabled:opacity-40"
                        >
                          {isCancelling ? '…' : 'cancel'}
                        </button>
                      )}
                      {!isActive && (
                        <button
                          onClick={() => deleteRuns([run.id])}
                          disabled={deleting}
                          className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-red-400 disabled:opacity-40"
                        >
                          delete
                        </button>
                      )}
                      <a
                        href={run.html_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-zinc-400"
                      >
                        logs ↗
                      </a>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* ── Section 3: User Evaluation Statuses ── */}
        <div className="mb-8">
          <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-zinc-600">User Evaluation Statuses</p>

          {loadingEvals ? (
            <div className="py-12 text-center font-mono text-xs text-zinc-700">Loading…</div>
          ) : !evaluations.length ? (
            <div className="rounded-xl border border-border bg-[#111] p-12 text-center text-sm text-zinc-600">
              No user evaluations found.
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-border bg-[#111]">
              {/* Table header */}
              <div className="grid grid-cols-[1fr_90px_100px_110px_110px] gap-3 border-b border-border px-4 py-2.5">
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">User</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Status</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Progress</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Started</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Completed</span>
              </div>

              {/* Rows */}
              {evaluations.map((evalInfo, i) => {
                const isRunning = evalInfo.eval_status === 'running' || evalInfo.eval_status === 'pending'

                return (
                  <div
                    key={evalInfo.user_id}
                    className={cn(
                      'grid grid-cols-[1fr_90px_100px_110px_110px] items-center gap-3 px-4 py-2.5 transition-colors hover:bg-[#141414]',
                      i !== evaluations.length - 1 && 'border-b border-border',
                    )}
                  >
                    {/* Email */}
                    <span className="truncate text-sm text-zinc-300">{evalInfo.email ?? evalInfo.user_id.slice(0, 8)}</span>

                    {/* Status */}
                    <span className="inline-flex items-center gap-1.5">
                      {isRunning && (
                        <span className="relative flex h-1.5 w-1.5 shrink-0">
                          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-500 opacity-40" />
                          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" />
                        </span>
                      )}
                      <span className={cn('rounded-full border px-1.5 py-0.5 font-mono text-[10px] font-semibold', evalStatusBadge(evalInfo.eval_status))}>
                        {evalInfo.eval_status}
                      </span>
                    </span>

                    {/* Progress */}
                    <span className="font-mono text-[10px] text-zinc-600">
                      {evalInfo.eval_job_count != null
                        ? `${evalInfo.eval_jobs_done ?? 0}/${evalInfo.eval_job_count}`
                        : '—'}
                    </span>

                    {/* Started */}
                    <span className="font-mono text-[10px] text-zinc-600">{formatDateShort(evalInfo.eval_started_at)}</span>

                    {/* Completed */}
                    <span className="font-mono text-[10px] text-zinc-600">{formatDateShort(evalInfo.eval_completed_at)}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
