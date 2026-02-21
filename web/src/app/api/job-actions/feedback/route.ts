import { createClient } from '@/lib/supabase/server'
import { NextResponse } from 'next/server'

export async function PUT(request: Request) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { job_id, feedback } = await request.json()
  if (!job_id) return NextResponse.json({ error: 'job_id required' }, { status: 400 })
  if (feedback && feedback !== 'up' && feedback !== 'down') {
    return NextResponse.json({ error: 'feedback must be "up", "down", or null' }, { status: 400 })
  }

  const { error } = await supabase
    .from('user_evaluations')
    .update({ match_feedback: feedback ?? null })
    .eq('job_id', job_id)

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json({ job_id, feedback })
}
