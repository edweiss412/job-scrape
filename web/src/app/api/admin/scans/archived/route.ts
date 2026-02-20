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

// GET /api/admin/scans/archived — returns counts of archived jobs/companies grouped by first_seen_date
export async function GET() {
  const user = await getAuthUser()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const svc = createServiceClient()

  const [jobsResult, companiesResult] = await Promise.all([
    svc.from('jobs').select('first_seen_date').not('archived_at', 'is', null),
    svc.from('freelance_companies').select('first_seen_date').not('archived_at', 'is', null),
  ])

  // Aggregate jobs by date
  const jobDateMap: Record<string, number> = {}
  for (const row of jobsResult.data ?? []) {
    jobDateMap[row.first_seen_date] = (jobDateMap[row.first_seen_date] ?? 0) + 1
  }
  const fulltime = Object.entries(jobDateMap)
    .map(([date, count]) => ({ date, count }))
    .sort((a, b) => b.date.localeCompare(a.date))

  // Aggregate companies by date
  const companyDateMap: Record<string, number> = {}
  for (const row of companiesResult.data ?? []) {
    companyDateMap[row.first_seen_date] = (companyDateMap[row.first_seen_date] ?? 0) + 1
  }
  const freelance = Object.entries(companyDateMap)
    .map(([date, count]) => ({ date, count }))
    .sort((a, b) => b.date.localeCompare(a.date))

  return NextResponse.json({
    fulltime,
    freelance,
    totals: {
      jobs: jobsResult.data?.length ?? 0,
      companies: companiesResult.data?.length ?? 0,
    },
  })
}
