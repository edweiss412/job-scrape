import type { SupabaseClient } from '@supabase/supabase-js'

interface ResumeForExtract {
  file_path: string
  file_name: string
  content_text?: string | null
}

export async function extractResumeText(
  adminClient: SupabaseClient,
  resume: ResumeForExtract,
  opts?: { includeHtml?: boolean; includeBuffer?: boolean },
): Promise<{ text: string | null; html: string | null; buffer: Buffer | null; error: string | null }> {
  // Fast path for plain text (skip when HTML or buffer is requested — need to download)
  if (!opts?.includeHtml && !opts?.includeBuffer && resume.content_text && resume.content_text.length > 100) {
    return { text: resume.content_text, html: null, buffer: null, error: null }
  }

  // Download from storage
  const { data: fileData, error: downloadError } = await adminClient.storage
    .from('resumes')
    .download(resume.file_path)

  if (downloadError || !fileData) {
    return { text: null, html: null, buffer: null, error: downloadError?.message ?? 'Failed to download file' }
  }

  const lower = resume.file_name.toLowerCase()

  if (lower.endsWith('.pdf')) {
    try {
      const buffer = Buffer.from(await fileData.arrayBuffer())
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const pdfParse: (buf: Buffer) => Promise<{ text: string }> = require('pdf-parse')
      const result = await pdfParse(buffer)
      const text = result.text?.trim() ?? ''
      if (text.length < 100) {
        return { text: null, html: null, buffer: null, error: 'PDF appears to have no extractable text (may be image-based)' }
      }
      return { text, html: null, buffer: opts?.includeBuffer ? buffer : null, error: null }
    } catch (e) {
      return { text: null, html: null, buffer: null, error: `PDF extraction failed: ${e instanceof Error ? e.message : String(e)}` }
    }
  }

  if (lower.endsWith('.docx') || lower.endsWith('.doc')) {
    try {
      const buffer = Buffer.from(await fileData.arrayBuffer())
      const mammoth = await import('mammoth')
      const textResult = await mammoth.extractRawText({ buffer })
      const text = textResult.value?.trim() ?? ''
      if (text.length < 100) {
        return { text: null, html: null, buffer: null, error: 'Document appears to have no extractable text' }
      }
      let html: string | null = null
      if (opts?.includeHtml) {
        const htmlResult = await mammoth.convertToHtml({ buffer })
        html = htmlResult.value ?? null
      }
      return { text, html, buffer: opts?.includeBuffer ? buffer : null, error: null }
    } catch (e) {
      return { text: null, html: null, buffer: null, error: `DOCX extraction failed: ${e instanceof Error ? e.message : String(e)}` }
    }
  }

  // Fallback: try as plain text
  try {
    const text = await fileData.text()
    if (text.length < 100) {
      return { text: null, html: null, buffer: null, error: 'File has no extractable text' }
    }
    return { text: text.trim(), html: null, buffer: null, error: null }
  } catch {
    return { text: null, html: null, buffer: null, error: 'Unsupported file type for text extraction' }
  }
}
