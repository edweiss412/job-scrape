import { createServerClient } from '@supabase/ssr'
import { createClient } from '@supabase/supabase-js'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { extractResumeText } from '@/lib/resume-extract'
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

// ---------------------------------------------------------------------------
// Programmatic resume editing — no LLM, no drift
// ---------------------------------------------------------------------------

/** Check if a line is an ALL-CAPS section heading (e.g. PROFESSIONAL EXPERIENCE) */
function isSectionHeading(line: string): boolean {
  const t = line.trim()
  return t.length > 2 && t === t.toUpperCase() && /[A-Z]/.test(t)
}

/** Check if a line looks like a job entry header (contains a year range) */
function isJobEntry(line: string): boolean {
  return /\d{4}[–-](Present|\d{4})/.test(line.trim())
}

/**
 * Find the insertion index for an "add" suggestion within the resume lines.
 * The section path looks like "Technical Proficiencies" or
 * "Professional Experience > Freelance Audio Engineer".
 *
 * Strategy: find the target text, then scan forward to find the end of that
 * sub-section (next ALL-CAPS heading, or next job entry for sub-sections
 * within Professional Experience). Insert just before the boundary.
 */
function findInsertionIndex(lines: string[], sectionPath: string): number {
  const parts = sectionPath.split('>').map(p => p.trim())
  const target = parts[parts.length - 1]
  const isSubSection = parts.length > 1

  // Find the line containing the target
  let targetIdx = -1
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes(target)) {
      targetIdx = i
      break
    }
  }
  if (targetIdx === -1) return -1

  // Scan forward to find the section boundary
  let insertIdx = lines.length
  for (let i = targetIdx + 1; i < lines.length; i++) {
    const trimmed = lines[i].trim()
    if (!trimmed) continue

    if (isSectionHeading(trimmed)) {
      insertIdx = i
      break
    }
    // For sub-sections within a parent (e.g. job entries), also stop at the
    // next job entry that isn't the target itself
    if (isSubSection && isJobEntry(trimmed)) {
      insertIdx = i
      break
    }
  }

  // Walk back past trailing blank lines so we insert at the end of content
  while (insertIdx > 0 && !lines[insertIdx - 1].trim()) {
    insertIdx--
  }

  return insertIdx
}

/**
 * Apply all accepted suggestions to the resume text using pure string
 * operations — no LLM involved, so no risk of unintended formatting drift.
 */
function applyChanges(
  resumeText: string,
  suggestions: AcceptedSuggestion[],
): { text: string; applied: number; skipped: string[] } {
  let text = resumeText
  const skipped: string[] = []

  // Pass 1: rewrites and removes (direct string replacement)
  for (const s of suggestions) {
    if (s.type === 'rewrite' && s.before) {
      if (text.includes(s.before)) {
        text = text.replace(s.before, s.finalText)
      } else {
        skipped.push(`rewrite: could not find "${s.before.slice(0, 60)}..."`)
      }
    } else if (s.type === 'remove' && s.before) {
      if (text.includes(s.before)) {
        // Remove the text and clean up any resulting triple+ newlines
        text = text.replace(s.before, '')
        text = text.replace(/\n{3,}/g, '\n\n')
      } else {
        skipped.push(`remove: could not find "${s.before.slice(0, 60)}..."`)
      }
    }
  }

  // Pass 2: adds (section-aware insertion)
  for (const s of suggestions) {
    if (s.type !== 'add') continue

    const lines = text.split('\n')
    const idx = findInsertionIndex(lines, s.section)
    if (idx !== -1) {
      lines.splice(idx, 0, s.finalText)
      text = lines.join('\n')
    } else {
      skipped.push(`add to "${s.section}": section not found`)
    }
  }

  const applied = suggestions.length - skipped.length
  return { text: text.trim(), applied, skipped }
}

// ---------------------------------------------------------------------------
// .docx builder
// ---------------------------------------------------------------------------

function buildDocx(text: string): Document {
  const lines = text.split('\n')
  const children: Paragraph[] = []

  for (const line of lines) {
    const trimmed = line.trim()

    if (!trimmed) {
      children.push(new Paragraph({ spacing: { after: 100 } }))
      continue
    }

    const isAllCaps = isSectionHeading(trimmed)
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

// ---------------------------------------------------------------------------
// Route handler
// ---------------------------------------------------------------------------

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

  // Apply changes programmatically — no LLM, no formatting drift
  const { text: tailoredText, applied, skipped } = applyChanges(resumeText, acceptedSuggestions)

  // Build .docx
  const doc = buildDocx(tailoredText)
  const buffer = await Packer.toBuffer(doc)
  const docxBase64 = Buffer.from(buffer).toString('base64')

  return NextResponse.json({ tailoredText, docxBase64, applied, skipped })
}
