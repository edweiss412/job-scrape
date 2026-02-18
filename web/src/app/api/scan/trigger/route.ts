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

export async function POST(request: Request) {
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

  const body = await request.json()
  const { type, category, max_companies, no_verify } = body

  const workflowFile = type === 'freelance' ? 'freelance.yml' : 'scrape.yml'

  const inputs: Record<string, string> = {}
  if (type === 'freelance') {
    if (category) inputs.category = category
    if (max_companies) inputs.max_companies = String(max_companies)
    if (no_verify) inputs.no_verify = 'true'
  }

  const res = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowFile}/dispatches`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
      body: JSON.stringify({ ref: 'main', inputs }),
    },
  )

  if (!res.ok) {
    const text = await res.text()
    return NextResponse.json({ error: `GitHub API error: ${text}` }, { status: 502 })
  }

  return NextResponse.json({ ok: true }, { status: 202 })
}
