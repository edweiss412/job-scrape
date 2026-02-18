import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { NextResponse, type NextRequest } from 'next/server'
import { extractResumeText } from '@/lib/resume-extract'

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

const SYSTEM_PROMPT = `You are an expert AV/audio engineering recruiter with 15+ years of experience evaluating candidates for live sound, broadcast, installation, and systems integration roles. You provide honest, specific, actionable resume evaluations. Be direct and concise. No filler phrases.`

function buildEvalPrompt(resumeText: string): string {
  return `Evaluate the following resume for an AV/audio engineering professional. Structure your evaluation with these sections:

### 1. Overall Presentation
Rate clarity, formatting effectiveness, and how well the resume communicates expertise (consider that this is plain text extracted from a formatted doc).

### 2. Technical Skills Assessment
Identify key technical competencies demonstrated. Note depth vs. breadth. Flag any critical AV/audio skills missing for the roles being targeted.

### 3. Experience Narrative
How well does the career progression tell a story? Are accomplishments quantified? Does the experience level match the implied target roles?

### 4. Strongest Selling Points
The 3-4 most compelling aspects of this resume for AV/audio engineering roles.

### 5. Critical Gaps & Weaknesses
Honest assessment of what's missing or underdeveloped. Be specific — what would a hiring manager flag?

### 6. Immediate Improvement Actions
Concrete, prioritized changes that would most improve this resume's effectiveness (top 3-5).

### 7. Readiness Score
Give an overall score 1-10 for current job search readiness, with a one-sentence rationale.

---
RESUME TEXT:
${resumeText}`
}

export async function POST(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const { user, adminClient } = await getClients()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  // Fetch resume record
  const { data: resume, error: fetchError } = await adminClient
    .from('resumes')
    .select('id, file_path, file_name, content_text')
    .eq('id', id)
    .single()

  if (fetchError || !resume) {
    return NextResponse.json({ error: 'Resume not found' }, { status: 404 })
  }

  // Extract text
  const { text, error: extractError } = await extractResumeText(adminClient, resume)
  if (!text) {
    return NextResponse.json(
      { error: extractError ?? 'Could not extract text from resume' },
      { status: 422 },
    )
  }

  const apiKey = process.env.OPENROUTER_KEY
  if (!apiKey) {
    return NextResponse.json({ error: 'OPENROUTER_KEY not configured' }, { status: 500 })
  }

  // Call LLM
  const llmRes = await fetch('https://openrouter.ai/api/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
      'HTTP-Referer': 'https://jobs.avprobms.app',
      'X-Title': 'Job Scout Resume Evaluator',
    },
    body: JSON.stringify({
      model: 'arcee-ai/trinity-large-preview:free',
      max_tokens: 2000,
      messages: [
        { role: 'system', content: SYSTEM_PROMPT },
        { role: 'user', content: buildEvalPrompt(text) },
      ],
    }),
  })

  if (!llmRes.ok) {
    const err = await llmRes.text()
    return NextResponse.json({ error: `LLM error: ${err}` }, { status: 500 })
  }

  const llmData = await llmRes.json()
  const evaluation = llmData.choices?.[0]?.message?.content?.trim() ?? ''

  if (!evaluation) {
    return NextResponse.json({ error: 'Empty response from LLM' }, { status: 500 })
  }

  // Persist to DB
  const evaluatedAt = new Date().toISOString()
  const { data: updated, error: updateError } = await adminClient
    .from('resumes')
    .update({ resume_evaluation: evaluation, resume_evaluated_at: evaluatedAt })
    .eq('id', id)
    .select('id, resume_evaluation, resume_evaluated_at')
    .single()

  if (updateError) {
    return NextResponse.json({ error: updateError.message }, { status: 500 })
  }

  return NextResponse.json(updated)
}
