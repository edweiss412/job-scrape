import { createServerClient } from '@supabase/ssr'
import { createClient } from '@supabase/supabase-js'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { extractResumeText } from '@/lib/resume-extract'
import { MODEL_TAILOR_QUESTIONS } from '@/lib/models'

export const maxDuration = 60

async function getClients() {
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

  const adminClient = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
  )

  return { user, adminClient }
}

const SYSTEM_PROMPT = `You are a senior technical recruiter specializing in AV production, broadcast audio, and corporate AV. You help candidates surface hidden experience that would strengthen their resume for specific roles.`

function buildQuestionsPrompt(resumeText: string, jobTitle: string, company: string, fullEval: string): string {
  return `Analyze the gaps between this candidate's resume and the target role. Generate 3-5 short, specific clarifying questions that could reveal experience NOT currently on the resume but relevant to this job.

TARGET ROLE: ${jobTitle} at ${company}

RESUME TEXT:
${resumeText}

FIRST-PASS EVALUATION (gap analysis):
${fullEval.slice(0, 4000)}

Generate a JSON response with this exact structure:
{
  "questions": [
    {
      "id": "1",
      "question": "A specific yes/no or short-answer question",
      "context": "Brief explanation of why this matters for the role",
      "placeholder": "Example: Yes, I managed a Dante network for 3 years"
    }
  ]
}

Rules:
- Ask about specific skills, tools, or experiences mentioned in the job but missing from the resume
- Focus on things the candidate MIGHT have done but didn't list (hidden experience)
- Keep questions concise — one sentence each
- Don't ask about things clearly covered in the resume
- Don't ask about willingness to relocate or salary expectations
- 3-5 questions maximum, ordered by impact

Return ONLY valid JSON. No markdown fences, no preamble.`
}

export async function POST(request: Request) {
  const { user, adminClient } = await getClients()
  if (!user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { jobId } = await request.json() as { jobId: string }
  if (!jobId) {
    return NextResponse.json({ error: 'jobId is required' }, { status: 400 })
  }

  // Fetch job data
  const { data: job, error: jobError } = await adminClient
    .from('jobs')
    .select('title, company, full_evaluation')
    .eq('job_id', jobId)
    .single()

  if (jobError || !job) {
    return NextResponse.json({ error: 'Job not found' }, { status: 404 })
  }

  // Fetch user's evaluation
  const { data: userEval } = await adminClient
    .from('user_evaluations')
    .select('full_evaluation')
    .eq('job_id', jobId)
    .eq('user_id', user.id)
    .maybeSingle()

  const fullEval = userEval?.full_evaluation ?? job.full_evaluation ?? ''
  if (!fullEval) {
    return NextResponse.json({ error: 'No evaluation available for this job.' }, { status: 422 })
  }

  // Fetch user's primary resume
  const { data: resume, error: resumeError } = await adminClient
    .from('resumes')
    .select('file_path, file_name, content_text')
    .eq('user_id', user.id)
    .eq('is_primary', true)
    .single()

  if (resumeError || !resume) {
    return NextResponse.json({ error: 'No primary resume found.' }, { status: 422 })
  }

  const { text: resumeText } = await extractResumeText(adminClient, resume)
  if (!resumeText) {
    return NextResponse.json({ error: 'Could not extract text from your resume' }, { status: 422 })
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
      'X-Title': 'Job Scout Resume Tailor',
    },
    body: JSON.stringify({
      model: MODEL_TAILOR_QUESTIONS,
      max_tokens: 2000,
      messages: [
        { role: 'system', content: SYSTEM_PROMPT },
        { role: 'user', content: buildQuestionsPrompt(resumeText, job.title, job.company, fullEval) },
      ],
    }),
  })

  if (!llmRes.ok) {
    const err = await llmRes.text()
    return NextResponse.json({ error: `LLM error: ${err}` }, { status: 500 })
  }

  const llmData = await llmRes.json()
  const raw = llmData.choices?.[0]?.message?.content?.trim() ?? ''

  try {
    const cleaned = raw
      .replace(/^```json\s*/i, '')
      .replace(/^```\s*/i, '')
      .replace(/\s*```$/i, '')
      .trim()
    const parsed = JSON.parse(cleaned)
    if (!parsed.questions || !Array.isArray(parsed.questions)) {
      throw new Error('Missing questions array')
    }
    // Normalize
    parsed.questions = parsed.questions.slice(0, 5).map((q: { id?: string; question?: string; context?: string; placeholder?: string }, i: number) => ({
      id: q.id || String(i + 1),
      question: q.question || '',
      context: q.context || '',
      placeholder: q.placeholder || '',
    }))
    return NextResponse.json(parsed)
  } catch {
    return NextResponse.json({ error: 'Failed to parse LLM response' }, { status: 500 })
  }
}
