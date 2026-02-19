import { createServerClient } from '@supabase/ssr'
import { createClient } from '@supabase/supabase-js'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { extractResumeText } from '@/lib/resume-extract'
import { MODEL_RESUME_TAILOR } from '@/lib/models'
import type { TailoringSuggestion, TailoringSuggestionsResponse } from '@/lib/types'

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

  return { user, authClient, adminClient }
}

const SYSTEM_PROMPT = `You are an expert resume strategist specializing in AV/audio engineering careers. You analyze job descriptions and resumes to produce specific, actionable resume tailoring suggestions. Be precise — reference exact text from the resume when suggesting changes.`

function buildSuggestionsPrompt(resumeText: string, jobTitle: string, company: string, fullEval: string, deepEval: string): string {
  return `Analyze this resume against the target job and produce structured tailoring suggestions.

TARGET ROLE: ${jobTitle} at ${company}

RESUME TEXT:
${resumeText}

JOB EVALUATION CONTEXT:
${fullEval.slice(0, 3000)}

DEEP EVALUATION (including existing tailoring suggestions):
${deepEval.slice(0, 5000)}

Generate a JSON response with this exact structure:
{
  "summary": "Brief 1-2 sentence overview of the tailoring strategy",
  "ats_keywords": ["keyword1", "keyword2", ...],
  "suggestions": [
    {
      "id": "1",
      "type": "rewrite",
      "section": "Section name > subsection",
      "before": "exact text from the resume to replace",
      "after": "improved replacement text",
      "reasoning": "why this change matters for this role",
      "priority": "high"
    },
    {
      "id": "2",
      "type": "add",
      "section": "Section to add content to",
      "after": "new text to add",
      "reasoning": "why this addition strengthens the application",
      "priority": "medium"
    },
    {
      "id": "3",
      "type": "remove",
      "section": "Section containing text to remove",
      "before": "text to remove",
      "after": "",
      "reasoning": "why removing this improves focus",
      "priority": "low"
    }
  ]
}

Rules:
- "rewrite" suggestions MUST include exact "before" text from the resume
- "add" suggestions have no "before" — only "after" with new content
- "remove" suggestions have "before" text to cut and empty "after"
- Include 5-12 suggestions, prioritized by impact
- ats_keywords: 8-15 keywords from the job that should appear in the resume
- Priority: "high" = critical for this role, "medium" = helpful, "low" = nice to have
- Reference the deep evaluation's existing tailoring section but expand and improve upon it

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

  // Fetch job catalog data
  const { data: job, error: jobError } = await adminClient
    .from('jobs')
    .select('title, company, full_evaluation, deep_evaluation')
    .eq('job_id', jobId)
    .single()

  if (jobError || !job) {
    return NextResponse.json({ error: 'Job not found' }, { status: 404 })
  }

  // Fetch user's evaluation (may have different eval content than the global job row)
  const { data: userEval } = await adminClient
    .from('user_evaluations')
    .select('full_evaluation, deep_evaluation')
    .eq('job_id', jobId)
    .eq('user_id', user.id)
    .maybeSingle()

  const fullEval = userEval?.full_evaluation ?? job.full_evaluation ?? ''
  const deepEval = userEval?.deep_evaluation ?? job.deep_evaluation ?? ''

  if (!deepEval) {
    return NextResponse.json({ error: 'No deep evaluation available for this job' }, { status: 422 })
  }

  // Fetch user's primary resume
  const { data: resume, error: resumeError } = await adminClient
    .from('resumes')
    .select('file_path, file_name, content_text')
    .eq('user_id', user.id)
    .eq('is_primary', true)
    .single()

  if (resumeError || !resume) {
    return NextResponse.json({ error: 'No primary resume found. Upload a resume in your profile first.' }, { status: 422 })
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
      model: MODEL_RESUME_TAILOR,
      max_tokens: 8000,
      messages: [
        { role: 'system', content: SYSTEM_PROMPT },
        { role: 'user', content: buildSuggestionsPrompt(resumeText, job.title, job.company, fullEval, deepEval) },
      ],
    }),
  })

  if (!llmRes.ok) {
    const err = await llmRes.text()
    return NextResponse.json({ error: `LLM error: ${err}` }, { status: 500 })
  }

  const llmData = await llmRes.json()
  const raw = llmData.choices?.[0]?.message?.content?.trim() ?? ''

  let parsed: TailoringSuggestionsResponse
  try {
    const cleaned = raw
      .replace(/^```json\s*/i, '')
      .replace(/^```\s*/i, '')
      .replace(/\s*```$/i, '')
      .trim()
    parsed = JSON.parse(cleaned)
    if (!parsed.suggestions || !Array.isArray(parsed.suggestions)) {
      throw new Error('Missing suggestions array')
    }
  } catch {
    return NextResponse.json({ error: 'Failed to parse LLM response as JSON' }, { status: 500 })
  }

  // Normalize and validate suggestions
  const validTypes = ['rewrite', 'add', 'remove'] as const
  const validPriorities = ['high', 'medium', 'low'] as const

  parsed.suggestions = parsed.suggestions
    .filter((s: TailoringSuggestion) => s && s.section && s.after !== undefined)
    .map((s: TailoringSuggestion, i: number) => ({
      id: s.id || String(i + 1),
      type: validTypes.includes(s.type) ? s.type : 'rewrite',
      section: s.section,
      before: s.before,
      after: s.after,
      reasoning: s.reasoning || '',
      priority: validPriorities.includes(s.priority) ? s.priority : 'medium',
    }))

  parsed.summary = parsed.summary || ''
  parsed.ats_keywords = Array.isArray(parsed.ats_keywords) ? parsed.ats_keywords : []

  return NextResponse.json(parsed)
}
