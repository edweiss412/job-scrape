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

  if (!token || !owner || !repo) {
    return NextResponse.json({ error: 'GitHub integration not configured' }, { status: 500 })
  }

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
        }
      })
    }),
  )

  const allRuns = results
    .flatMap((r) => (r.status === 'fulfilled' ? r.value : []))
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())

  // Piggyback current scrape stage for today's run (if active)
  let scrapeStage: { run_date: string; current_stage: string | null } | null = null
  try {
    const { createServiceClient } = await import('@/lib/supabase/server')
    const svc = createServiceClient()
    const today = new Date().toISOString().split('T')[0]
    const { data } = await svc
      .from('scrape_runs')
      .select('run_date, current_stage')
      .eq('run_date', today)
      .maybeSingle()
    if (data?.current_stage && data.current_stage !== 'complete') {
      scrapeStage = data
    }
  } catch { /* non-critical */ }

  return NextResponse.json({ runs: allRuns, scrapeStage })
}
