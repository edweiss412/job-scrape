import { createClient } from '@/lib/supabase/server'
import { createServiceClient } from '@/lib/supabase/server'
import { NextResponse } from 'next/server'
import { ADMIN_EMAIL } from '@/lib/admin'

export async function GET(request: Request) {
  // Admin-only
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const { searchParams } = new URL(request.url)
  const from = searchParams.get('from')
  const to = searchParams.get('to')

  const admin = createServiceClient()

  // Fetch all logs within the time range (last 30 days default)
  const now = new Date()
  const rangeStart = from || new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString()
  const rangeEnd = to || now.toISOString()

  const { data: logs, error } = await admin
    .from('api_usage_log')
    .select('*')
    .gte('created_at', rangeStart)
    .lte('created_at', rangeEnd)
    .order('created_at', { ascending: false })
    .limit(2000)

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }

  // Resolve user emails for the dropdown
  const userIdSet = new Set<string>()
  for (const log of logs || []) {
    if (log.user_id) userIdSet.add(log.user_id)
  }

  const users: { id: string; email: string }[] = [
    { id: 'system', email: 'System / Pipeline' },
  ]

  if (userIdSet.size > 0) {
    const { data: { users: authUsers } } = await admin.auth.admin.listUsers({ perPage: 1000 })
    for (const u of authUsers || []) {
      if (userIdSet.has(u.id)) {
        users.push({ id: u.id, email: u.email || u.id })
      }
    }
  }

  return NextResponse.json({ recent: logs || [], users })
}
