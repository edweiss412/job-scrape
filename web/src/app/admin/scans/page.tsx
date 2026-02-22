'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { AdminSubNav } from '@/components/admin/AdminSubNav'
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
  source?: 'github' | 'supabase'
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

interface ScrapeStageInfo {
  run_date: string
  current_stage: string | null
}

interface ArchivedDateBucket {
  date: string
  count: number
}

interface ArchivedData {
  fulltime: ArchivedDateBucket[]
  freelance: ArchivedDateBucket[]
  totals: { jobs: number; companies: number }
}

interface ScrapeRunRow {
  run_date: string
  total_scraped: number | null
  new_jobs: number | null
  sources: string[] | null
  current_stage: string | null
  created_at: string | null
  pre_filter_stats: { passed?: number; failed?: number } | null
  expired_checked: number | null
  expired_found: number | null
  github_run_id: number | null
  gh_status: string | null
  gh_conclusion: string | null
  gh_html_url: string | null
  gh_duration_seconds: number | null
}

interface JobStats {
  total_jobs: number
  passed_prefilter: number
  active_jobs: number
  expired_jobs: number
}

/* ── Constants ── */

const SCRAPE_STAGES = [
  { key: 'scraping', label: 'Scraping', desc: 'Collecting listings' },
  { key: 'fetching_descriptions', label: 'Descriptions', desc: 'Fetching job details' },
  { key: 'syncing', label: 'Syncing', desc: 'Uploading to database' },
  { key: 'pre_filtering', label: 'Pre-filter', desc: 'Screening relevance' },
  { key: 'checking_expired', label: 'Expired check', desc: 'Verifying active URLs' },
] as const

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

const SOURCE_ABBREV: Record<string, string> = {
  serpapi: 'Serp',
  brightdata: 'BD',
  brightdata_google_jobs: 'BD',
  indeed: 'Indeed',
  indeed_rss: 'Indeed',
  avixa: 'AVIXA',
  career_pages: 'Career',
  career_page: 'Career',
  jobspy: 'JS',
  jobspy_indeed: 'JS',
  jobspy_google: 'JS',
  jobspy_glassdoor: 'JS',
  jobspy_ziprecruiter: 'JS',
}

