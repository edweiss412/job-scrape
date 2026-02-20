import { createClient, createServiceClient } from '@/lib/supabase/server'
import { NextResponse } from 'next/server'

// GET /api/jobs/unevaluated — count of jobs that passed pre-filter but have no evaluation for the current user
export async function GET() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const svc = createServiceClient()

  // Use the RPC function for an efficient count
  const { data, error } = await svc.rpc('count_unevaluated_jobs', { p_user_id: user.id })

  if (error) {
    console.error('count_unevaluated_jobs RPC error:', error)
    return NextResponse.json({ error: error.message }, { status: 500 })
  }

  const result = data as { count: number; latest_scrape: string | null } | null

  return NextResponse.json({
    count: result?.count ?? 0,
    latest_scrape: result?.latest_scrape ?? null,
  })
}
