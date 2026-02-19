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

// GET /api/admin/scans/evaluations — list user evaluation statuses
export async function GET() {
  const user = await getAuthUser()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const adminClient = createServiceClient()

  const [profilesResult, usersResult] = await Promise.all([
    adminClient
      .from('user_profiles')
      .select('user_id, eval_status, eval_started_at, eval_completed_at, eval_job_count, eval_jobs_done'),
    adminClient.auth.admin.listUsers(),
  ])

  if (profilesResult.error) {
    return NextResponse.json({ error: profilesResult.error.message }, { status: 500 })
  }
  if (usersResult.error) {
    return NextResponse.json({ error: usersResult.error.message }, { status: 500 })
  }

  const emailMap = new Map(
    usersResult.data.users.map((u) => [u.id, u.email]),
  )

  const evaluations = (profilesResult.data ?? []).map((p) => ({
    user_id: p.user_id,
    email: emailMap.get(p.user_id) ?? null,
    eval_status: p.eval_status ?? 'idle',
    eval_started_at: p.eval_started_at ?? null,
    eval_completed_at: p.eval_completed_at ?? null,
    eval_job_count: p.eval_job_count ?? null,
    eval_jobs_done: p.eval_jobs_done ?? null,
  }))

  return NextResponse.json(evaluations)
}
