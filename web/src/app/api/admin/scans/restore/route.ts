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

interface RestoreRequest {
  action: 'restore' | 'delete'
  scope: 'fulltime' | 'freelance' | 'all'
  dates?: string[]
}

// POST /api/admin/scans/restore — restore or permanently delete archived data
export async function POST(request: Request) {
  const user = await getAuthUser()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const body = await request.json() as RestoreRequest
  const { action, scope, dates } = body

  if (!action || !['restore', 'delete'].includes(action)) {
    return NextResponse.json({ error: 'action must be "restore" or "delete"' }, { status: 400 })
  }
  if (!scope || !['fulltime', 'freelance', 'all'].includes(scope)) {
    return NextResponse.json({ error: 'scope must be "fulltime", "freelance", or "all"' }, { status: 400 })
  }

  const svc = createServiceClient()
  const counts: Record<string, number> = {}
  const errors: string[] = []

  if (scope === 'fulltime' || scope === 'all') {
    try {
      if (action === 'restore') {
        // Restore: set archived_at = null
        let q = svc.from('jobs').update({ archived_at: null }).not('archived_at', 'is', null)
        if (dates?.length) q = q.in('first_seen_date', dates)
        const { data, error } = await q.select('job_id')
        if (error) errors.push(`jobs restore: ${error.message}`)
        counts.jobs = data?.length ?? 0
      } else {
        // Permanently delete archived jobs + their evaluations
        // First, find archived job IDs
        let q = svc.from('jobs').select('job_id').not('archived_at', 'is', null)
        if (dates?.length) q = q.in('first_seen_date', dates)
        const { data: jobRows } = await q
        if (jobRows?.length) {
          const jobIds = jobRows.map((j: { job_id: string }) => j.job_id)
          const BATCH = 100
          let evalCount = 0
          for (let i = 0; i < jobIds.length; i += BATCH) {
            const batch = jobIds.slice(i, i + BATCH)
            const { data: evalData } = await svc.from('user_evaluations').delete().in('job_id', batch).select('id')
            evalCount += evalData?.length ?? 0
            await svc.from('jobs').delete().in('job_id', batch)
          }
          counts.user_evaluations = evalCount
          counts.jobs = jobRows.length
        } else {
          counts.jobs = 0
        }
      }
    } catch (e) {
      errors.push(`fulltime: ${e instanceof Error ? e.message : 'unknown'}`)
    }
  }

  if (scope === 'freelance' || scope === 'all') {
    try {
      if (action === 'restore') {
        let q = svc.from('freelance_companies').update({ archived_at: null }).not('archived_at', 'is', null)
        if (dates?.length) q = q.in('first_seen_date', dates)
        const { data, error } = await q.select('company_id')
        if (error) errors.push(`freelance restore: ${error.message}`)
        counts.companies = data?.length ?? 0
      } else {
        // Permanently delete archived companies + their evaluations
        let q = svc.from('freelance_companies').select('company_id').not('archived_at', 'is', null)
        if (dates?.length) q = q.in('first_seen_date', dates)
        const { data: companyRows } = await q
        if (companyRows?.length) {
          const companyIds = companyRows.map((c: { company_id: string }) => c.company_id)
          const BATCH = 100
          let evalCount = 0
          for (let i = 0; i < companyIds.length; i += BATCH) {
            const batch = companyIds.slice(i, i + BATCH)
            const { data: evalData } = await svc.from('user_freelance_evaluations').delete().in('company_id', batch).select('id')
            evalCount += evalData?.length ?? 0
          }
          // Delete the archived companies themselves
          let delQ = svc.from('freelance_companies').delete().not('archived_at', 'is', null)
          if (dates?.length) delQ = delQ.in('first_seen_date', dates)
          await delQ
          counts.user_freelance_evaluations = evalCount
          counts.companies = companyRows.length
        } else {
          counts.companies = 0
        }
      }
    } catch (e) {
      errors.push(`freelance: ${e instanceof Error ? e.message : 'unknown'}`)
    }
  }

  return NextResponse.json({ counts, errors })
}
