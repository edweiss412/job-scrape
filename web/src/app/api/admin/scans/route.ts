import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { ADMIN_EMAIL } from '@/lib/admin'

async function getAuthUser() {
  const cookieStore = await cookies()
  const authClient = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() { return cookieStore.getAll() },
        setAll(cookiesToSet: { name: string; value: string; options?: object }[]) {
          cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options))
        },
      },
    },
  )
  const { data: { user } } = await authClient.auth.getUser()
  return user
}

interface GHWorkflowRun {
  id: number
  status: string
  conclusion: string | null
  event: string
  created_at: string
  run_started_at: string | null
  updated_at: string
  html_url: string
  actor: { login: string; avatar_url: string } | null
}

// GET /api/admin/scans — list recent workflow runs across all 3 workflows
export async function GET() {
  const user = await getAuthUser()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const token = process.env.GH_PAT
  const owner = process.env.GITHUB_REPO_OWNER
  const repo = process.env.GITHUB_REPO_NAME

  // Fetch GitHub workflow runs (non-blocking if not configured)
  let allRuns: {
    id: number
    workflow: string
    status: string
    conclusion: string | null
    event: string
    created_at: string
    run_started_at: string
    updated_at: string
    html_url: string
    duration_seconds: number | null
    actor: string | null
    source?: string
  }[] = []

  if (token && owner && repo) {
    const headers = {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    }

    const workflows: { file: string; tag: 'fulltime' | 'freelance' | 'evaluate' }[] = [
      { file: 'scrape.yml', tag: 'fulltime' },
      { file: 'freelance.yml', tag: 'freelance' },
      { file: 'evaluate_for_user.yml', tag: 'evaluate' },
    ]

    const results = await Promise.allSettled(
      workflows.map(async (w) => {
        const res = await fetch(
          `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${w.file}/runs?per_page=5`,
          { headers },
        )
        if (!res.ok) return []
        const data = await res.json()
        const runs: GHWorkflowRun[] = data.workflow_runs ?? []
        return runs.map((r) => {
          const startedAt = r.run_started_at ?? r.created_at
          const updatedAt = r.updated_at
          const durationSeconds =
            r.status === 'completed'
              ? Math.round((new Date(updatedAt).getTime() - new Date(startedAt).getTime()) / 1000)
              : null
          return {
            id: r.id,
            workflow: w.tag,
            status: r.status,
            conclusion: r.conclusion,
            event: r.event,
            created_at: r.created_at,
            run_started_at: startedAt,
            updated_at: updatedAt,
            html_url: r.html_url,
            duration_seconds: durationSeconds,
            actor: r.actor?.login ?? null,
            source: 'github' as const,
          }
        })
      }),
    )

    allRuns = results
      .flatMap((r) => (r.status === 'fulfilled' ? r.value : []))
  }

  // Also fetch recent scrape_runs from Supabase to cover non-GH-Actions runs
  let scrapeStage: { run_date: string; current_stage: string | null } | null = null
  let scrapeRuns: Record<string, unknown>[] = []
  let jobStats: { total_jobs: number; passed_prefilter: number; active_jobs: number; expired_jobs: number } | null = null

  try {
    const { createServiceClient } = await import('@/lib/supabase/server')
    const svc = createServiceClient()

    const { data: scrapeRows } = await svc
      .from('scrape_runs')
      .select('run_date, total_scraped, new_jobs, sources, current_stage, created_at, pre_filter_stats, expired_checked, expired_found')
      .order('run_date', { ascending: false })
      .limit(20)

    if (scrapeRows) {
      scrapeRuns = scrapeRows

      // Dates already covered by a GH fulltime run (by matching date)
      const ghFulltimeDates = new Set(
        allRuns
          .filter((r) => r.workflow === 'fulltime')
          .map((r) => r.created_at.split('T')[0]),
      )

      // Check if the latest fulltime GH run is done (completed/cancelled)
      const latestFulltime = allRuns.find((r) => r.workflow === 'fulltime')
      const ghFulltimeDone = latestFulltime?.status === 'completed'

      for (const row of scrapeRows) {
        // Piggyback active stage for today
        const today = new Date().toISOString().split('T')[0]
        if (row.run_date === today && row.current_stage && row.current_stage !== 'complete') {
          // If the GH workflow already finished (completed/cancelled/failed) but
          // current_stage is still active, the pipeline was killed mid-run.
          // Mark it as cancelled so the stepper doesn't get stuck.
          if (ghFulltimeDone) {
            scrapeStage = { run_date: row.run_date, current_stage: 'cancelled' }
            // Also fix the DB so it doesn't stay stale
            svc.from('scrape_runs')
              .update({ current_stage: 'cancelled' })
              .eq('run_date', row.run_date)
              .then(() => {})
          } else {
            scrapeStage = { run_date: row.run_date, current_stage: row.current_stage }
          }
        }

        // Synthesize a virtual run entry if no GH run covers this date
        if (!ghFulltimeDates.has(row.run_date)) {
          const isActive = row.current_stage != null && row.current_stage !== 'complete'
          const createdAt = row.created_at ?? `${row.run_date}T00:00:00Z`
          allRuns.push({
            id: -new Date(row.run_date).getTime(), // negative ID to avoid collision with GH IDs
            workflow: 'fulltime',
            status: isActive ? 'in_progress' : 'completed',
            conclusion: isActive ? null : 'success',
            event: 'local',
            created_at: createdAt,
            run_started_at: createdAt,
            updated_at: createdAt,
            html_url: '',
            duration_seconds: null,
            actor: 'local',
            source: 'supabase',
          })
        }
      }
    }

    // Aggregate job stats
    const { count: totalJobs } = await svc
      .from('jobs')
      .select('*', { count: 'exact', head: true })
      .is('archived_at', null)

    const { count: passedPrefilter } = await svc
      .from('jobs')
      .select('*', { count: 'exact', head: true })
      .is('archived_at', null)
      .eq('pre_filter_passed', true)

    const { count: activeJobs } = await svc
      .from('jobs')
      .select('*', { count: 'exact', head: true })
      .is('archived_at', null)
      .eq('listing_status', 'active')

    const { count: expiredJobs } = await svc
      .from('jobs')
      .select('*', { count: 'exact', head: true })
      .is('archived_at', null)
      .eq('listing_status', 'expired')

    jobStats = {
      total_jobs: totalJobs ?? 0,
      passed_prefilter: passedPrefilter ?? 0,
      active_jobs: activeJobs ?? 0,
      expired_jobs: expiredJobs ?? 0,
    }
  } catch { /* non-critical */ }

  allRuns.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())

  return NextResponse.json({ runs: allRuns, scrapeStage, scrapeRuns, jobStats })
}
