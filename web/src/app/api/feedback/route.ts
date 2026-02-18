import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { ADMIN_EMAIL } from '@/lib/admin'

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

// POST /api/feedback — create a new feedback item
export async function POST(request: Request) {
  const { user, adminClient } = await getClients()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const body = await request.json()

  const { data, error } = await adminClient
    .from('feedback')
    .insert({
      type: body.type,
      title: body.title,
      description: body.description,
      priority: body.priority ?? 'medium',
      page_url: body.page_url ?? null,
      steps_to_reproduce: body.steps_to_reproduce || null,
      expected_behavior: body.expected_behavior || null,
      actual_behavior: body.actual_behavior || null,
      use_case: body.use_case || null,
      user_impact: body.user_impact || null,
      reporter_email: user.email,
    })
    .select()
    .single()

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(data, { status: 201 })
}

// GET /api/feedback — list all feedback items (admin only)
export async function GET() {
  const { user, adminClient } = await getClients()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const { data, error } = await adminClient
    .from('feedback')
    .select('*')
    .order('created_at', { ascending: false })

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(data)
}
