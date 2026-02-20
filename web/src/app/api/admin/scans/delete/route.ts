import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { createServiceClient } from '@/lib/supabase/server'
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

interface RunToDelete {
  id: number
  workflow: 'fulltime' | 'freelance' | 'evaluate'
  created_at: string
}

// POST /api/admin/scans/delete — delete workflow runs from GitHub + purge associated Supabase data
export async function POST(request: Request) {
  const user = await getAuthUser()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const token = process.env.GH_PAT
  const owner = process.env.GITHUB_REPO_OWNER
  const repo = process.env.GITHUB_REPO_NAME

  if (!token || !owner || !repo) {
    return NextResponse.json({ error: 'GitHub integration not configured' }, { status: 500 })
  }

  const body = await request.json()
  const { runs } = body as { runs: RunToDelete[] }

  if (!Array.isArray(runs) || runs.length === 0) {
    return NextResponse.json({ error: 'runs must be a non-empty array' }, { status: 400 })
  }

  const ghHeaders = {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  }

  // 1. Delete from GitHub Actions
  const ghResults = await Promise.allSettled(
    runs.map(async (run) => {
      const res = await fetch(
        `https://api.github.com/repos/${owner}/${repo}/actions/runs/${run.id}`,
        { method: 'DELETE', headers: ghHeaders },
      )
      if (!res.ok && res.status !== 204) {
        const text = await res.text()
        throw new Error(`Run ${run.id}: ${text}`)
      }
      return run.id
    }),
  )

  const deleted = ghResults
    .filter((r): r is PromiseFulfilledResult<number> => r.status === 'fulfilled')
    .map((r) => r.value)
  const ghErrors = ghResults
    .filter((r): r is PromiseRejectedResult => r.status === 'rejected')
    .map((r) => r.reason?.message ?? 'Unknown error')

  // 2. Purge associated Supabase data for successfully deleted runs
  const svc = createServiceClient()
  const supabaseErrors: string[] = []

  // Collect unique run_dates per workflow type
  const fulltimeDates = new Set<string>()
  const freelanceDates = new Set<string>()
  const deletedSet = new Set(deleted)

  for (const run of runs) {
    if (!deletedSet.has(run.id)) continue
    const runDate = run.created_at.slice(0, 10) // YYYY-MM-DD
    if (run.workflow === 'fulltime') fulltimeDates.add(runDate)
    if (run.workflow === 'freelance') freelanceDates.add(runDate)
    // evaluate runs: user_evaluations are per-user and shouldn't be bulk-deleted from admin
  }

  // Purge fulltime data: run_jobs → runs → orphaned user_evaluations → orphaned jobs
  for (const runDate of fulltimeDates) {
    try {
      // Find run IDs in Supabase — exact date first, then ±1 day for UTC/local edge cases
      let supaRuns: { id: number }[] | null = null
      let runsErr: { message: string } | null = null

      ;({ data: supaRuns, error: runsErr } = await svc
        .from('runs')
        .select('id')
        .eq('run_date', runDate))

      // Fallback: try adjacent dates only if exact match found nothing
      if (!runsErr && !supaRuns?.length) {
        const d = new Date(runDate + 'T12:00:00Z')
        const prev = new Date(d.getTime() - 86_400_000).toISOString().slice(0, 10)
        const next = new Date(d.getTime() + 86_400_000).toISOString().slice(0, 10)
        ;({ data: supaRuns, error: runsErr } = await svc
          .from('runs')
          .select('id')
          .in('run_date', [prev, next]))
      }

      if (runsErr) {
        supabaseErrors.push(`fulltime ${runDate}: runs lookup: ${runsErr.message}`)
        continue
      }
      if (!supaRuns?.length) continue

      const supaRunIds = supaRuns.map((r) => r.id)

      // Collect job_ids belonging to these runs before deletion
      const { data: rjData } = await svc
        .from('run_jobs')
        .select('job_id')
        .in('run_id', supaRunIds)
      const affectedJobIds = [...new Set((rjData ?? []).map((rj: { job_id: string }) => rj.job_id))]

      // Delete run_jobs first (FK → runs, FK → jobs)
      const { error: rjErr } = await svc.from('run_jobs').delete().in('run_id', supaRunIds)
      if (rjErr) supabaseErrors.push(`fulltime ${runDate}: run_jobs: ${rjErr.message}`)

      // Delete runs
      const { error: runDelErr } = await svc.from('runs').delete().in('id', supaRunIds)
      if (runDelErr) supabaseErrors.push(`fulltime ${runDate}: runs: ${runDelErr.message}`)

      // Clean up orphaned jobs (no remaining run_jobs reference)
      if (affectedJobIds.length > 0) {
        const { data: survivingRefs } = await svc
          .from('run_jobs')
          .select('job_id')
          .in('job_id', affectedJobIds)
        const surviving = new Set((survivingRefs ?? []).map((r: { job_id: string }) => r.job_id))
        const orphaned = affectedJobIds.filter((id) => !surviving.has(id))

        // Batch delete: user_evaluations then jobs (user_evaluations FK → jobs has CASCADE,
        // but be explicit so partial failures don't leave stale eval data)
        const BATCH = 100
        for (let i = 0; i < orphaned.length; i += BATCH) {
          const batch = orphaned.slice(i, i + BATCH)
          await svc.from('user_evaluations').delete().in('job_id', batch)
          await svc.from('jobs').delete().in('job_id', batch)
        }
      }
    } catch (e) {
      supabaseErrors.push(`fulltime ${runDate}: ${e instanceof Error ? e.message : 'unknown'}`)
    }
  }

  // Purge freelance data
  for (const runDate of freelanceDates) {
    try {
      await svc.from('freelance_companies').delete().eq('first_seen_date', runDate)
    } catch (e) {
      supabaseErrors.push(`freelance ${runDate}: ${e instanceof Error ? e.message : 'unknown'}`)
    }
  }

  return NextResponse.json({
    deleted,
    errors: [...ghErrors, ...supabaseErrors],
  })
}
