import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { ADMIN_EMAIL } from '@/lib/admin'

type SuggestField = 'description' | 'use_case' | 'user_impact' | 'steps_to_reproduce' | 'expected_behavior' | 'actual_behavior'

const FIELD_LABELS: Record<SuggestField, string> = {
  description: 'Description',
  use_case: 'Use case',
  user_impact: 'Impact',
  steps_to_reproduce: 'Steps to reproduce',
  expected_behavior: 'Expected behavior',
  actual_behavior: 'Actual behavior',
}

function buildPrompt(
  field: SuggestField,
  title: string,
  type: string,
  currentValues?: Partial<Record<SuggestField, string>>,
): string {
  const existing = currentValues?.[field]?.trim() ?? ''

  // Build context from sibling fields that have content
  const siblings = (Object.keys(FIELD_LABELS) as SuggestField[]).filter(
    (k) => k !== field && currentValues?.[k]?.trim(),
  )
  const contextLines = siblings.map((k) => `${FIELD_LABELS[k]}: ${currentValues![k]!.trim()}`)
  const contextSection =
    contextLines.length > 0 ? `\n\nContext from other filled fields:\n${contextLines.join('\n')}` : ''

  const refineNote = existing
    ? `\n\nThe user has already written the following — clean it up and improve it, keeping their intent intact:\n${existing}`
    : ''

  const basePrompts: Record<SuggestField, string> = {
    description: `Write a clear, concise description (2-3 sentences) for this ${type === 'bug' ? 'bug report' : 'feature request'}: "${title}". Be specific about what the issue/feature involves. Write in first person.`,
    use_case: `Write a brief use case (1-2 sentences) for this feature request: "${title}". Explain when and why someone would use this feature.`,
    user_impact: `Write a brief user impact statement (1-2 sentences) for this feature request: "${title}". Explain how it would improve the user's workflow or experience.`,
    steps_to_reproduce: `Write concise numbered steps to reproduce this bug: "${title}". Include navigation steps, specific actions, and what triggers the issue. Use numbered list format.`,
    expected_behavior: `In one sentence, describe the expected behavior for this bug: "${title}". What should happen?`,
    actual_behavior: `In one sentence, describe the actual (broken) behavior for this bug: "${title}". What currently happens instead?`,
  }

  return `${basePrompts[field]}${contextSection}${refineNote}`
}

export async function POST(request: Request) {
  // Auth check
  const cookieStore = await cookies()
  const supabase = createServerClient(
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
  const { data: { user } } = await supabase.auth.getUser()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const { title, type, field, currentValues, screenshotBase64 } = await request.json() as {
    title: string
    type: 'bug' | 'feature'
    field: SuggestField
    currentValues?: Partial<Record<SuggestField, string>>
    screenshotBase64?: string
  }

  if (!title?.trim() || !field || !FIELD_LABELS[field]) {
    return NextResponse.json({ error: 'Missing required fields' }, { status: 400 })
  }

  const apiKey = process.env.OPENROUTER_KEY
  if (!apiKey) {
    return NextResponse.json({ error: 'OPENROUTER_KEY not configured' }, { status: 500 })
  }

  const systemPrompt = `You are helping document bugs and feature requests for a personal web app called "Job Scout" — a Next.js dashboard for automated AV/audio engineering job search and freelance prospecting. Be direct, concise, and technically precise. No filler phrases like "certainly" or "of course". Output only the requested text, no preamble.`

  const userPrompt = buildPrompt(field, title.trim(), type, currentValues)

  // Use vision model if a screenshot is provided, otherwise use text model
  const hasScreenshot = !!screenshotBase64?.startsWith('data:image/')
  const model = hasScreenshot ? 'google/gemini-flash-1.5' : 'arcee-ai/trinity-large-preview:free'
  const userMessage = hasScreenshot
    ? {
        role: 'user' as const,
        content: [
          { type: 'text', text: userPrompt + '\n\nA screenshot of the page at the time of the report is attached for visual context.' },
          { type: 'image_url', image_url: { url: screenshotBase64 } },
        ],
      }
    : { role: 'user' as const, content: userPrompt }

  const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
      'HTTP-Referer': 'https://jobs.avprobms.app',
      'X-Title': 'Job Scout Admin',
    },
    body: JSON.stringify({
      model,
      max_tokens: 200,
      messages: [
        { role: 'system', content: systemPrompt },
        userMessage,
      ],
    }),
  })

  if (!res.ok) {
    const err = await res.text()
    return NextResponse.json({ error: `OpenRouter error: ${err}` }, { status: 500 })
  }

  const data = await res.json()
  const suggestion = data.choices?.[0]?.message?.content?.trim() ?? ''

  return NextResponse.json({ suggestion })
}
