import { createServerClient } from '@supabase/ssr'
import { createClient } from '@supabase/supabase-js'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { extractResumeText } from '@/lib/resume-extract'
import {
  Document, Packer, Paragraph, TextRun,
  HeadingLevel, AlignmentType,
} from 'docx'

export const maxDuration = 120

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
 * "Professional Experience > Freelance Audio Engineer" or
 * "Technical Proficiencies > New subsection after 'Networking & Protocols'".
 *
 * Strategy: find the target text, then scan forward to find the end of that
 * sub-section (next ALL-CAPS heading, or next job entry for sub-sections
 * within Professional Experience). Insert just before the boundary.
 */
function findInsertionIndex(lines: string[], sectionPath: string): number {
  const parts = sectionPath.split('>').map(p => p.trim())
  let target = parts[parts.length - 1]
  const isSubSection = parts.length > 1

  // Handle "New subsection after 'X'" pattern — extract the reference section name
  const afterMatch = target.match(/[Nn]ew subsection after ['"](.+?)['"]/i)
    || target.match(/[Aa]fter ['"](.+?)['"]/i)
  if (afterMatch) {
    target = afterMatch[1]
  }

  // Find the line containing the target (case-insensitive, normalized)
  let targetIdx = -1
  const normTarget = target.toLowerCase()
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].toLowerCase().includes(normTarget)) {
      targetIdx = i
      break
    }
  }

  // Fallback: try matching the parent section if target not found
  if (targetIdx === -1 && parts.length > 1) {
    const parentTarget = parts[0].toLowerCase()
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].toLowerCase().includes(parentTarget)) {
        targetIdx = i
        break
      }
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
    if (isSubSection && !afterMatch && isJobEntry(trimmed)) {
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

/** Normalize a single character for fuzzy matching. */
function normChar(ch: string): string {
  if ('\u2013\u2014\u2015\u2012'.includes(ch)) return '-'
  if ('\u2018\u2019\u201A'.includes(ch)) return "'"
  if ('\u201C\u201D\u201E'.includes(ch)) return '"'
  if ('\u00A0\u202F\u2009'.includes(ch)) return ' '
  if (ch === '\u2026') return '...'
  return ch
}

/**
 * Build a normalized version of a string while tracking which original
 * character produced each normalized character. Returns the normalized
 * string and an array where origIndices[i] is the index in the original
 * string that produced normalized character i.
 */
function buildNormMap(original: string): { normalized: string; origIndices: number[] } {
  const normChars: string[] = []
  const origIndices: number[] = []
  let prevWasSpace = false
  let lineStart = true

  for (let i = 0; i < original.length; i++) {
    const raw = original[i]

    // Newlines: preserve them but trim trailing spaces from the line
    if (raw === '\n') {
      while (normChars.length > 0 && normChars[normChars.length - 1] === ' ') {
        normChars.pop()
        origIndices.pop()
      }
      normChars.push('\n')
      origIndices.push(i)
      lineStart = true
      prevWasSpace = false
      continue
    }

    const nc = normChar(raw)

    // Handle multi-char expansions (e.g. ellipsis → "...")
    if (nc.length > 1) {
      // Skip if this would be at the start of a line (unlikely for ellipsis)
      for (const c of nc) {
        normChars.push(c)
        origIndices.push(i)
      }
      prevWasSpace = false
      lineStart = false
      continue
    }

    const ch = nc

    // Skip leading spaces on a line (trim left)
    if (lineStart && ch === ' ') continue

    // Collapse consecutive spaces
    if (ch === ' ') {
      if (prevWasSpace) continue
      prevWasSpace = true
    } else {
      prevWasSpace = false
      lineStart = false
    }

    normChars.push(ch)
    origIndices.push(i)
  }

  // Trim trailing spaces from last line
  while (normChars.length > 0 && normChars[normChars.length - 1] === ' ') {
    normChars.pop()
    origIndices.pop()
  }

  return { normalized: normChars.join(''), origIndices }
}

/**
 * Find `needle` in `haystack` using normalized comparison, returning the
 * start and end positions in the *original* haystack. This lets us replace
 * the exact original characters even when the LLM substituted ASCII
 * equivalents for Unicode dashes, quotes, or whitespace.
 */
function fuzzyFind(haystack: string, needle: string): { start: number; end: number } | null {
  const { normalized: normHaystack, origIndices } = buildNormMap(haystack)
  const { normalized: normNeedle } = buildNormMap(needle)

  const idx = normHaystack.indexOf(normNeedle)
  if (idx === -1) return null

  const origStart = origIndices[idx]
  const lastNormIdx = idx + normNeedle.length - 1
  // End is one past the last original character that contributed to the match
  const origEnd = origIndices[lastNormIdx] + 1

  return { start: origStart, end: origEnd }
}

/**
 * Apply all accepted suggestions to the resume text using pure string
 * operations — no LLM involved, so no risk of unintended formatting drift.
 * Uses normalized matching to tolerate Unicode dashes/quotes/whitespace
 * differences between LLM-generated text and the original .docx content.
 */
function applyChanges(
  resumeText: string,
  suggestions: AcceptedSuggestion[],
): { text: string; applied: number; skipped: string[] } {
  let text = resumeText
  const skipped: string[] = []

  // Pass 1: rewrites and removes (direct string replacement with fuzzy matching)
  for (const s of suggestions) {
    if (s.type === 'rewrite' && s.before) {
      // Try exact match first, then fuzzy
      if (text.includes(s.before)) {
        text = text.replace(s.before, s.finalText)
      } else {
        const match = fuzzyFind(text, s.before)
        if (match) {
          text = text.slice(0, match.start) + s.finalText + text.slice(match.end)
        } else {
          skipped.push(`rewrite: could not find "${s.before.slice(0, 60)}..."`)
        }
      }
    } else if (s.type === 'remove' && s.before) {
      if (text.includes(s.before)) {
        text = text.replace(s.before, '')
        text = text.replace(/\n{3,}/g, '\n\n')
      } else {
        const match = fuzzyFind(text, s.before)
        if (match) {
          text = text.slice(0, match.start) + text.slice(match.end)
          text = text.replace(/\n{3,}/g, '\n\n')
        } else {
          skipped.push(`remove: could not find "${s.before.slice(0, 60)}..."`)
        }
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
// HTML parsing — extract formatting info from mammoth HTML output
// ---------------------------------------------------------------------------

interface FormattedRun {
  text: string
  bold?: boolean
  italic?: boolean
}

interface FormattedBlock {
  text: string       // plain text content
  isBullet: boolean
  runs: FormattedRun[]
}

function decodeHtmlEntities(s: string): string {
  return s
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, '\u00A0')
}

/** Parse inline <strong>/<em> tags into formatted runs. */
function parseInlineRuns(html: string): FormattedRun[] {
  const runs: FormattedRun[] = []
  let bold = false
  let italic = false
  let buf = ''
  let i = 0

  function flush() {
    if (buf) {
      const run: FormattedRun = { text: decodeHtmlEntities(buf) }
      if (bold) run.bold = true
      if (italic) run.italic = true
      runs.push(run)
      buf = ''
    }
  }

  while (i < html.length) {
    if (html.startsWith('<strong>', i)) {
      flush(); bold = true; i += 8
    } else if (html.startsWith('</strong>', i)) {
      flush(); bold = false; i += 9
    } else if (html.startsWith('<em>', i)) {
      flush(); italic = true; i += 4
    } else if (html.startsWith('</em>', i)) {
      flush(); italic = false; i += 5
    } else if (html[i] === '<') {
      // Skip unknown tags (e.g. <br/>)
      const end = html.indexOf('>', i)
      if (end !== -1) i = end + 1
      else i++
    } else {
      buf += html[i]; i++
    }
  }
  flush()
  return runs.filter(r => r.text)
}

/** Parse mammoth HTML into structured blocks preserving bullet/bold/italic info. */
function parseResumeHtml(html: string): FormattedBlock[] {
  const blocks: FormattedBlock[] = []
  const regex = /<(p|li)>([\s\S]*?)<\/\1>/g
  let m
  while ((m = regex.exec(html)) !== null) {
    const isBullet = m[1] === 'li'
    const runs = parseInlineRuns(m[2])
    const text = runs.map(r => r.text).join('')
    blocks.push({ text, isBullet, runs })
  }
  return blocks
}

/** Normalize text for format-map key lookup (handles Unicode differences). */
function normalizeForLookup(text: string): string {
  return text.toLowerCase().replace(/\s+/g, ' ').trim()
    .replace(/[\u2013\u2014\u2015\u2012]/g, '-')
    .replace(/[\u2018\u2019\u201A]/g, "'")
    .replace(/[\u201C\u201D\u201E]/g, '"')
    .replace(/[\u00A0\u202F\u2009]/g, ' ')
}

/** Build a lookup map from normalized text → original formatting. */
function buildFormatMap(blocks: FormattedBlock[]): Map<string, FormattedBlock> {
  const map = new Map<string, FormattedBlock>()
  for (const block of blocks) {
    const key = normalizeForLookup(block.text)
    if (key && !map.has(key)) {
      map.set(key, block)
    }
  }
  return map
}

/** Convert FormattedRun[] to TextRun[] for docx, applying a default font size. */
function runsToTextRuns(runs: FormattedRun[], size: number): TextRun[] {
  return runs.map(r => new TextRun({
    text: r.text,
    bold: r.bold || undefined,
    italics: r.italic || undefined,
    size,
    font: 'Calibri',
  }))
}

// ---------------------------------------------------------------------------
// .docx builder — uses original HTML format map + context heuristics
// ---------------------------------------------------------------------------

function buildDocx(text: string, originalHtml?: string | null): Document {
  // Parse original HTML for formatting info
  const blocks = originalHtml ? parseResumeHtml(originalHtml) : []
  const formatMap = buildFormatMap(blocks)

  const lines = text.split('\n')
  const children: Paragraph[] = []

  // Section context tracking
  let inExperience = false
  let bulletMode = false
  let justSawJobEntry = false
  let lineAfterJobEntry = false  // true for the first non-blank line after a job entry

  for (const line of lines) {
    const trimmed = line.trim()

    if (!trimmed) {
      children.push(new Paragraph({ spacing: { after: 100 } }))
      continue
    }

    const isAllCaps = isSectionHeading(trimmed)
    const isJob = isJobEntry(trimmed)

    // Look up formatting from original HTML
    const key = normalizeForLookup(trimmed)
    const fmt = formatMap.get(key)

    // --- Section headings (ALL-CAPS) ---
    if (isAllCaps) {
      inExperience = trimmed.includes('EXPERIENCE')
      bulletMode = false
      justSawJobEntry = false
      lineAfterJobEntry = false

      children.push(new Paragraph({
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 240, after: 80 },
        children: [new TextRun({ text: trimmed, bold: true, size: 24, font: 'Calibri' })],
      }))
      continue
    }

    // --- Name line (first non-empty) ---
    if (children.length === 0) {
      children.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 60 },
        children: [new TextRun({ text: trimmed, bold: true, size: 28, font: 'Calibri' })],
      }))
      continue
    }

    // --- Contact info near top ---
    if (children.length < 5 && trimmed.length < 100 && (trimmed.includes('@') || /^\d{3}/.test(trimmed) || trimmed.includes('linkedin'))) {
      children.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 40 },
        children: [new TextRun({ text: trimmed, size: 20, font: 'Calibri', color: '555555' })],
      }))
      continue
    }

    // --- Title/tagline near top (e.g. "Live Audio Engineer · A1 · RF Coordinator") ---
    if (children.length < 5 && trimmed.includes('·')) {
      children.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 60 },
        children: [new TextRun({ text: trimmed, bold: true, size: 22, font: 'Calibri' })],
      }))
      continue
    }

    // --- Job entry header (has year range, in experience section) ---
    if (isJob && inExperience) {
      justSawJobEntry = true
      lineAfterJobEntry = true
      bulletMode = false

      if (fmt && fmt.runs.length > 1) {
        // Use original formatting (e.g. bold title + regular date)
        children.push(new Paragraph({
          spacing: { before: 200, after: 40 },
          children: runsToTextRuns(fmt.runs, 22),
        }))
      } else {
        // Heuristic: split "Title Date" — bold the title part
        const jobMatch = trimmed.match(/^(.+?)\s+((?:Oct |Nov |Dec |Jan |Feb |Mar |Apr |May |Jun |Jul |Aug |Sep )?\d{4}[–-].+)$/)
        if (jobMatch) {
          children.push(new Paragraph({
            spacing: { before: 200, after: 40 },
            children: [
              new TextRun({ text: jobMatch[1] + ' ', bold: true, size: 22, font: 'Calibri' }),
              new TextRun({ text: jobMatch[2], size: 22, font: 'Calibri' }),
            ],
          }))
        } else {
          children.push(new Paragraph({
            spacing: { before: 200, after: 40 },
            children: [new TextRun({ text: trimmed, bold: true, size: 22, font: 'Calibri' })],
          }))
        }
      }
      continue
    }

    // --- Location line (first non-blank after a job entry) ---
    if (inExperience && lineAfterJobEntry) {
      lineAfterJobEntry = false
      bulletMode = true  // After location, all content is bullets

      children.push(new Paragraph({
        spacing: { after: 40 },
        children: [new TextRun({ text: trimmed, italics: true, size: 21, font: 'Calibri' })],
      }))
      continue
    }

    // --- Bullet: format map says so, or context says so (experience section) ---
    const shouldBeBullet = fmt?.isBullet || (bulletMode && inExperience)
      || trimmed.startsWith('-') || trimmed.startsWith('•') || trimmed.startsWith('*')

    if (shouldBeBullet) {
      const bulletText = trimmed.replace(/^[-•*]\s*/, '')

      if (fmt && fmt.runs.length > 0) {
        children.push(new Paragraph({
          bullet: { level: 0 },
          spacing: { after: 40 },
          children: runsToTextRuns(fmt.runs, 21),
        }))
      } else {
        children.push(new Paragraph({
          bullet: { level: 0 },
          spacing: { after: 40 },
          children: [new TextRun({ text: bulletText, size: 21, font: 'Calibri' })],
        }))
      }
      continue
    }

    // --- Sub-heading: format map says all-bold, or heuristic ---
    const fmtAllBold = fmt && fmt.runs.length > 0 && fmt.runs.every(r => r.bold)
    const isHeuristicSubHeading = !fmt && trimmed.length < 50
      && !trimmed.includes(',') && !trimmed.includes(';')
      && !/\d{4}/.test(trimmed) && !trimmed.includes('@')

    if (fmtAllBold || isHeuristicSubHeading) {
      children.push(new Paragraph({
        spacing: { before: 160, after: 60 },
        children: [new TextRun({ text: trimmed, bold: true, size: 22, font: 'Calibri' })],
      }))
      continue
    }

    // --- Mixed formatting from format map (e.g. bold label + normal content) ---
    if (fmt && fmt.runs.some(r => r.bold || r.italic)) {
      children.push(new Paragraph({
        spacing: { after: 60 },
        children: runsToTextRuns(fmt.runs, 21),
      }))
      continue
    }

    // --- All-italic from format map ---
    const fmtAllItalic = fmt && fmt.runs.length > 0 && fmt.runs.every(r => r.italic)
    if (fmtAllItalic) {
      children.push(new Paragraph({
        spacing: { after: 60 },
        children: [new TextRun({ text: trimmed, italics: true, size: 21, font: 'Calibri' })],
      }))
      continue
    }

    // --- Regular paragraph ---
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

  const { text: resumeText, html: resumeHtml } = await extractResumeText(adminClient, resume, { includeHtml: true })
  if (!resumeText) {
    return NextResponse.json({ error: 'Could not extract text from your resume' }, { status: 422 })
  }

  // Apply changes programmatically — no LLM, no formatting drift
  const { text: tailoredText, applied, skipped } = applyChanges(resumeText, acceptedSuggestions)

  // Build .docx using original HTML for formatting preservation
  const doc = buildDocx(tailoredText, resumeHtml)
  const buffer = await Packer.toBuffer(doc)
  const docxBase64 = Buffer.from(buffer).toString('base64')

  return NextResponse.json({ tailoredText, docxBase64, applied, skipped })
}
