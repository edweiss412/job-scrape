import { createClient, createServiceClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { JobGrid } from '@/components/jobs/JobGrid'
import { RunSelector } from '@/components/jobs/RunSelector'
import { TriggerScanButton } from '@/components/admin/TriggerScanButton'
import { EvaluateForUserButton } from '@/components/jobs/EvaluateForUserButton'
import { JobWithRunMeta } from '@/lib/types'
import Link from 'next/link'

interface Props {
  searchParams: Promise<{ run?: string }>
}

export default async function FullTimePage({ searchParams }: Props) {
  const { run } = await searchParams
  const supabase = await createClient()
  const svc = createServiceClient()

  // ── Session user ──────────────────────────────────────────────────────────
  const { data: { user } } = await supabase.auth.getUser()

  // ── Parallel data fetches ─────────────────────────────────────────────────
  const [runsResult, hasPrimaryResumeResult, evalCountResult, evalStatusResult] = await Promise.all([
    supabase.from('runs').select('run_date, total_jobs').order('run_date', { ascending: false }),
    // Check primary resume via service client (user_id scoped)
    user ? svc.from('resumes').select('id').eq('user_id', user.id).eq('is_primary', true).maybeSingle() : Promise.resolve({ data: null }),
    // Count user's evaluations (RLS auto-scopes)
    supabase.from('user_evaluations').select('id', { count: 'exact', head: true }),
    // Check eval_status + last eval date
    user ? svc.from('user_profiles')
      .select('eval_status, eval_started_at, eval_completed_at, eval_job_count, eval_jobs_done, updated_at')
      .eq('user_id', user.id)
      .maybeSingle()
      : Promise.resolve({ data: null }),
  ])

  const runs = runsResult.data ?? []
  const hasPrimaryResume = !!hasPrimaryResumeResult.data
  const evalCount = evalCountResult.count ?? 0
  const evalProfile = evalStatusResult.data
  const evalStatus = (evalProfile?.eval_status ?? 'idle') as 'idle' | 'pending' | 'running' | 'completed' | 'error'

  // Staleness: last evaluation older than 7 days?
  const lastEvalAt = evalProfile?.eval_completed_at ?? null
  const isStale = lastEvalAt
    ? (Date.now() - new Date(lastEvalAt).getTime()) > 7 * 24 * 60 * 60 * 1000
    : false

  let jobs: JobWithRunMeta[] = []
  let newJobIds: Set<string> = new Set()

  if (run) {
    const { data: runRecord } = await supabase
      .from('runs')
      .select('*')
      .eq('run_date', run)
      .single()

    if (runRecord) {
      const { data: runJobs } = await supabase
        .from('run_jobs')
        .select(`
          is_new_this_run,
          jobs(
            job_id, title, company, location, url, source,
            salary, date_posted, tier, first_seen_date, last_seen_date,
            user_evaluations(match_score, match_verdict, match_reasoning, job_summary, full_evaluation, deep_evaluation)
          )
        `)
        .eq('run_id', runRecord.id)

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      jobs = (runJobs ?? [] as any[])
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .filter((rj: any) => rj.jobs !== null)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .map((rj: any) => {
          const evalRow = Array.isArray(rj.jobs.user_evaluations)
            ? rj.jobs.user_evaluations[0] ?? {}
            : rj.jobs.user_evaluations ?? {}
          return {
            ...rj.jobs,
            ...evalRow,
            user_evaluations: undefined,
            is_new_this_run: rj.is_new_this_run,
          }
        })
        .sort((a: JobWithRunMeta, b: JobWithRunMeta) => (b.match_score ?? 0) - (a.match_score ?? 0))

      newJobIds = new Set<string>((runRecord.new_job_ids ?? []) as string[])
    }
  } else if (evalCount > 0) {
    const { data } = await supabase
      .from('user_evaluations')
      .select(`
        match_score, match_verdict, match_reasoning, job_summary, full_evaluation, deep_evaluation,
        jobs(job_id, title, company, location, url, source, salary, date_posted, tier, first_seen_date, last_seen_date)
      `)
      .not('match_verdict', 'is', null)
      .order('match_score', { ascending: false })

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    jobs = (data ?? [] as any[]).map((row: any) => ({
      ...row.jobs,
      match_score: row.match_score,
      match_verdict: row.match_verdict,
      match_reasoning: row.match_reasoning,
      job_summary: row.job_summary,
      full_evaluation: row.full_evaluation,
      deep_evaluation: row.deep_evaluation,
    }))
  }

  // ── Empty state derivation ────────────────────────────────────────────────
  const showNoResume = !hasPrimaryResume && evalCount === 0
  const showNoEvals = hasPrimaryResume && evalCount === 0 && evalStatus !== 'pending' && evalStatus !== 'running'
  const showEvalInProgress = evalStatus === 'pending' || evalStatus === 'running'

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-7xl px-4 py-5 sm:py-8">

        {/* Page header */}
        <div className="mb-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h1
              className="text-xl font-bold text-white"
              style={{ fontFamily: 'Syne, sans-serif' }}
            >
              Full Time
            </h1>
            <div className="flex items-center gap-2">
              <TriggerScanButton type="fulltime" />
              <RunSelector runs={runs} currentRun={run ?? null} />
            </div>
          </div>
        </div>

        {/* Staleness banner — show only when user has evals but they're old */}
        {!showNoResume && !showNoEvals && !showEvalInProgress && isStale && (
          <div className="mb-5 flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 px-4 py-3">
            <svg className="h-4 w-4 shrink-0 text-zinc-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p className="text-xs text-zinc-500">
              Your last evaluation was{' '}
              <span className="text-zinc-400">
                {lastEvalAt ? new Date(lastEvalAt).toLocaleDateString() : 'a while ago'}
              </span>
              . Re-evaluate to score new jobs added since then.
            </p>
            <div className="ml-auto shrink-0">
              <EvaluateForUserButton initialStatus="idle" />
            </div>
          </div>
        )}

        {/* Evaluation in-progress banner */}
        {showEvalInProgress && (
          <div className="mb-5">
            <EvaluateForUserButton
              initialStatus={evalStatus as 'pending' | 'running'}
              jobCount={evalProfile?.eval_job_count ?? null}
              jobsDone={evalProfile?.eval_jobs_done ?? null}
              evalStartedAt={evalProfile?.eval_started_at ?? null}
            />
          </div>
        )}

        {/* Empty state: no resume */}
        {showNoResume && (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-zinc-800 bg-zinc-900/20 py-20 text-center">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-zinc-800 bg-zinc-900">
              <svg className="h-5 w-5 text-zinc-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <h2 className="mb-1 text-sm font-semibold text-white">Upload a resume to get started</h2>
            <p className="mb-6 max-w-xs text-xs text-zinc-600">
              Jobs are evaluated against your resume using AI. Upload yours to see personalised match scores.
            </p>
            <Link
              href="/profile"
              className="inline-flex items-center gap-2 rounded-lg border border-emerald-900/40 bg-emerald-950/20 px-5 py-2.5 text-xs font-medium text-emerald-400 transition-all hover:bg-emerald-950/40"
            >
              Go to Profile →
            </Link>
          </div>
        )}

        {/* Empty state: has resume, no evals yet */}
        {showNoEvals && (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-zinc-800 bg-zinc-900/20 py-20 text-center">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-zinc-800 bg-zinc-900">
              <svg className="h-5 w-5 text-zinc-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
              </svg>
            </div>
            <h2 className="mb-1 text-sm font-semibold text-white">No evaluations yet</h2>
            <p className="mb-6 max-w-sm text-xs text-zinc-600">
              Your resume is ready. Score the last 60 days of job listings against it now — no need to wait for the next scheduled scan.
            </p>
            <EvaluateForUserButton initialStatus="idle" />
            <p className="mt-4 text-xs text-zinc-700">
              New jobs are scraped automatically every Monday and Thursday.
            </p>
          </div>
        )}

        {/* Normal job grid */}
        {!showNoResume && !showNoEvals && (
          <JobGrid jobs={jobs} newJobIds={newJobIds} />
        )}
      </main>
    </div>
  )
}
