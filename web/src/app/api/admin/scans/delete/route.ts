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
  source?: 'github' | 'supabase'
}

// POST /api/admin/scans/delete — delete or archive workflow runs from GitHub + associated Supabase data
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
  const { runs, dates, action = 'delete' } = body as {
    runs?: RunToDelete[]
    dates?: string[]
    action?: 'archive' | 'delete'
  }

  // Date-based deletion: skip GH entirely, just clean Supabase data by date
  if (Array.isArray(dates) && dates.length > 0) {
    const svc = createServiceClient()
    const supabaseErrors: string[] = []

    for (const runDate of dates) {
      try {
        // Delete scrape_runs metadata
        const { error: scrapeRunErr } = await svc.from('scrape_runs').delete().eq('run_date', runDate)
        if (scrapeRunErr) supabaseErrors.push(`${runDate}: scrape_runs: ${scrapeRunErr.message}`)

        // Delete runs + run_jobs metadata
        const { data: supaRuns } = await svc.from('runs').select('id').eq('run_date', runDate)
        if (supaRuns?.length) {
          const supaRunIds = supaRuns.map((r) => r.id)
          await svc.from('run_jobs').delete().in('run_id', supaRunIds)
          await svc.from('runs').delete().in('id', supaRunIds)
        }

        // Find jobs first seen on this date
        const { data: jobRows } = await svc
          .from('jobs')
          .select('job_id')
          .eq('first_seen_date', runDate)

        if (jobRows?.length) {
          const jobIds = jobRows.map((j: { job_id: string }) => j.job_id)
          const BATCH = 100

          if (action === 'archive') {
            for (let i = 0; i < jobIds.length; i += BATCH) {
              const batch = jobIds.slice(i, i + BATCH)
              const { error } = await svc.from('jobs').update({ archived_at: new Date().toISOString() }).in('job_id', batch)
              if (error) supabaseErrors.push(`${runDate}: archive jobs: ${error.message}`)
            }
          } else {
            for (let i = 0; i < jobIds.length; i += BATCH) {
              const batch = jobIds.slice(i, i + BATCH)
              await svc.from('user_evaluations').delete().in('job_id', batch)
              await svc.from('jobs').delete().in('job_id', batch)
            }
          }
        }
      } catch (e) {
        supabaseErrors.push(`${runDate}: ${e instanceof Error ? e.message : 'unknown'}`)
      }
    }

    return NextResponse.json({ deleted: [], deletedDates: dates, action, errors: supabaseErrors })
  }

  if (!Array.isArray(runs) || runs.length === 0) {
    return NextResponse.json({ error: 'runs or dates must be a non-empty array' }, { status: 400 })
  }

  const ghHeaders = {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  }

  // Separate runs by source: GitHub runs need GH API delete, Supabase-only runs skip it
  const ghRuns = runs.filter((r) => r.source !== 'supabase')
  const supabaseOnlyRuns = runs.filter((r) => r.source === 'supabase')

  // 1. Delete GitHub Actions runs
  const ghResults = await Promise.allSettled(
    ghRuns.map(async (run) => {
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

  const deleted = [
    ...ghResults
      .filter((r): r is PromiseFulfilledResult<number> => r.status === 'fulfilled')
      .map((r) => r.value),
    // Supabase-only runs are always "deleted" (no GH to clean up)
    ...supabaseOnlyRuns.map((r) => r.id),
  ]
  const ghErrors = ghResults
    .filter((r): r is PromiseRejectedResult => r.status === 'rejected')
    .map((r) => r.reason?.message ?? 'Unknown error')

  // 2. Handle associated Supabase data for successfully deleted runs
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

  // Handle fulltime data
  for (const runDate of fulltimeDates) {
    try {
      // Always hard-delete lightweight metadata: scrape_runs, runs, run_jobs
      const { error: scrapeRunErr } = await svc.from('scrape_runs').delete().eq('run_date', runDate)
      if (scrapeRunErr) supabaseErrors.push(`fulltime ${runDate}: scrape_runs: ${scrapeRunErr.message}`)

      const { data: supaRuns } = await svc.from('runs').select('id').eq('run_date', runDate)
      if (supaRuns?.length) {
        const supaRunIds = supaRuns.map((r) => r.id)
        const { error: rjErr } = await svc.from('run_jobs').delete().in('run_id', supaRunIds)
        if (rjErr) supabaseErrors.push(`fulltime ${runDate}: run_jobs: ${rjErr.message}`)
        const { error: runDelErr } = await svc.from('runs').delete().in('id', supaRunIds)
        if (runDelErr) supabaseErrors.push(`fulltime ${runDate}: runs: ${runDelErr.message}`)
      }

      // Find all jobs first seen on this date
      const { data: jobRows, error: jobLookupErr } = await svc
        .from('jobs')
        .select('job_id')
        .eq('first_seen_date', runDate)
      if (jobLookupErr) {
        supabaseErrors.push(`fulltime ${runDate}: jobs lookup: ${jobLookupErr.message}`)
        continue
      }
      if (!jobRows?.length) continue

      const jobIds = jobRows.map((j: { job_id: string }) => j.job_id)

      if (action === 'archive') {
        // Archive: set archived_at on jobs, leave user_evaluations intact
        const BATCH = 100
        for (let i = 0; i < jobIds.length; i += BATCH) {
          const batch = jobIds.slice(i, i + BATCH)
          const { error } = await svc.from('jobs').update({ archived_at: new Date().toISOString() }).in('job_id', batch)
          if (error) supabaseErrors.push(`fulltime ${runDate}: archive jobs: ${error.message}`)
        }
      } else {
        // Delete: remove user_evaluations then jobs
        const BATCH = 100
        for (let i = 0; i < jobIds.length; i += BATCH) {
          const batch = jobIds.slice(i, i + BATCH)
          await svc.from('user_evaluations').delete().in('job_id', batch)
          await svc.from('jobs').delete().in('job_id', batch)
        }
      }
    } catch (e) {
      supabaseErrors.push(`fulltime ${runDate}: ${e instanceof Error ? e.message : 'unknown'}`)
    }
  }

  // Handle freelance data
  for (const runDate of freelanceDates) {
    try {
      if (action === 'archive') {
        // Archive: set archived_at on freelance_companies, leave user_freelance_evaluations intact
        const { error } = await svc.from('freelance_companies').update({ archived_at: new Date().toISOString() }).eq('first_seen_date', runDate)
        if (error) supabaseErrors.push(`freelance ${runDate}: archive: ${error.message}`)
      } else {
        // Delete: remove user_freelance_evaluations then freelance_companies
        const { data: companyRows } = await svc
          .from('freelance_companies')
          .select('company_id')
          .eq('first_seen_date', runDate)

        if (companyRows?.length) {
          const companyIds = companyRows.map((c: { company_id: string }) => c.company_id)
          const BATCH = 100
          for (let i = 0; i < companyIds.length; i += BATCH) {
            const batch = companyIds.slice(i, i + BATCH)
            await svc.from('user_freelance_evaluations').delete().in('company_id', batch)
          }
        }

        await svc.from('freelance_companies').delete().eq('first_seen_date', runDate)
      }
    } catch (e) {
      supabaseErrors.push(`freelance ${runDate}: ${e instanceof Error ? e.message : 'unknown'}`)
    }
  }

  return NextResponse.json({
    deleted,
    action,
    errors: [...ghErrors, ...supabaseErrors],
  })
}
