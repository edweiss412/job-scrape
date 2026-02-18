import { createClient } from '@/lib/supabase/server'
import { createServiceClient } from '@/lib/supabase/server'
import { NextResponse, type NextRequest } from 'next/server'
import { ADMIN_EMAIL } from '@/lib/admin'

// PATCH /api/feedback/[id] — update status and/or editable fields
export async function PATCH(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const body = await request.json()
  const patch: Record<string, unknown> = { updated_at: new Date().toISOString() }

  if (body.status !== undefined) patch.status = body.status
  if (body.title !== undefined) patch.title = body.title
  if (body.description !== undefined) patch.description = body.description
  if (body.priority !== undefined) patch.priority = body.priority
  if (body.steps_to_reproduce !== undefined) patch.steps_to_reproduce = body.steps_to_reproduce || null
  if (body.expected_behavior !== undefined) patch.expected_behavior = body.expected_behavior || null
  if (body.actual_behavior !== undefined) patch.actual_behavior = body.actual_behavior || null
  if (body.use_case !== undefined) patch.use_case = body.use_case || null
  if (body.user_impact !== undefined) patch.user_impact = body.user_impact || null

  const adminClient = createServiceClient()
  const { data, error } = await adminClient
    .from('feedback')
    .update(patch)
    .eq('id', id)
    .select()
    .single()

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(data)
}

// DELETE /api/feedback/[id]
export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const adminClient = createServiceClient()
  const { error } = await adminClient.from('feedback').delete().eq('id', id)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return new NextResponse(null, { status: 204 })
}
