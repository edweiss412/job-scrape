import { createClient } from '@/lib/supabase/server'
import { createServiceClient } from '@/lib/supabase/server'
import { NextResponse } from 'next/server'
import { ADMIN_EMAIL } from '@/lib/admin'

// Lightweight columns for aggregation (no metadata JSONB)
const AGG_COLUMNS = 'created_at, source, category, pipeline, model, user_id, cost_usd, total_tokens, prompt_tokens, completion_tokens, latency_ms, success'

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

  const now = new Date()
  const rangeStart = from || new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString()
  const rangeEnd = to || now.toISOString()

  // Two parallel queries:
  // 1. Lightweight aggregation data — ALL rows, no limit (excludes metadata JSONB)
  // 2. Recent activity — full rows, limited to 500
  const [aggResult, recentResult] = await Promise.all([
    admin
      .from('api_usage_log')
      .select(AGG_COLUMNS)
      .gte('created_at', rangeStart)
      .lte('created_at', rangeEnd)
      .order('created_at', { ascending: false }),
    admin
      .from('api_usage_log')
      .select('*')
      .gte('created_at', rangeStart)
      .lte('created_at', rangeEnd)
      .order('created_at', { ascending: false })
      .limit(500),
  ])

  if (aggResult.error) {
    return NextResponse.json({ error: aggResult.error.message }, { status: 500 })
  }

  const aggLogs = aggResult.data || []
  const recentLogs = recentResult.data || []

  // Resolve user emails from aggregation data (covers all users, not just recent 500)
  const userIdSet = new Set<string>()
  for (const log of aggLogs) {
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

  return NextResponse.json({ agg: aggLogs, recent: recentLogs, users })
}
