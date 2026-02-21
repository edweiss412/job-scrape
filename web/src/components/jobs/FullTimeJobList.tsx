import { createClient } from '@/lib/supabase/server'
import { JobGrid } from '@/components/jobs/JobGrid'
import { LiveJobGridWrapper } from '@/components/jobs/LiveJobGridWrapper'
import { EvaluateForUserButton } from '@/components/jobs/EvaluateForUserButton'
import { TriggerScanButton } from '@/components/admin/TriggerScanButton'
import { JobWithRunMeta } from '@/lib/types'
import { isAdmin } from '@/lib/admin'
import Link from 'next/link'

interface FullTimeJobListProps {
  run: string | undefined
  evalCount: number
  hasPrimaryResume: boolean
  totalJobCount: number
  scanIsActive: boolean
  evalStatus: string
  latestScanRun: { html_url?: string } | null
  userIsAdmin: boolean
}

export async function FullTimeJobList({
  run,
  evalCount,
  hasPrimaryResume,
  totalJobCount,
  scanIsActive,
  evalStatus,
  latestScanRun,
  userIsAdmin,
}: FullTimeJobListProps) {
  const supabase = await createClient()

  const showEvalInProgress = evalStatus === 'pending' || evalStatus === 'running'

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
            salary, date_posted, tier, first_seen_date, last_seen_date, archived_at,
            user_evaluations(match_score, match_verdict, match_reasoning, job_summary, full_evaluation, deep_evaluation)
          )
        `)
        .eq('run_id', runRecord.id)

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      jobs = (runJobs ?? [] as any[])
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .filter((rj: any) => rj.jobs !== null && rj.jobs.archived_at === null)
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
        jobs(job_id, title, company, location, url, source, salary, date_posted, tier, first_seen_date, last_seen_date, archived_at)
      `)
      .not('match_verdict', 'is', null)
      .order('match_score', { ascending: false })

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    jobs = (data ?? [] as any[]).filter((row: any) => row.jobs?.archived_at === null).map((row: any) => ({
      ...row.jobs,
      match_score: row.match_score,
      match_verdict: row.match_verdict,
      match_reasoning: row.match_reasoning,
      job_summary: row.job_summary,
      full_evaluation: row.full_evaluation,
      deep_evaluation: row.deep_evaluation,
    }))
  }

  // Empty state derivation
  const showNoResume = !hasPrimaryResume && evalCount === 0
  const showScanRunning = hasPrimaryResume && evalCount === 0 && totalJobCount === 0 && scanIsActive
  const showNoJobs = hasPrimaryResume && evalCount === 0 && totalJobCount === 0 && !scanIsActive && evalStatus !== 'pending' && evalStatus !== 'running'
  const showNoEvals = hasPrimaryResume && evalCount === 0 && totalJobCount > 0 && evalStatus !== 'pending' && evalStatus !== 'running'

  return (
    <LiveJobGridWrapper scanIsActive={scanIsActive} evalIsActive={showEvalInProgress}>
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

      {/* Empty state: scan is running, no jobs yet */}
      {showScanRunning && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-zinc-800 bg-zinc-900/20 py-20 text-center">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-amber-900/40 bg-amber-950/20">
            <span className="relative flex h-3 w-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-500 opacity-40" />
              <span className="relative inline-flex h-3 w-3 rounded-full bg-amber-500" />
            </span>
          </div>
          <h2 className="mb-1 text-sm font-semibold text-white">Scan in progress</h2>
          <p className="mb-6 max-w-sm text-xs text-zinc-600">
            A fulltime job scan is currently running. Jobs will appear here as they are evaluated.
          </p>
          {latestScanRun?.html_url && (
            <a
              href={latestScanRun.html_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/50 px-5 py-2.5 text-xs font-medium text-zinc-400 transition-all hover:bg-zinc-900 hover:text-zinc-300"
            >
              View scan logs ↗
            </a>
          )}
        </div>
      )}

      {/* Empty state: no jobs scraped yet */}
      {showNoJobs && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-zinc-800 bg-zinc-900/20 py-20 text-center">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-zinc-800 bg-zinc-900">
            <svg className="h-5 w-5 text-zinc-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
          <h2 className="mb-1 text-sm font-semibold text-white">No jobs scraped yet</h2>
          {userIsAdmin ? (
            <>
              <p className="mb-6 max-w-sm text-xs text-zinc-600">
                Run a scan first to discover job listings, then evaluate them against your resume.
              </p>
              <TriggerScanButton type="fulltime" />
              <p className="mt-4 text-xs text-zinc-700">
                Scans run automatically every Monday and Thursday, or trigger one now.
              </p>
            </>
          ) : (
            <p className="mt-2 max-w-sm text-xs text-zinc-600">
              Job listings are scraped automatically every Monday and Thursday. Check back soon.
            </p>
          )}
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
          <EvaluateForUserButton />
          <p className="mt-4 text-xs text-zinc-700">
            New jobs are scraped automatically every Monday and Thursday.
          </p>
        </div>
      )}

      {/* Normal job grid */}
      {!showNoResume && !showScanRunning && !showNoJobs && !showNoEvals && (
        <JobGrid jobs={jobs} newJobIds={newJobIds} />
      )}
    </LiveJobGridWrapper>
  )
}
