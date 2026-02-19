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

// POST /api/admin/scans/delete — delete one or more workflow runs
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
  const { run_ids } = body

  if (!Array.isArray(run_ids) || run_ids.length === 0 || !run_ids.every((id: unknown) => typeof id === 'number')) {
    return NextResponse.json({ error: 'run_ids must be a non-empty array of numbers' }, { status: 400 })
  }

  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  }

  const results = await Promise.allSettled(
    run_ids.map(async (runId: number) => {
      const res = await fetch(
        `https://api.github.com/repos/${owner}/${repo}/actions/runs/${runId}`,
        { method: 'DELETE', headers },
      )
      if (!res.ok && res.status !== 204) {
        const text = await res.text()
        throw new Error(`Run ${runId}: ${text}`)
      }
      return runId
    }),
  )

  const deleted = results
    .filter((r): r is PromiseFulfilledResult<number> => r.status === 'fulfilled')
    .map((r) => r.value)
  const errors = results
    .filter((r): r is PromiseRejectedResult => r.status === 'rejected')
    .map((r) => r.reason?.message ?? 'Unknown error')

  return NextResponse.json({ deleted, errors })
}
