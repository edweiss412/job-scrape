import { createServerClient } from '@supabase/ssr'
import { createServiceClient } from '@/lib/supabase/server'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'

async function getUser() {
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

// POST /api/scan/evaluate — dispatch on-demand evaluation for the current user
export async function POST() {
  const user = await getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const svc = createServiceClient()

  // Check user has a primary resume before dispatching
  const { data: resume } = await svc
    .from('resumes')
    .select('id')
    .eq('user_id', user.id)
    .eq('is_primary', true)
    .maybeSingle()

  if (!resume) {
    return NextResponse.json(
      { error: 'No primary resume found. Upload and set a resume as primary first.' },
      { status: 422 },
    )
  }

  // Check not already running
  const { data: profile } = await svc
    .from('user_profiles')
    .select('eval_status, eval_started_at')
    .eq('user_id', user.id)
    .maybeSingle()

  // Staleness guard: if pending/running for too long, the GH Actions runner likely died.
  // Auto-reset so the user can re-trigger.
  if ((profile?.eval_status === 'pending' || profile?.eval_status === 'running') && profile?.eval_started_at) {
    const elapsed = Date.now() - new Date(profile.eval_started_at).getTime()
    const staleThreshold = profile.eval_status === 'pending' ? 5 * 60 * 1000 : 35 * 60 * 1000
    if (elapsed > staleThreshold) {
      await svc.from('user_profiles').update({ eval_status: 'idle' }).eq('user_id', user.id)
      // Fall through to allow re-trigger
    } else {
      return NextResponse.json({ error: 'Evaluation already in progress' }, { status: 409 })
    }
  }

  // Mark as pending + reset cancellation signal
  await svc
    .from('user_profiles')
    .upsert({
      user_id: user.id,
      eval_status: 'pending',
      eval_cancel_requested_at: null,
    }, { onConflict: 'user_id' })

  // Dispatch GitHub Actions workflow
  const token = process.env.GH_PAT
  const owner = process.env.GITHUB_REPO_OWNER
  const repo = process.env.GITHUB_REPO_NAME

  if (!token || !owner || !repo) {
    // Reset status and error out
    await svc
      .from('user_profiles')
      .update({ eval_status: 'error' })
      .eq('user_id', user.id)
    return NextResponse.json({ error: 'GitHub integration not configured' }, { status: 500 })
  }

  const res = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/actions/workflows/evaluate_for_user.yml/dispatches`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
      body: JSON.stringify({ ref: 'main', inputs: { user_id: user.id } }),
    },
  )

  if (!res.ok) {
    const text = await res.text()
    await svc.from('user_profiles').update({ eval_status: 'error' }).eq('user_id', user.id)
    return NextResponse.json({ error: `GitHub API error: ${text}` }, { status: 502 })
  }

  return NextResponse.json({ ok: true, status: 'pending' }, { status: 202 })
}

// GET /api/scan/evaluate — poll evaluation status for the current user
export async function GET() {
  const user = await getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const svc = createServiceClient()
  const { data: profile } = await svc
    .from('user_profiles')
    .select('eval_status, eval_started_at, eval_completed_at, eval_job_count, eval_jobs_done')
    .eq('user_id', user.id)
    .maybeSingle()

  let status = profile?.eval_status ?? 'idle'

  // Staleness guard: if 'running' or 'pending' for over 35 min, the GH Actions runner
  // was likely killed by timeout (30min). Auto-reset to error so the UI isn't stuck.
  if ((status === 'running' || status === 'pending') && profile?.eval_started_at) {
    const elapsed = Date.now() - new Date(profile.eval_started_at).getTime()
    if (elapsed > 35 * 60 * 1000) {
      await svc.from('user_profiles').update({
        eval_status: 'error',
        eval_completed_at: new Date().toISOString(),
      }).eq('user_id', user.id)
      status = 'error'
    }
  }

  return NextResponse.json({
    status,
    started_at: profile?.eval_started_at ?? null,
    completed_at: profile?.eval_completed_at ?? null,
    job_count: profile?.eval_job_count ?? null,
    jobs_done: profile?.eval_jobs_done ?? null,
  })
}
