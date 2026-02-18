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

// DELETE /api/admin/users/[userId] — permanently delete a user
export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ userId: string }> },
) {
  const user = await getAuthUser()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const { userId } = await params

  // Prevent deleting the admin account itself
  const adminClient = createServiceClient()
  const { data: target, error: fetchError } = await adminClient.auth.admin.getUserById(userId)
  if (fetchError) return NextResponse.json({ error: fetchError.message }, { status: 500 })
  if (target.user.email === ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Cannot delete the admin account' }, { status: 400 })
  }

  const { error } = await adminClient.auth.admin.deleteUser(userId)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  return NextResponse.json({ deleted: true })
}

// PATCH /api/admin/users/[userId] — update a user's role
export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ userId: string }> },
) {
  const user = await getAuthUser()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const { userId } = await params
  const body = await request.json()
  const role: string | null = body.role ?? null

  const adminClient = createServiceClient()
  const { data, error } = await adminClient.auth.admin.updateUserById(userId, {
    app_metadata: { role },
  })

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  return NextResponse.json({
    id: data.user.id,
    email: data.user.email,
    role: (data.user.app_metadata?.role as string) ?? null,
  })
}