function abbreviateSources(sources: string[] | null): string {
  if (!sources?.length) return '—'
  const abbrevs = sources.map((s) => SOURCE_ABBREV[s.toLowerCase()] ?? s)
  return [...new Set(abbrevs)].join(', ')
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
  if (status === 'cancelled') return 'border-zinc-700 bg-zinc-900 text-zinc-500'
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
  const [runs, setRuns] = useState<WorkflowRun[]>([])
  const [evaluations, setEvaluations] = useState<UserEvalInfo[]>([])
  const [loadingRuns, setLoadingRuns] = useState(true)
  const [loadingEvals, setLoadingEvals] = useState(true)
  const [cancelling, setCancelling] = useState<number | null>(null)
  const [cancellingEval, setCancellingEval] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [scrapeStage, setScrapeStage] = useState<ScrapeStageInfo | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [archiving, setArchiving] = useState(false)
  const [scrapeRuns, setScrapeRuns] = useState<ScrapeRunRow[]>([])
  const [jobStats, setJobStats] = useState<JobStats | null>(null)
  const [workflowRunsOpen, setWorkflowRunsOpen] = useState(false)
  const [deletingScrapeDate, setDeletingScrapeDate] = useState<string | null>(null)
  const [archivingScrapeDate, setArchivingScrapeDate] = useState<string | null>(null)

  // Trigger state per scan type
  const [fulltimeTrigger, setFulltimeTrigger] = useState<TriggerState>({ phase: 'idle' })
  const [freelanceTrigger, setFreelanceTrigger] = useState<TriggerState>({ phase: 'idle' })
  const [freelanceInputs, setFreelanceInputs] = useState<FreelanceInputs>({
    category: '',
    max_companies: 100,
    no_verify: false,
  })

  // Modal + purge state
  const [purgeModalOpen, setPurgeModalOpen] = useState(false)
  const [purgeAction, setPurgeAction] = useState<'delete' | 'archive'>('delete')
  const [purgeScope, setPurgeScope] = useState<'fulltime' | 'freelance' | 'all'>('all')
  const [purgeConfirm, setPurgeConfirm] = useState('')
  const [purging, setPurging] = useState(false)
  const [purgeResult, setPurgeResult] = useState<{ counts: Record<string, number>; action?: string; errors: string[] } | null>(null)

  // Archived data state
  const [archivedData, setArchivedData] = useState<ArchivedData | null>(null)
  const [loadingArchived, setLoadingArchived] = useState(true)
  const [restoringDates, setRestoringDates] = useState<Set<string>>(new Set())
  const [deletingDates, setDeletingDates] = useState<Set<string>>(new Set())
  const [restoreAllAction, setRestoreAllAction] = useState<'restore' | 'delete' | null>(null)
  const [archiveResult, setArchiveResult] = useState<{ counts: Record<string, number>; errors: string[] } | null>(null)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  function closePurgeModal() {
    setPurgeModalOpen(false)
    setPurgeConfirm('')
    setPurgeResult(null)
  }

  useEffect(() => {
    if (!purgeModalOpen) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') closePurgeModal()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [purgeModalOpen])

  /* ── Data fetching ── */

  const fetchRuns = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/scans')
      if (!res.ok) return
      const data = await res.json()
      setRuns(data.runs ?? [])
      setScrapeStage(data.scrapeStage ?? null)
      setScrapeRuns(data.scrapeRuns ?? [])
      setJobStats(data.jobStats ?? null)
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

  const fetchArchived = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/scans/archived')
      if (!res.ok) return
      const data = await res.json()
      setArchivedData(data)
    } finally {
      setLoadingArchived(false)
    }
  }, [])

  useEffect(() => {
    fetchRuns()
    fetchEvals()
    fetchArchived()
  }, [fetchRuns, fetchEvals, fetchArchived])

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

  async function cancelRun(runId: number, workflowType?: string, userId?: string) {
    setCancelling(runId)
    try {
      await fetch('/api/admin/scans/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: runId, workflow_type: workflowType, user_id: userId }),
      })
      // Refresh after cancellation
      setTimeout(() => { fetchRuns(); fetchEvals() }, 2000)
    } finally {
      setCancelling(null)
    }
  }

  async function cancelUserEval(userId: string) {
    setCancellingEval(userId)
    try {
      // Find the matching GH workflow run for this user's evaluation
      const evalRun = runs.find((r) => r.workflow === 'evaluate' && (r.status === 'in_progress' || r.status === 'queued'))
      if (evalRun) {
        await fetch('/api/admin/scans/cancel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ run_id: evalRun.id, workflow_type: 'evaluate', user_id: userId }),
        })
      } else {
        // No GH run found — just update DB directly
        await fetch('/api/admin/scans/cancel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          // Use a dummy run_id — the GH cancel will 404 but DB cleanup still happens
          body: JSON.stringify({ run_id: 0, workflow_type: 'evaluate', user_id: userId }),
        })
      }
      setTimeout(fetchEvals, 2000)
    } finally {
      setCancellingEval(null)
    }
  }

  /* ── Delete/Archive runs ── */

  async function handleRuns(runIds: number[], action: 'delete' | 'archive') {
    if (!runIds.length) return
    if (action === 'delete') setDeleting(true)
    else setArchiving(true)
    try {
      // Send full run metadata so the API can purge matching Supabase data
      const runsToHandle = runs
        .filter((r) => runIds.includes(r.id))
        .map((r) => ({ id: r.id, workflow: r.workflow, created_at: r.created_at, source: r.source }))

      const res = await fetch('/api/admin/scans/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ runs: runsToHandle, action }),
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
        if (action === 'archive') fetchArchived()
      }
    } finally {
      setDeleting(false)
      setArchiving(false)
    }
  }

  /* ── Scrape date actions ── */

  async function handleScrapeDate(date: string, action: 'delete' | 'archive') {
    if (action === 'delete') setDeletingScrapeDate(date)
    else setArchivingScrapeDate(date)
    try {
      const res = await fetch('/api/admin/scans/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dates: [date], action }),
      })
      if (res.ok) {
        fetchRuns()
        if (action === 'archive') fetchArchived()
      }
    } finally {
      setDeletingScrapeDate(null)
      setArchivingScrapeDate(null)
    }
  }

  /* ── Purge all data ── */

  const confirmWord = purgeAction === 'archive' ? 'ARCHIVE' : 'PURGE'

  async function purgeData() {
    if (purgeConfirm !== confirmWord) return
    setPurging(true)
    setPurgeResult(null)
    try {
      const res = await fetch('/api/admin/scans/purge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope: purgeScope, action: purgeAction }),
      })
      if (res.ok) {
        const data = await res.json()
        setPurgeResult(data)
        setPurgeConfirm('')
        // Refresh runs list
        fetchRuns()
        fetchEvals()
        if (purgeAction === 'archive') fetchArchived()
      }
    } finally {
      setPurging(false)
    }
  }

  /* ── Archived data actions ── */

  async function handleArchivedAction(action: 'restore' | 'delete', scope: 'fulltime' | 'freelance' | 'all', dates?: string[]) {
    const key = dates ? dates.join(',') : 'all'
    if (action === 'restore') setRestoringDates((prev) => new Set(prev).add(key))
    else setDeletingDates((prev) => new Set(prev).add(key))
    setArchiveResult(null)

    try {
      const res = await fetch('/api/admin/scans/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, scope, dates }),
      })
      if (res.ok) {
        const data = await res.json()
        setArchiveResult(data)
        fetchArchived()
      }
    } finally {
      setRestoringDates((prev) => {
        const next = new Set(prev)
        next.delete(key)
        return next
      })
      setDeletingDates((prev) => {
        const next = new Set(prev)
        next.delete(key)
        return next
      })
      setRestoreAllAction(null)
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

  const totalArchived = (archivedData?.totals.jobs ?? 0) + (archivedData?.totals.companies ?? 0)

  // Pipeline stepper state
  const fulltimeActive = runs.some(
    (r) => r.workflow === 'fulltime' && (r.status === 'in_progress' || r.status === 'queued' || r.status === 'waiting'),
  )
  const showStepper = fulltimeActive || (scrapeStage != null && scrapeStage.current_stage != null && scrapeStage.current_stage !== 'complete')
  const stepperActiveIdx = scrapeStage?.current_stage
    ? SCRAPE_STAGES.findIndex((s) => s.key === scrapeStage.current_stage)
    : -1
  const stepperCancelled = scrapeStage?.current_stage === 'cancelled'

  return (
      <main className="mx-auto w-full max-w-4xl px-4 py-8">

        <AdminSubNav />

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

        {/* Job stats chips */}
        {jobStats && (
          <div className="mb-5 flex flex-wrap gap-2">
            <span className="rounded-full border border-emerald-900/40 bg-emerald-950/20 px-2.5 py-1 font-mono text-[10px] text-emerald-500">
              {jobStats.active_jobs.toLocaleString()} active jobs
            </span>
            <span className="rounded-full border border-blue-900/50 bg-blue-950/30 px-2.5 py-1 font-mono text-[10px] text-blue-400">
              {jobStats.passed_prefilter.toLocaleString()} passed pre-filter
            </span>
            {jobStats.expired_jobs > 0 && (
              <span className="rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 font-mono text-[10px] text-zinc-500">
                {jobStats.expired_jobs.toLocaleString()} expired
              </span>
            )}
            {totalArchived > 0 && (
              <span className="rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 font-mono text-[10px] text-zinc-500">
                {totalArchived} archived
              </span>
            )}
          </div>
        )}

        {/* ── Section 1: Trigger Controls ── */}
        <div className="mb-8">
          <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-zinc-600">Trigger Scans</p>
          <div className="grid grid-cols-2 gap-3">
            {/* Fulltime */}
            <div className={cn(
              'rounded-xl border p-4 transition-colors duration-700',
              showStepper ? 'border-amber-900/30 bg-[#0f0f0e]' : 'border-border bg-[#111]',
            )}>
              <div className={cn('flex items-center gap-2', showStepper ? 'mb-4' : 'mb-3')}>
                <span className={cn('rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase', WORKFLOW_BADGE.fulltime)}>
                  Fulltime
                </span>
                <span className="font-mono text-[10px] text-zinc-700">scrape.yml</span>
                {showStepper && (
                  <span className="ml-auto animate-pulse rounded border border-amber-900/40 bg-amber-950/20 px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-wider text-amber-500/70">
                    Live
                  </span>
                )}
              </div>

              {showStepper ? (
                stepperCancelled ? (
                  <div className="flex items-center gap-2.5 rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-2">
                    <svg className="h-3 w-3 text-zinc-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                    <span className="font-mono text-[11px] text-zinc-500">Pipeline cancelled</span>
                  </div>
                ) : stepperActiveIdx === -1 ? (
                  <div className="flex items-center gap-2.5 rounded-lg border border-amber-900/20 bg-amber-950/10 px-3 py-2">
                    <Spinner className="h-3.5 w-3.5 text-amber-500" />
                    <span className="font-mono text-[11px] text-amber-500/80">Starting pipeline…</span>
                  </div>
                ) : (
                  <div className="flex flex-col">
                    {SCRAPE_STAGES.map((stage, si) => {
                      const isCompleted = si < stepperActiveIdx
                      const isCurrent = si === stepperActiveIdx
                      const isLast = si === SCRAPE_STAGES.length - 1

                      return (
                        <div key={stage.key} className="flex items-start gap-3">
                          <div className="flex flex-col items-center">
                            {isCompleted ? (
                              <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-emerald-800/50 bg-emerald-950/40">
                                <svg className="h-2.5 w-2.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                </svg>
                              </div>
                            ) : isCurrent ? (
                              <div className="relative flex h-5 w-5 shrink-0 items-center justify-center">
                                <span className="absolute h-4 w-4 animate-ping rounded-full bg-amber-500/20" />
                                <span className="relative h-2.5 w-2.5 rounded-full bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.4)]" />
                              </div>
                            ) : (
                              <div className="flex h-5 w-5 shrink-0 items-center justify-center">
                                <span className="h-1.5 w-1.5 rounded-full bg-zinc-800" />
                              </div>
                            )}
                            {!isLast && (
                              <div className={cn(
                                'w-px transition-colors duration-500',
                                isCompleted ? 'h-3 bg-emerald-800/40' : isCurrent ? 'h-3 bg-amber-800/20' : 'h-3 bg-zinc-800/30',
                              )} />
                            )}
                          </div>
                          <div className="flex items-baseline gap-2 pt-0.5">
                            <span className={cn(
                              'font-mono text-[11px] font-medium transition-colors duration-500',
                              isCompleted ? 'text-emerald-500/70' : isCurrent ? 'text-amber-400' : 'text-zinc-700',
                            )}>
                              {stage.label}
                            </span>
                            {isCurrent && (
                              <span className="font-mono text-[10px] text-amber-500/30">{stage.desc}</span>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )
              ) : (
                <>
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
                </>
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

        {/* ── Section 2: Scrape Results ── */}
        <div className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-600">Scrape Results</p>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setPurgeModalOpen(true)}
                className="rounded-md border border-zinc-800 bg-zinc-900 px-2 py-0.5 font-mono text-[10px] text-zinc-500 transition-colors hover:border-zinc-700 hover:text-zinc-400"
              >
                Manage Data
              </button>
              <button
                onClick={() => { setLoadingRuns(true); fetchRuns() }}
                className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-zinc-400"
              >
                refresh
              </button>
            </div>
          </div>

          {loadingRuns ? (
            <div className="py-12 text-center font-mono text-xs text-zinc-700">Loading…</div>
          ) : !scrapeRuns.length ? (
            <div className="rounded-xl border border-border bg-[#111] p-12 text-center text-sm text-zinc-600">
              No scrape data yet. Trigger a scan above.
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-border bg-[#111]">
              {/* Table header */}
              <div className="grid grid-cols-[80px_110px_70px_55px_110px_70px_1fr_auto] gap-3 border-b border-border px-4 py-2.5">
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Date</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 cursor-help" title="GitHub Actions workflow run status and duration">Run</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 cursor-help" title="Total listings scraped across all sources">Scraped</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 cursor-help" title="Jobs not seen in any previous scrape run">New</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 cursor-help" title="Keyword relevance filter: passed (green) / failed (red)">Pre-filter</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 cursor-help" title="Expired listings found out of URLs checked">Expired</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Sources</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 text-right">Actions</span>
              </div>

              {/* Rows */}
              {scrapeRuns.map((sr, i) => {
                const passed = sr.pre_filter_stats?.passed ?? 0
                const failed = sr.pre_filter_stats?.failed ?? 0
                const isDeleting = deletingScrapeDate === sr.run_date
                const isArchiving = archivingScrapeDate === sr.run_date
                const isBusy = isDeleting || isArchiving

                return (
                  <div
                    key={sr.run_date}
                    className={cn(
                      'grid grid-cols-[80px_110px_70px_55px_110px_70px_1fr_auto] items-center gap-3 px-4 py-2.5 transition-colors hover:bg-[#141414]',
                      i !== scrapeRuns.length - 1 && 'border-b border-border',
                    )}
                  >
                    {/* Date */}
                    <span className="font-mono text-xs text-zinc-300">
                      {new Date(sr.run_date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                    </span>

                    {/* GH Run status */}
                    <span className="font-mono text-[10px]">
                      {sr.gh_html_url ? (
                        <a
                          href={sr.gh_html_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={cn(
                            'inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 font-semibold transition-colors hover:opacity-80',
                            statusBadgeClass(sr.gh_status ?? 'completed', sr.gh_conclusion ?? null),
                          )}
                        >
                          {statusLabel(sr.gh_status ?? 'completed', sr.gh_conclusion ?? null)}
                          {sr.gh_duration_seconds != null && (
                            <span className="text-[9px] opacity-60">{formatDuration(sr.gh_duration_seconds)}</span>
                          )}
                        </a>
                      ) : sr.github_run_id ? (
                        <span className="text-zinc-700">#{sr.github_run_id}</span>
                      ) : (
                        <span className="text-zinc-800">local</span>
                      )}
                    </span>

                    {/* Scraped */}
                    <span className="font-mono text-[11px] text-zinc-400">
                      {sr.total_scraped?.toLocaleString() ?? '—'}
                    </span>

                    {/* New */}
                    <span className="font-mono text-[11px] text-zinc-400">
                      {sr.new_jobs?.toLocaleString() ?? '—'}
                    </span>

                    {/* Pre-filter */}
                    <span className="flex items-center gap-1.5 font-mono text-[11px]">
                      {passed + failed > 0 ? (
                        <>
                          <span className="text-emerald-500">{passed.toLocaleString()}</span>
                          <span className="text-zinc-700">/</span>
                          <span className="text-red-400/70">{failed.toLocaleString()}</span>
                        </>
                      ) : (
                        <span className="text-zinc-700">—</span>
                      )}
                    </span>

                    {/* Expired */}
                    <span className="font-mono text-[11px] text-zinc-500">
                      {sr.expired_checked != null ? `${sr.expired_found ?? 0}/${sr.expired_checked}` : '—'}
                    </span>

                    {/* Sources */}
                    <span className="truncate font-mono text-[10px] text-zinc-600">
                      {abbreviateSources(sr.sources)}
                    </span>

                    {/* Actions */}
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => handleScrapeDate(sr.run_date, 'archive')}
                        disabled={isBusy}
                        className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-zinc-400 disabled:opacity-40"
                      >
                        {isArchiving ? '…' : 'archive'}
                      </button>
                      <button
                        onClick={() => handleScrapeDate(sr.run_date, 'delete')}
                        disabled={isBusy}
                        className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-red-400 disabled:opacity-40"
                      >
                        {isDeleting ? '…' : 'delete'}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* ── Section 3: Workflow Runs (collapsed) ── */}
        <div className="mb-8">
          <button
            onClick={() => setWorkflowRunsOpen((v) => !v)}
            className="mb-3 flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-zinc-600 transition-colors hover:text-zinc-400"
          >
            <svg
              className={cn('h-3 w-3 transition-transform', workflowRunsOpen && 'rotate-90')}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            Workflow Runs ({runs.length})
          </button>

          {workflowRunsOpen && (
            <>
              {selected.size > 0 && (
                <div className="mb-3 flex items-center gap-3">
                  <button
                    onClick={() => handleRuns(Array.from(selected), 'archive')}
                    disabled={archiving || deleting}
                    className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-0.5 font-mono text-[10px] text-zinc-400 transition-colors hover:bg-zinc-800 disabled:opacity-40"
                  >
                    {archiving ? 'Archiving…' : `Archive ${selected.size} run${selected.size > 1 ? 's' : ''}`}
                  </button>
                  <button
                    onClick={() => handleRuns(Array.from(selected), 'delete')}
                    disabled={deleting || archiving}
                    className="rounded-md border border-red-900/40 bg-red-950/20 px-2 py-0.5 font-mono text-[10px] text-red-400 transition-colors hover:bg-red-950/40 disabled:opacity-40"
                  >
                    {deleting ? 'Deleting…' : `Delete ${selected.size} run${selected.size > 1 ? 's' : ''}`}
                  </button>
                </div>
              )}

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
                      <div key={run.id}>
                        <div
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
                            {isActive && run.source !== 'supabase' && (
                              <button
                                onClick={() => cancelRun(run.id, run.workflow)}
                                disabled={isCancelling}
                                className="font-mono text-[10px] text-red-400/70 transition-colors hover:text-red-400 disabled:opacity-40"
                              >
                                {isCancelling ? '…' : 'cancel'}
                              </button>
                            )}
                            {!isActive && (
                              <>
                                <button
                                  onClick={() => handleRuns([run.id], 'archive')}
                                  disabled={archiving || deleting}
                                  className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-zinc-400 disabled:opacity-40"
                                >
                                  archive
                                </button>
                                <button
                                  onClick={() => handleRuns([run.id], 'delete')}
                                  disabled={deleting || archiving}
                                  className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-red-400 disabled:opacity-40"
                                >
                                  delete
                                </button>
                              </>
                            )}
                            {run.html_url ? (
                              <a
                                href={run.html_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-zinc-400"
                              >
                                logs ↗
                              </a>
                            ) : (
                              <span className="font-mono text-[10px] text-zinc-800">—</span>
                            )}
                          </div>
                        </div>

                      </div>
                    )
                  })}
                </div>
              )}
            </>
          )}
        </div>

        {/* ── Section 4: User Evaluation Statuses ── */}
        <div className="mb-10">
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
              <div className="grid grid-cols-[1fr_90px_100px_110px_110px_60px] gap-3 border-b border-border px-4 py-2.5">
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">User</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Status</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Progress</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Started</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Completed</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 text-right">Actions</span>
              </div>

              {/* Rows */}
              {evaluations.map((evalInfo, i) => {
                const isRunning = evalInfo.eval_status === 'running' || evalInfo.eval_status === 'pending'
                const isEvalCancelling = cancellingEval === evalInfo.user_id

                return (
                  <div
                    key={evalInfo.user_id}
                    className={cn(
                      'grid grid-cols-[1fr_90px_100px_110px_110px_60px] items-center gap-3 px-4 py-2.5 transition-colors hover:bg-[#141414]',
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

                    {/* Actions */}
                    <div className="flex items-center justify-end">
                      {isRunning && (
                        <button
                          onClick={() => cancelUserEval(evalInfo.user_id)}
                          disabled={isEvalCancelling}
                          className="font-mono text-[10px] text-red-400/70 transition-colors hover:text-red-400 disabled:opacity-40"
                        >
                          {isEvalCancelling ? '…' : 'cancel'}
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* ── Purge / Archive Modal ── */}
        {purgeModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={closePurgeModal}>
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
            <div className="relative z-10 w-full max-w-md rounded-xl border border-[#252525] bg-[#0e0e0e] shadow-2xl" onClick={(e) => e.stopPropagation()}>
              {/* Modal header */}
              <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
                <h2 className="text-sm font-semibold text-white">Manage Data</h2>
                <button onClick={closePurgeModal} className="text-zinc-600 transition-colors hover:text-zinc-400">
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              {/* Modal body */}
              <div className="p-5">
                <p className="mb-4 text-sm text-zinc-400">
                  {purgeAction === 'archive'
                    ? 'Archive data for the selected scope. Jobs and companies will be hidden from user-facing pages but can be restored later.'
                    : 'Permanently delete all Supabase data for the selected scope. Evaluations and run metadata will be removed. This cannot be undone.'}
                </p>

                {/* Action toggle */}
                <div className="mb-4">
                  <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-zinc-600">Action</p>
                  <div className="flex gap-2">
                    {(['delete', 'archive'] as const).map((a) => (
                      <button
                        key={a}
                        onClick={() => { setPurgeAction(a); setPurgeResult(null); setPurgeConfirm('') }}
                        className={cn(
                          'rounded-full border px-3 py-1 font-mono text-[10px] font-semibold uppercase transition-all',
                          purgeAction === a
                            ? a === 'delete'
                              ? 'border-red-900/50 bg-red-950/30 text-red-400'
                              : 'border-zinc-600 bg-zinc-800 text-zinc-300'
                            : 'border-[#2a2a2a] text-zinc-600 hover:border-[#333] hover:text-zinc-400',
                        )}
                      >
                        {a}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Scope selector */}
                <div className="mb-4">
                  <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-zinc-600">Scope</p>
                  <div className="flex gap-2">
                    {(['fulltime', 'freelance', 'all'] as const).map((scope) => (
                      <button
                        key={scope}
                        onClick={() => { setPurgeScope(scope); setPurgeResult(null) }}
                        className={cn(
                          'rounded-full border px-3 py-1 font-mono text-[10px] font-semibold uppercase transition-all',
                          purgeScope === scope
                            ? purgeAction === 'delete'
                              ? 'border-red-900/50 bg-red-950/30 text-red-400'
                              : 'border-zinc-600 bg-zinc-800 text-zinc-300'
                            : 'border-[#2a2a2a] text-zinc-600 hover:border-[#333] hover:text-zinc-400',
                        )}
                      >
                        {scope}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Confirmation input */}
                <div className="mb-4">
                  <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-zinc-600">
                    Type {confirmWord} to confirm
                  </p>
                  <input
                    type="text"
                    value={purgeConfirm}
                    onChange={(e) => setPurgeConfirm(e.target.value)}
                    placeholder={confirmWord}
                    className={cn(
                      'w-48 rounded-lg border bg-[#0e0e0e] px-3 py-1.5 font-mono text-xs text-zinc-300 placeholder:text-zinc-800 focus:outline-none',
                      purgeAction === 'delete' ? 'border-[#2a2a2a] focus:border-red-900/50' : 'border-[#2a2a2a] focus:border-zinc-600',
                    )}
                  />
                </div>

                <button
                  onClick={purgeData}
                  disabled={purgeConfirm !== confirmWord || purging}
                  className={cn(
                    'rounded-lg border px-4 py-1.5 font-mono text-xs font-semibold transition-all',
                    purgeConfirm === confirmWord && !purging
                      ? purgeAction === 'delete'
                        ? 'border-red-900/50 bg-red-950/30 text-red-400 hover:bg-red-950/50'
                        : 'border-zinc-600 bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
                      : 'border-[#2a2a2a] text-zinc-700 cursor-not-allowed',
                  )}
                >
                  {purging
                    ? purgeAction === 'archive' ? 'Archiving…' : 'Purging…'
                    : `${purgeAction === 'archive' ? 'Archive' : 'Purge'} ${purgeScope} data`}
                </button>

                {/* Results */}
                {purgeResult && (
                  <div className="mt-4 rounded-lg border border-[#2a2a2a] bg-background p-3">
                    <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-emerald-500">
                      {purgeResult.action === 'archive' ? 'Archive' : 'Purge'} complete
                    </p>
                    <div className="space-y-1">
                      {Object.entries(purgeResult.counts).map(([table, count]) => (
                        <div key={table} className="flex items-center justify-between font-mono text-[10px]">
                          <span className="text-zinc-500">{table}</span>
                          <span className="text-zinc-300">
                            {count} {purgeResult.action === 'archive' ? 'archived' : 'deleted'}
                          </span>
                        </div>
                      ))}
                    </div>
                    {purgeResult.errors.length > 0 && (
                      <div className="mt-2 border-t border-[#2a2a2a] pt-2">
                        {purgeResult.errors.map((err, i) => (
                          <p key={i} className="font-mono text-[10px] text-red-400">{err}</p>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── Section 5: Archived Data ── */}
        <div className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-600">Archived Data</p>
            <button
              onClick={() => { setLoadingArchived(true); fetchArchived() }}
              className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-zinc-400"
            >
              refresh
            </button>
          </div>

          {loadingArchived ? (
            <div className="py-12 text-center font-mono text-xs text-zinc-700">Loading…</div>
          ) : totalArchived === 0 ? (
            <div className="rounded-xl border border-border bg-[#111] p-12 text-center text-sm text-zinc-600">
              No archived data.
            </div>
          ) : (
            <div className="rounded-xl border border-border bg-[#111] p-5">
              {/* Totals */}
              <div className="mb-4 flex items-center gap-4">
                <span className="font-mono text-[10px] text-zinc-500">
                  {archivedData!.totals.jobs} job{archivedData!.totals.jobs !== 1 ? 's' : ''}
                </span>
                <span className="font-mono text-[10px] text-zinc-500">
                  {archivedData!.totals.companies} compan{archivedData!.totals.companies !== 1 ? 'ies' : 'y'}
                </span>
              </div>

              {/* Fulltime archived */}
              {archivedData!.fulltime.length > 0 && (
                <div className="mb-4">
                  <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-amber-500/70">Fulltime Jobs</p>
                  <div className="space-y-1">
                    {archivedData!.fulltime.map((bucket) => (
                      <div key={`ft-${bucket.date}`} className="flex items-center justify-between rounded-lg border border-[#1a1a1a] bg-background px-3 py-2">
                        <div className="flex items-center gap-3">
                          <span className="font-mono text-xs text-zinc-400">{bucket.date}</span>
                          <span className="font-mono text-[10px] text-zinc-600">{bucket.count} job{bucket.count !== 1 ? 's' : ''}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => handleArchivedAction('restore', 'fulltime', [bucket.date])}
                            disabled={restoringDates.has(bucket.date) || deletingDates.has(bucket.date)}
                            className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-emerald-400 disabled:opacity-40"
                          >
                            {restoringDates.has(bucket.date) ? '…' : 'restore'}
                          </button>
                          <button
                            onClick={() => handleArchivedAction('delete', 'fulltime', [bucket.date])}
                            disabled={deletingDates.has(bucket.date) || restoringDates.has(bucket.date)}
                            className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-red-400 disabled:opacity-40"
                          >
                            {deletingDates.has(bucket.date) ? '…' : 'delete'}
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Freelance archived */}
              {archivedData!.freelance.length > 0 && (
                <div className="mb-4">
                  <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-blue-400/70">Freelance Companies</p>
                  <div className="space-y-1">
                    {archivedData!.freelance.map((bucket) => (
                      <div key={`fl-${bucket.date}`} className="flex items-center justify-between rounded-lg border border-[#1a1a1a] bg-background px-3 py-2">
                        <div className="flex items-center gap-3">
                          <span className="font-mono text-xs text-zinc-400">{bucket.date}</span>
                          <span className="font-mono text-[10px] text-zinc-600">{bucket.count} compan{bucket.count !== 1 ? 'ies' : 'y'}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => handleArchivedAction('restore', 'freelance', [bucket.date])}
                            disabled={restoringDates.has(bucket.date) || deletingDates.has(bucket.date)}
                            className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-emerald-400 disabled:opacity-40"
                          >
                            {restoringDates.has(bucket.date) ? '…' : 'restore'}
                          </button>
                          <button
                            onClick={() => handleArchivedAction('delete', 'freelance', [bucket.date])}
                            disabled={deletingDates.has(bucket.date) || restoringDates.has(bucket.date)}
                            className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-red-400 disabled:opacity-40"
                          >
                            {deletingDates.has(bucket.date) ? '…' : 'delete'}
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Bulk actions */}
              <div className="flex items-center gap-3 border-t border-[#1a1a1a] pt-4">
                <button
                  onClick={() => { setRestoreAllAction('restore'); handleArchivedAction('restore', 'all') }}
                  disabled={restoreAllAction !== null}
                  className="rounded-lg border border-emerald-900/40 bg-emerald-950/20 px-3 py-1.5 font-mono text-[10px] font-semibold text-emerald-400 transition-colors hover:bg-emerald-950/40 disabled:opacity-40"
                >
                  {restoreAllAction === 'restore' ? 'Restoring…' : 'Restore All'}
                </button>
                <button
                  onClick={() => { setRestoreAllAction('delete'); handleArchivedAction('delete', 'all') }}
                  disabled={restoreAllAction !== null}
                  className="rounded-lg border border-red-900/40 bg-red-950/20 px-3 py-1.5 font-mono text-[10px] font-semibold text-red-400 transition-colors hover:bg-red-950/40 disabled:opacity-40"
                >
                  {restoreAllAction === 'delete' ? 'Deleting…' : 'Permanently Delete All'}
                </button>
              </div>

              {/* Result display */}
              {archiveResult && (
                <div className="mt-4 rounded-lg border border-[#2a2a2a] bg-background p-3">
                  <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-emerald-500">Done</p>
                  <div className="space-y-1">
                    {Object.entries(archiveResult.counts).map(([key, count]) => (
                      <div key={key} className="flex items-center justify-between font-mono text-[10px]">
                        <span className="text-zinc-500">{key}</span>
                        <span className="text-zinc-300">{count}</span>
                      </div>
                    ))}
                  </div>
                  {archiveResult.errors.length > 0 && (
                    <div className="mt-2 border-t border-[#2a2a2a] pt-2">
                      {archiveResult.errors.map((err, i) => (
                        <p key={i} className="font-mono text-[10px] text-red-400">{err}</p>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </main>
  )
}
