import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { ADMIN_EMAIL } from '@/lib/admin'
import { extractResumeText } from '@/lib/resume-extract'
import type { QACategory } from '@/lib/types'

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

const VALID_CATEGORIES: QACategory[] = ['technical', 'behavioral', 'situational', 'general']

const SYSTEM_PROMPT = `You are an expert interviewer and career coach specializing in AV/audio engineering roles. Generate realistic, insightful interview questions and model answers based on the provided resume context. Be specific to the candidate's actual experience.`

function buildGeneratePrompt(context: string): string {
  return `Based on the following resume/evaluation context, generate 8-10 interview Q&A pairs that would be genuinely useful for this AV/audio engineering professional to practice.

Mix question types:
- technical: hands-on AV/audio skills, equipment, systems
- behavioral: past experience ("tell me about a time...")
- situational: hypothetical scenarios ("how would you handle...")
- general: career goals, strengths, motivations

Format your response as a JSON array only (no markdown fences, no preamble):
[
  {
    "question": "...",
    "answer": "...",
    "category": "technical|behavioral|situational|general"
  }
]

Each answer should be 2-4 sentences, specific to the candidate's background.

---
CONTEXT:
${context}`
}

export async function POST(request: Request) {
  const { user, adminClient } = await getClients()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const { resumeId } = await request.json() as { resumeId: string }
  if (!resumeId) {
    return NextResponse.json({ error: 'resumeId is required' }, { status: 400 })
  }

  // Fetch resume
  const { data: resume, error: fetchError } = await adminClient
    .from('resumes')
    .select('resume_evaluation, content_text, file_path, file_name')
    .eq('id', resumeId)
    .single()

  if (fetchError || !resume) {
    return NextResponse.json({ error: 'Resume not found' }, { status: 404 })
  }

  // Get best available context
  let context: string | null = null

  if (resume.resume_evaluation?.trim()) {
    context = resume.resume_evaluation
  } else if (resume.content_text && resume.content_text.length > 100) {
    context = resume.content_text
  } else {
    const { text } = await extractResumeText(adminClient, resume)
    context = text
  }

  if (!context) {
    return NextResponse.json(
      { error: 'No content available for this resume. Please evaluate it first or upload a readable file.' },
      { status: 422 },
    )
  }

  const apiKey = process.env.OPENROUTER_KEY
  if (!apiKey) {
    return NextResponse.json({ error: 'OPENROUTER_KEY not configured' }, { status: 500 })
  }

  const llmRes = await fetch('https://openrouter.ai/api/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
      'HTTP-Referer': 'https://jobs.avprobms.app',
      'X-Title': 'Job Scout Interview Q&A Generator',
    },
    body: JSON.stringify({
      model: 'arcee-ai/trinity-large-preview:free',
      max_tokens: 4000,
      messages: [
        { role: 'system', content: SYSTEM_PROMPT },
        { role: 'user', content: buildGeneratePrompt(context) },
      ],
    }),
  })

  if (!llmRes.ok) {
    const err = await llmRes.text()
    return NextResponse.json({ error: `LLM error: ${err}` }, { status: 500 })
  }

  const llmData = await llmRes.json()
  const raw = llmData.choices?.[0]?.message?.content?.trim() ?? ''

  // Parse JSON defensively — strip possible markdown fences
  let parsed: Array<{ question: string; answer: string; category: string }>
  try {
    const cleaned = raw
      .replace(/^```json\s*/i, '')
      .replace(/^```\s*/i, '')
      .replace(/\s*```$/i, '')
      .trim()
    parsed = JSON.parse(cleaned)
    if (!Array.isArray(parsed)) throw new Error('Not an array')
  } catch {
    return NextResponse.json({ error: 'Failed to parse LLM response as JSON' }, { status: 500 })
  }

  // Validate and normalize
  const rows = parsed
    .filter(item => item?.question?.trim())
    .map(item => ({
      question: item.question.trim(),
      answer: item.answer?.trim() || null,
      category: VALID_CATEGORIES.includes(item.category as QACategory)
        ? (item.category as QACategory)
        : 'general' as QACategory,
      source: 'ai_generated' as const,
    }))

  if (rows.length === 0) {
    return NextResponse.json({ error: 'LLM returned no valid Q&A pairs' }, { status: 500 })
  }

  // Bulk insert
  const { data: inserted, error: insertError } = await adminClient
    .from('interview_qa')
    .insert(rows)
    .select()

  if (insertError) {
    return NextResponse.json({ error: insertError.message }, { status: 500 })
  }

  return NextResponse.json(inserted, { status: 201 })
}
