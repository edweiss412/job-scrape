import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { ADMIN_EMAIL } from '@/lib/admin'

async function getUser() {
  const cookieStore = await cookies()
  const base = {
    cookies: {
      getAll() { return cookieStore.getAll() },
      setAll(cookiesToSet: { name: string; value: string; options?: object }[]) {
        cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options))
      },
    },
  }
  const authClient = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    base,
  )
  const { data: { user } } = await authClient.auth.getUser()
  return user
}

export async function GET(request: Request) {
  const user = await getUser()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const token = process.env.GITHUB_TOKEN
  const owner = process.env.GITHUB_REPO_OWNER
  const repo = process.env.GITHUB_REPO_NAME

  if (!token || !owner || !repo) {
    return NextResponse.json({ error: 'GitHub integration not configured' }, { status: 500 })
  }

  const { searchParams } = new URL(request.url)
  const type = searchParams.get('type') ?? 'fulltime'
  const workflowFile = type === 'freelance' ? 'freelance.yml' : 'scrape.yml'

  const res = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowFile}/runs?per_page=3&event=workflow_dispatch`,
    {
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

  const data = await res.json()
  const runs: Array<{
    status: string
    conclusion: string | null
    started_at: string
    html_url: string
    id: number
  }> = data.workflow_runs ?? []

  if (!runs.length) {
    return NextResponse.json({ status: 'idle' })
  }

  const latest = runs[0]
  let status: string

  if (latest.status === 'queued') {
    status = 'queued'
  } else if (latest.status === 'in_progress') {
    status = 'in_progress'
  } else if (latest.status === 'completed') {
    status = latest.conclusion === 'success' ? 'completed' : 'error'
  } else {
    status = 'idle'
  }

  return NextResponse.json({
    status,
    conclusion: latest.conclusion,
    started_at: latest.started_at,
    workflow_url: latest.html_url,
    run_id: latest.id,
  })
}
