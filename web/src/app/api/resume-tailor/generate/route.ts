import { createServerClient } from '@supabase/ssr'
import { createClient } from '@supabase/supabase-js'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { extractResumeText } from '@/lib/resume-extract'
import { MODEL_RESUME_TAILOR } from '@/lib/models'
import {
  Document, Packer, Paragraph, TextRun,
  HeadingLevel, AlignmentType,
} from 'docx'

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

interface AcceptedSuggestion {
  id: string
  type: 'rewrite' | 'add' | 'remove'
  section: string
  before?: string
  finalText: string
}

const SYSTEM_PROMPT = `You are a professional resume writer. Apply the provided changes to the resume and return the complete updated resume text. Maintain the original structure, formatting, and tone. Only make the specified changes — do not add, remove, or rephrase anything else.`

function buildApplyPrompt(resumeText: string, suggestions: AcceptedSuggestion[]): string {
  const changes = suggestions.map((s, i) => {
    if (s.type === 'rewrite') {
      return `${i + 1}. REWRITE in "${s.section}":
   FIND: "${s.before}"
   REPLACE WITH: "${s.finalText}"`
    }
    if (s.type === 'add') {
      return `${i + 1}. ADD to "${s.section}":
   NEW TEXT: "${s.finalText}"`
    }
    return `${i + 1}. REMOVE from "${s.section}":
   DELETE: "${s.before}"`
  }).join('\n\n')

  return `Apply these changes to the resume below and return the COMPLETE updated resume text.

CHANGES TO APPLY:
${changes}

ORIGINAL RESUME:
${resumeText}

Return ONLY the complete updated resume text. No commentary, no markdown fences.`
}

function buildDocx(text: string): Document {
  const lines = text.split('\n')
  const children: Paragraph[] = []

  for (const line of lines) {
    const trimmed = line.trim()

    if (!trimmed) {
      children.push(new Paragraph({ spacing: { after: 100 } }))
      continue
    }

    // Detect headings: all caps lines or lines ending with ':'
    const isAllCaps = trimmed === trimmed.toUpperCase() && trimmed.length > 2 && /[A-Z]/.test(trimmed)
    const isHeadingWithColon = trimmed.endsWith(':') && trimmed.length < 60 && !trimmed.startsWith('-') && !trimmed.startsWith('•')

    if (isAllCaps) {
      children.push(new Paragraph({
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 240, after: 80 },
        children: [new TextRun({ text: trimmed, bold: true, size: 24, font: 'Calibri' })],
      }))
      continue
    }

    if (isHeadingWithColon) {
      children.push(new Paragraph({
        heading: HeadingLevel.HEADING_3,
        spacing: { before: 200, after: 60 },
        children: [new TextRun({ text: trimmed, bold: true, size: 22, font: 'Calibri' })],
      }))
      continue
    }

    // Bullet points
    if (trimmed.startsWith('-') || trimmed.startsWith('•') || trimmed.startsWith('*')) {
      const bulletText = trimmed.replace(/^[-•*]\s*/, '')
      children.push(new Paragraph({
        bullet: { level: 0 },
        spacing: { after: 40 },
        children: [new TextRun({ text: bulletText, size: 21, font: 'Calibri' })],
      }))
      continue
    }

    // Detect name line (first non-empty line, likely candidate name)
    if (children.length === 0) {
      children.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 60 },
        children: [new TextRun({ text: trimmed, bold: true, size: 28, font: 'Calibri' })],
      }))
      continue
    }

    // Contact info / short metadata lines near the top
    if (children.length < 5 && trimmed.length < 100 && (trimmed.includes('@') || trimmed.includes('|') || /^\d{3}/.test(trimmed) || trimmed.includes('linkedin'))) {
      children.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 40 },
        children: [new TextRun({ text: trimmed, size: 20, font: 'Calibri', color: '555555' })],
      }))
      continue
    }

    // Regular paragraph
    children.push(new Paragraph({
      spacing: { after: 60 },
      children: [new TextRun({ text: trimmed, size: 21, font: 'Calibri' })],
    }))
  }

  return new Document({
    sections: [{
      properties: {
        page: {
          margin: { top: 720, bottom: 720, left: 720, right: 720 },
        },
      },
      children,
    }],
  })
}

export async function POST(request: Request) {
  const { user, adminClient } = await getClients()
  if (!user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { jobId, acceptedSuggestions } = await request.json() as {
    jobId: string
    acceptedSuggestions: AcceptedSuggestion[]
  }

  if (!jobId || !acceptedSuggestions?.length) {
    return NextResponse.json({ error: 'jobId and at least one accepted suggestion are required' }, { status: 400 })
  }

  // Fetch user's primary resume
  const { data: resume, error: resumeError } = await adminClient
    .from('resumes')
    .select('file_path, file_name, content_text')
    .eq('user_id', user.id)
    .eq('is_primary', true)
    .single()

  if (resumeError || !resume) {
    return NextResponse.json({ error: 'No primary resume found' }, { status: 422 })
  }

  const { text: resumeText } = await extractResumeText(adminClient, resume)
  if (!resumeText) {
    return NextResponse.json({ error: 'Could not extract text from your resume' }, { status: 422 })
  }

  const apiKey = process.env.OPENROUTER_KEY
  if (!apiKey) {
    return NextResponse.json({ error: 'OPENROUTER_KEY not configured' }, { status: 500 })
  }

  // Call LLM to apply the changes
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
        { role: 'user', content: buildApplyPrompt(resumeText, acceptedSuggestions) },
      ],
    }),
  })

  if (!llmRes.ok) {
    const err = await llmRes.text()
    return NextResponse.json({ error: `LLM error: ${err}` }, { status: 500 })
  }

  const llmData = await llmRes.json()
  const tailoredText = llmData.choices?.[0]?.message?.content?.trim() ?? ''

  if (!tailoredText) {
    return NextResponse.json({ error: 'Empty response from LLM' }, { status: 500 })
  }

  // Build .docx
  const doc = buildDocx(tailoredText)
  const buffer = await Packer.toBuffer(doc)

  return new Response(new Uint8Array(buffer), {
    headers: {
      'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'Content-Disposition': `attachment; filename="tailored-resume.docx"`,
    },
  })
}
