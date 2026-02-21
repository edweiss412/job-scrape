import { Suspense } from 'react'
import { createClient, createServiceClient } from '@/lib/supabase/server'
import { RunSelector } from '@/components/jobs/RunSelector'
import { TriggerScanButton } from '@/components/admin/TriggerScanButton'
import { StatusBar } from '@/components/jobs/StatusBar'
import { FullTimeJobList } from '@/components/jobs/FullTimeJobList'
import { JobGridSkeleton } from '@/components/dashboard/skeletons'
import { isAdmin } from '@/lib/admin'
import { getRunsList } from '@/lib/cached-queries'
import { ProfileNudgeBanner } from '@/components/jobs/ProfileNudgeBanner'

interface Props {
  searchParams: Promise<{ run?: string }>
}

export default async function FullTimePage({ searchParams }: Props) {
  const { run } = await searchParams
  const supabase = await createClient()
  const svc = createServiceClient()

  // ── Session user ──────────────────────────────────────────────────────────
  const { data: { user } } = await supabase.auth.getUser()
  const userIsAdmin = isAdmin(user?.email)

  // ── Parallel data fetches (lightweight — header + status bar) ─────────────
  const ghToken = process.env.GH_PAT ?? process.env.GITHUB_TOKEN
  const ghOwner = process.env.GITHUB_REPO_OWNER
  const ghRepo = process.env.GITHUB_REPO_NAME

  const [runs, hasPrimaryResumeResult, evalCountResult, jobCountResult, evalStatusResult, scanStatusResult, unevaluatedResult] = await Promise.all([
    getRunsList(),
    // Check primary resume via service client (user_id scoped)
    user ? svc.from('resumes').select('id').eq('user_id', user.id).eq('is_primary', true).maybeSingle() : Promise.resolve({ data: null }),
    // Count user's evaluations (RLS auto-scopes)
    supabase.from('user_evaluations').select('id', { count: 'exact', head: true }),
    // Count total jobs in DB (exclude archived)
    supabase.from('jobs').select('job_id', { count: 'exact', head: true }).is('archived_at', null),
    // Check eval_status + last eval date + profile completeness
    user ? svc.from('user_profiles')
      .select('eval_status, eval_started_at, eval_completed_at, eval_job_count, eval_jobs_done, updated_at, target_roles, candidate_context')
      .eq('user_id', user.id)
      .maybeSingle()
      : Promise.resolve({ data: null }),
    // Check if a fulltime scan is currently running via GitHub API (cached 30s)
    (ghToken && ghOwner && ghRepo)
      ? fetch(
          `https://api.github.com/repos/${ghOwner}/${ghRepo}/actions/workflows/scrape.yml/runs?per_page=1&event=workflow_dispatch`,
          { headers: { Authorization: `Bearer ${ghToken}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' }, next: { revalidate: 30 } },
        ).then(r => r.ok ? r.json() : null).catch(() => null)
      : Promise.resolve(null),
    // Count unevaluated jobs (pre-filter passed, no user_evaluation for this user)
    user ? svc.rpc('count_unevaluated_jobs', { p_user_id: user.id }) : Promise.resolve({ data: null }),
  ])

  const hasPrimaryResume = !!hasPrimaryResumeResult.data
  const evalCount = evalCountResult.count ?? 0
  const totalJobCount = jobCountResult.count ?? 0
  const evalProfile = evalStatusResult.data
  const evalStatus = (evalProfile?.eval_status ?? 'idle') as 'idle' | 'pending' | 'running' | 'completed' | 'error'
  const latestScanRun = scanStatusResult?.workflow_runs?.[0]
  const scanIsActive = latestScanRun?.status === 'queued' || latestScanRun?.status === 'in_progress'
  const unevaluatedData = unevaluatedResult?.data as { count: number; latest_scrape: string | null } | null
  const unevaluatedCount = unevaluatedData?.count ?? 0
  const latestScrapeDate = unevaluatedData?.latest_scrape ?? null

  // Profile completeness nudge: show when user has evals but no target_roles and no candidate_context
  const hasTargetRoles = !!(evalProfile?.target_roles && (Array.isArray(evalProfile.target_roles) ? evalProfile.target_roles.length > 0 : true))
  const hasCandidateContext = !!(evalProfile?.candidate_context && String(evalProfile.candidate_context).trim().length > 0)
  const showProfileNudge = evalCount > 0 && !hasTargetRoles && !hasCandidateContext

  // Staleness: last evaluation older than 7 days?
  const lastEvalAt = evalProfile?.eval_completed_at ?? null
  const isStale = lastEvalAt
    ? (Date.now() - new Date(lastEvalAt).getTime()) > 7 * 24 * 60 * 60 * 1000
    : false

  // Determine whether to show StatusBar (only when user has resume and isn't in an empty state)
  const showNoResume = !hasPrimaryResume && evalCount === 0
  const showNoJobs = hasPrimaryResume && evalCount === 0 && totalJobCount === 0 && !scanIsActive
  const showStatusBar = hasPrimaryResume && !showNoResume && !showNoJobs

  return (
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
            {userIsAdmin && <RunSelector runs={runs} currentRun={run ?? null} />}
          </div>
        </div>
      </div>

      {/* Consolidated notification bar — handles eval progress, new jobs, and stale scores */}
      {showStatusBar && (
        <StatusBar
          unevaluatedCount={unevaluatedCount}
          latestScrapeDate={latestScrapeDate}
          isStale={isStale}
          lastEvalAt={lastEvalAt}
        />
      )}

      {/* Profile completeness nudge — only when no other banner is active */}
      {showProfileNudge && !isStale && unevaluatedCount === 0 && <ProfileNudgeBanner />}

      <Suspense fallback={<JobGridSkeleton />}>
        <FullTimeJobList
          run={run}
          evalCount={evalCount}
          hasPrimaryResume={hasPrimaryResume}
          totalJobCount={totalJobCount}
          scanIsActive={scanIsActive}
          evalStatus={evalStatus}
          latestScanRun={latestScanRun ? { html_url: latestScanRun.html_url } : null}
          userIsAdmin={userIsAdmin}
        />
      </Suspense>
    </main>
  )
}
