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

  // Purge fulltime data: run_jobs → runs (jobs are shared across runs, keep them)
  for (const runDate of fulltimeDates) {
    try {
      // Find run IDs in Supabase for this date
      const { data: supaRuns } = await svc
        .from('runs')
        .select('id')
        .eq('run_date', runDate)

      if (supaRuns?.length) {
        const supaRunIds = supaRuns.map((r) => r.id)
        // Delete run_jobs first (FK)
        await svc.from('run_jobs').delete().in('run_id', supaRunIds)
        // Delete runs
        await svc.from('runs').delete().in('id', supaRunIds)
      }
    } catch (e) {
      supabaseErrors.push(`fulltime ${runDate}: ${e instanceof Error ? e.message : 'unknown'}`)
    }
  }

  // Purge freelance data
  for (const runDate of freelanceDates) {
    try {
      await svc.from('freelance_companies').delete().eq('run_date', runDate)
    } catch (e) {
      supabaseErrors.push(`freelance ${runDate}: ${e instanceof Error ? e.message : 'unknown'}`)
    }
  }

  return NextResponse.json({
    deleted,
    errors: [...ghErrors, ...supabaseErrors],
  })
}
