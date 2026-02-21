import { createClient } from '@/lib/supabase/server'
import { NextResponse } from 'next/server'

export async function GET() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { data, error } = await supabase
    .from('user_job_actions')
    .select('job_id, action')

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(data ?? [])
}

export async function PUT(request: Request) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { job_id, action } = await request.json()
  if (!job_id || !action) {
    return NextResponse.json({ error: 'job_id and action required' }, { status: 400 })
  }

  // Check if same action already exists (toggle = delete)
  const { data: existing } = await supabase
    .from('user_job_actions')
    .select('id, action')
    .eq('job_id', job_id)
    .maybeSingle()

  if (existing && existing.action === action) {
    // Toggle off — delete the row
    await supabase.from('user_job_actions').delete().eq('id', existing.id)
    return NextResponse.json({ deleted: true })
  }

  // Upsert (insert or update to new action)
  const { error } = await supabase
    .from('user_job_actions')
    .upsert(
      { user_id: user.id, job_id, action },
      { onConflict: 'user_id,job_id' },
    )

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json({ job_id, action })
}
