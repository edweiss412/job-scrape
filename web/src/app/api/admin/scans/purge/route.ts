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

type PurgeScope = 'fulltime' | 'freelance' | 'all'

// POST /api/admin/scans/purge — delete all data for a given scope
export async function POST(request: Request) {
  const user = await getAuthUser()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const body = await request.json()
  const { scope } = body as { scope: PurgeScope }

  if (!scope || !['fulltime', 'freelance', 'all'].includes(scope)) {
    return NextResponse.json({ error: 'scope must be "fulltime", "freelance", or "all"' }, { status: 400 })
  }

  const svc = createServiceClient()
  const counts: Record<string, number> = {}
  const errors: string[] = []

  // Helper: delete all rows from a table and return count
  async function purgeTable(table: string): Promise<number> {
    // Use gte on id/primary key to match all rows — Supabase requires a filter for delete
    const { data, error } = await svc.from(table).delete().gte('id', 0).select('id')
    if (error) {
      // Fallback for tables with non-numeric PKs — use neq on a text column
      errors.push(`${table}: ${error.message}`)
      return 0
    }
    return data?.length ?? 0
  }

  // For tables with text PKs, use a different approach
  async function purgeTableTextPK(table: string, pkColumn: string): Promise<number> {
    const { data, error } = await svc.from(table).delete().neq(pkColumn, '').select(pkColumn)
    if (error) {
      errors.push(`${table}: ${error.message}`)
      return 0
    }
    return data?.length ?? 0
  }

  if (scope === 'fulltime' || scope === 'all') {
    // Order respects FKs: user_evaluations → run_jobs → runs → scrape_runs → jobs
    counts.user_evaluations = await purgeTableTextPK('user_evaluations', 'job_id')
    counts.run_jobs = await purgeTable('run_jobs')
    counts.runs = await purgeTable('runs')
    counts.scrape_runs = await purgeTable('scrape_runs')
    counts.jobs = await purgeTableTextPK('jobs', 'job_id')
  }

  if (scope === 'freelance' || scope === 'all') {
    // user_freelance_evaluations → freelance_companies
    counts.user_freelance_evaluations = await purgeTableTextPK('user_freelance_evaluations', 'company_id')
    counts.freelance_companies = await purgeTableTextPK('freelance_companies', 'company_id')
  }

  return NextResponse.json({ counts, errors })
}
