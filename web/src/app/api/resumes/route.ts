import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { NextResponse, type NextRequest } from 'next/server'

function serverClient() {
  return async () => {
    const cookieStore = await cookies()
    return createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_ROLE_KEY!,
      {
        cookies: {
          getAll() { return cookieStore.getAll() },
          setAll(cookiesToSet) {
            cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options))
          },
        },
      },
    )
  }
}

async function getAuthenticatedClient() {
  const cookieStore = await cookies()
  // Use anon key + cookie session for auth check
  const authClient = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() { return cookieStore.getAll() },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options))
        },
      },
    },
  )
  const { data: { user } } = await authClient.auth.getUser()
  return { user, authClient }
}

// GET /api/resumes — list all resumes
export async function GET() {
  const { user } = await getAuthenticatedClient()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const cookieStore = await cookies()
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { cookies: { getAll() { return cookieStore.getAll() }, setAll() {} } },
  )

  const { data, error } = await supabase
    .from('resumes')
    .select('id, name, is_primary, file_name, file_size, created_at, updated_at, resume_evaluation, resume_evaluated_at')
    .order('created_at', { ascending: false })

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(data)
}

// POST /api/resumes — upload new resume
export async function POST(request: NextRequest) {
  const { user } = await getAuthenticatedClient()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const formData = await request.formData()
  const file = formData.get('file') as File | null
  const name = formData.get('name') as string | null
  const setPrimary = formData.get('setPrimary') === 'true'

  if (!file) return NextResponse.json({ error: 'No file provided' }, { status: 400 })

  const allowedTypes = [
    'text/plain',
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword',
  ]
  if (!allowedTypes.includes(file.type)) {
    return NextResponse.json({ error: 'Only .txt, .pdf, and .docx files are supported' }, { status: 400 })
  }

  const MAX_SIZE = 5 * 1024 * 1024 // 5MB
  if (file.size > MAX_SIZE) {
    return NextResponse.json({ error: 'File too large (max 5MB)' }, { status: 400 })
  }

  const cookieStore = await cookies()
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { cookies: { getAll() { return cookieStore.getAll() }, setAll() {} } },
  )

  // Generate a UUID for the storage path
  const { data: uuidData } = await supabase.rpc('gen_random_uuid')
  const resumeId = uuidData ?? crypto.randomUUID()
  const storagePath = `${resumeId}/${file.name}`

  // Upload to Supabase Storage
  const arrayBuffer = await file.arrayBuffer()
  const { error: uploadError } = await supabase.storage
    .from('resumes')
    .upload(storagePath, arrayBuffer, {
      contentType: file.type,
      upsert: false,
    })

  if (uploadError) {
    return NextResponse.json({ error: uploadError.message }, { status: 500 })
  }

  // Extract text content for .txt files (useful for LLM preview)
  let contentText: string | null = null
  if (file.type === 'text/plain') {
    contentText = await file.text()
  }

  // Insert DB record
  const { data: resume, error: dbError } = await supabase
    .from('resumes')
    .insert({
      id: resumeId,
      name: name?.trim() || file.name.replace(/\.[^.]+$/, ''),
      is_primary: setPrimary,
      file_path: storagePath,
      file_name: file.name,
      file_size: file.size,
      content_text: contentText,
    })
    .select()
    .single()

  if (dbError) {
    // Rollback storage upload
    await supabase.storage.from('resumes').remove([storagePath])
    return NextResponse.json({ error: dbError.message }, { status: 500 })
  }

  return NextResponse.json(resume, { status: 201 })
}
