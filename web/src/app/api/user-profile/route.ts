import { createServerClient } from '@supabase/ssr'
import { createServiceClient } from '@/lib/supabase/server'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'

async function getUser() {
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

// GET /api/user-profile — fetch current user's profile (returns defaults if none)
export async function GET() {
  const user = await getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const svc = createServiceClient()
  const { data, error } = await svc
    .from('user_profiles')
    .select('*')
    .eq('user_id', user.id)
    .maybeSingle()

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  // Return defaults if no profile row yet
  if (!data) {
    return NextResponse.json({
      user_id: user.id,
      target_roles: ['audio engineer', 'av technician'],
      target_locations: ['Chicago, IL', 'Remote'],
      candidate_context: null,
      notify_email: user.email ?? null,
      home_city: null,
      current_income: null,
      full_name: null,
      phone: null,
      linkedin_url: null,
      professional_title: null,
      created_at: null,
      updated_at: null,
    })
  }

  return NextResponse.json(data)
}

// PUT /api/user-profile — upsert current user's profile
export async function PUT(request: Request) {
  const user = await getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const body = await request.json()
  const svc = createServiceClient()

  const { data, error } = await svc
    .from('user_profiles')
    .upsert(
      {
        user_id: user.id,
        target_roles: body.target_roles ?? ['audio engineer', 'av technician'],
        target_locations: body.target_locations ?? ['Chicago, IL', 'Remote'],
        candidate_context: body.candidate_context ?? null,
        notify_email: body.notify_email ?? null,
        home_city: body.home_city?.trim() || null,
        current_income: body.current_income ? Number(body.current_income) : null,
        full_name: body.full_name?.trim() || null,
        phone: body.phone?.trim() || null,
        linkedin_url: body.linkedin_url?.trim() || null,
        professional_title: body.professional_title?.trim() || null,
        updated_at: new Date().toISOString(),
      },
      { onConflict: 'user_id' },
    )
    .select()
    .single()

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(data)
}
