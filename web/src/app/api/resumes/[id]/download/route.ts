import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
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
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const adminClient = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    base,
  )

  const { data: resume } = await adminClient
    .from('resumes')
    .select('file_path, file_name')
    .eq('id', id)
    .single()

  if (!resume) return NextResponse.json({ error: 'Not found' }, { status: 404 })

  const { data, error } = await adminClient.storage
    .from('resumes')
    .createSignedUrl(resume.file_path, 60 * 60) // 1 hour

  if (error || !data) return NextResponse.json({ error: 'Could not generate download URL' }, { status: 500 })

  return NextResponse.json({ url: data.signedUrl, filename: resume.file_name })
}
