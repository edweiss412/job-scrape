import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { NextResponse, type NextRequest } from 'next/server'

async function getClients() {
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

  const adminClient = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    base,
  )

  return { user, adminClient }
}

// PATCH /api/resumes/[id] — update name or set as primary
export async function PATCH(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const { user, adminClient } = await getClients()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const body = await request.json()
  const updates: Record<string, unknown> = { updated_at: new Date().toISOString() }
  if ('name' in body) updates.name = body.name
  if ('is_primary' in body) updates.is_primary = body.is_primary

  const { data, error } = await adminClient
    .from('resumes')
    .update(updates)
    .eq('id', id)
    .eq('user_id', user.id)
    .select()
    .single()

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(data)
}

// DELETE /api/resumes/[id]
export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const { user, adminClient } = await getClients()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  // Get the file_path first (scoped to user)
  const { data: resume } = await adminClient
    .from('resumes')
    .select('file_path')
    .eq('id', id)
    .eq('user_id', user.id)
    .single()

  if (!resume) return NextResponse.json({ error: 'Not found' }, { status: 404 })

  // Delete from storage
  await adminClient.storage.from('resumes').remove([resume.file_path])

  // Delete DB record
  const { error } = await adminClient.from('resumes').delete().eq('id', id).eq('user_id', user.id)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  return new NextResponse(null, { status: 204 })
}
