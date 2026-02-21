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

// POST /api/scan/evaluate/cancel — cancel an in-progress evaluation for the current user
export async function POST() {
  const user = await getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const svc = createServiceClient()

  // Only cancel if currently running or pending
  const { data: profile } = await svc
    .from('user_profiles')
    .select('eval_status')
    .eq('user_id', user.id)
    .maybeSingle()

  if (!profile || (profile.eval_status !== 'running' && profile.eval_status !== 'pending')) {
    return NextResponse.json({ error: 'No evaluation in progress to cancel' }, { status: 409 })
  }

  // Set cancellation signal + status
  await svc
    .from('user_profiles')
    .update({
      eval_cancel_requested_at: new Date().toISOString(),
      eval_status: 'cancelled',
      eval_completed_at: new Date().toISOString(),
    })
    .eq('user_id', user.id)

  // Best-effort: find and cancel the GH workflow run
  const token = process.env.GH_PAT
  const owner = process.env.GITHUB_REPO_OWNER
  const repo = process.env.GITHUB_REPO_NAME

  if (token && owner && repo) {
    try {
      // Find in-progress evaluate_for_user workflow runs
      const listRes = await fetch(
        `https://api.github.com/repos/${owner}/${repo}/actions/workflows/evaluate_for_user.yml/runs?status=in_progress&per_page=5`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
            Accept: 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
          },
        },
      )
      if (listRes.ok) {
        const data = await listRes.json()
        for (const run of data.workflow_runs ?? []) {
          // Cancel all in-progress runs (typically just one)
          await fetch(
            `https://api.github.com/repos/${owner}/${repo}/actions/runs/${run.id}/cancel`,
            {
              method: 'POST',
              headers: {
                Authorization: `Bearer ${token}`,
                Accept: 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
              },
            },
          )
        }
      }
    } catch {
      // Best-effort — DB state is already set
    }
  }

  return NextResponse.json({ ok: true, status: 'cancelled' })
}
