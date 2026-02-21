import { createServerClient } from '@supabase/ssr'
import { createServiceClient } from '@/lib/supabase/server'
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

// POST /api/admin/scans/cancel — cancel a workflow run with optional DB cleanup
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
  const { run_id, workflow_type, user_id } = body

  if (!run_id || typeof run_id !== 'number') {
    return NextResponse.json({ error: 'run_id is required' }, { status: 400 })
  }

  // Cancel the GH workflow run
  const res = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/actions/runs/${run_id}/cancel`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
    },
  )

  if (!res.ok) {
    const text = await res.text()
    return NextResponse.json({ error: `GitHub API error: ${text}` }, { status: 502 })
  }

  // DB cleanup based on workflow type
  const svc = createServiceClient()

  if (workflow_type === 'evaluate' && user_id) {
    await svc
      .from('user_profiles')
      .update({
        eval_status: 'cancelled',
        eval_cancel_requested_at: new Date().toISOString(),
        eval_completed_at: new Date().toISOString(),
      })
      .eq('user_id', user_id)
  } else if (workflow_type === 'fulltime') {
    const today = new Date().toISOString().slice(0, 10)
    await svc
      .from('scrape_runs')
      .update({ current_stage: 'cancelled' })
      .eq('run_date', today)
  }

  return NextResponse.json({ ok: true })
}
