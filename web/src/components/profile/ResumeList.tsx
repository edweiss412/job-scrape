'use client'

import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Resume } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { formatDate, formatFileSize } from '@/lib/utils'
import { Spinner } from '@/components/ui/spinner'
import { proseComponents } from '@/components/jobs/eval-shared'

interface ResumeListProps {
  resumes: Resume[]
  onRefresh: () => void
}

interface PreviewState {
  url: string
  filename: string
}

function ResumePreviewModal({ preview, onClose }: { preview: PreviewState; onClose: () => void }) {
  // Close on Escape
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const lower = preview.filename.toLowerCase()
  const isPdf = lower.endsWith('.pdf')
  const isTxt = lower.endsWith('.txt')
  const isWord = lower.endsWith('.docx') || lower.endsWith('.doc')

  const iframeSrc = isWord
    ? `https://view.officeapps.live.com/op/embed.aspx?src=${encodeURIComponent(preview.url)}`
    : preview.url  // pdf and txt render directly

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" />

      {/* Modal */}
      <div
        className="relative z-10 flex h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-[#2a2a2a] bg-[#111]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
          <span className="truncate text-sm font-medium text-white">{preview.filename}</span>
          <div className="ml-4 flex shrink-0 items-center gap-2">
            <a
              href={preview.url}
              download={preview.filename}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[#333] bg-border px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:bg-[#2a2a2a]"
            >
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download
            </a>
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-border hover:text-white"
              title="Close"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden">
          {(isPdf || isTxt || isWord) ? (
            <iframe
              src={iframeSrc}
              className="h-full w-full"
              title={preview.filename}
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-4 text-zinc-500">
              <svg className="h-12 w-12 text-zinc-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <p className="text-sm">Preview not available for this file type.</p>
              <a
                href={preview.url}
                download={preview.filename}
                className="inline-flex items-center gap-1.5 rounded-lg bg-white px-4 py-2 text-sm font-medium text-black transition-colors hover:bg-zinc-200"
              >
                Download to view
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ResumeEvaluationPanel({ content, evaluatedAt }: { content: string; evaluatedAt?: string | null }) {
  return (
    <div className="rounded-lg border border-[#1a1a1a] bg-[#0d0d0d] p-4">
      {evaluatedAt && (
        <p className="mb-3 text-[10px] font-mono text-zinc-600">
          Evaluated {formatDate(evaluatedAt)}
        </p>
      )}
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={proseComponents('#60a5fa')}>
        {content}
      </ReactMarkdown>
    </div>
  )
}

export function ResumeList({ resumes, onRefresh }: ResumeListProps) {
  const [loading, setLoading] = useState<string | null>(null)
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const [evalLoading, setEvalLoading] = useState<Set<string>>(new Set())
  const [expandedEvals, setExpandedEvals] = useState<Set<string>>(new Set())
  const [evalCache, setEvalCache] = useState<Record<string, { text: string; evaluatedAt: string }>>({})

  async function handleSetPrimary(id: string) {
    setLoading(`primary-${id}`)
    await fetch(`/api/resumes/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_primary: true }),
    })
    setLoading(null)
    onRefresh()
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Delete "${name}"? This cannot be undone.`)) return
    setLoading(`delete-${id}`)
    await fetch(`/api/resumes/${id}`, { method: 'DELETE' })
    setLoading(null)
    onRefresh()
  }

  async function handleDownload(id: string) {
    setLoading(`download-${id}`)
    const res = await fetch(`/api/resumes/${id}/download`)
    const { url, filename } = await res.json()
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    setLoading(null)
  }

  async function handlePreview(id: string) {
    setLoading(`preview-${id}`)
    const res = await fetch(`/api/resumes/${id}/download`)
    const { url, filename } = await res.json()
    setLoading(null)
    setPreview({ url, filename })
  }

  async function handleEvaluate(resume: Resume) {
    setEvalLoading(prev => new Set(prev).add(resume.id))
    try {
      const res = await fetch(`/api/resumes/${resume.id}/evaluate`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        setEvalCache(prev => ({
          ...prev,
          [resume.id]: { text: data.resume_evaluation, evaluatedAt: data.resume_evaluated_at },
        }))
        setExpandedEvals(prev => new Set(prev).add(resume.id))
        onRefresh()
      } else {
        const err = await res.json()
        alert(`Evaluation failed: ${err.error}`)
      }
    } finally {
      setEvalLoading(prev => {
        const next = new Set(prev)
        next.delete(resume.id)
        return next
      })
    }
  }

  function toggleEval(id: string) {
    setExpandedEvals(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  if (!resumes.length) {
    return (
      <p className="py-8 text-center text-sm text-zinc-600">
        No resumes uploaded yet.
      </p>
    )
  }

  return (
    <>
    {preview && <ResumePreviewModal preview={preview} onClose={() => setPreview(null)} />}
    <div className="divide-y divide-border">
      {resumes.map((resume) => {
        const cached = evalCache[resume.id]
        const evalText = cached?.text ?? resume.resume_evaluation
        const evalDate = cached?.evaluatedAt ?? resume.resume_evaluated_at
        const isExpanded = expandedEvals.has(resume.id)
        const isEvalLoading = evalLoading.has(resume.id)

        return (
          <div key={resume.id}>
            {/* Main row */}
            <div className="flex items-center gap-4 py-4">
              {/* File icon — clickable to preview */}
              <button
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-2 transition-colors hover:border-zinc-600 hover:bg-border"
                onClick={() => handlePreview(resume.id)}
                title="Preview"
              >
                {loading === `preview-${resume.id}` ? (
                  <Spinner className="h-4 w-4" />
                ) : (
                  <svg className="h-5 w-5 text-zinc-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                )}
              </button>

              {/* Info */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <button
                    className="truncate text-sm font-medium text-white hover:text-zinc-300"
                    onClick={() => handlePreview(resume.id)}
                  >
                    {resume.name}
                  </button>
                  {resume.is_primary && (
                    <span className="shrink-0 rounded-full border border-emerald-800 bg-emerald-950/60 px-2 py-0.5 font-mono text-[10px] font-semibold text-emerald-400">
                      PRIMARY
                    </span>
                  )}
                  {evalText && (
                    <span className="shrink-0 rounded-full border border-blue-800 bg-blue-950/60 px-2 py-0.5 font-mono text-[10px] font-semibold text-blue-400">
                      EVALUATED
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-xs text-zinc-600">
                  {resume.file_name}
                  {resume.file_size ? ` · ${formatFileSize(resume.file_size)}` : ''}
                  {' · '}Uploaded {formatDate(resume.created_at)}
                </p>
              </div>

              {/* Actions */}
              <div className="flex shrink-0 items-center gap-1.5">
                {/* Evaluate / toggle button */}
                {evalText ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => toggleEval(resume.id)}
                    title={isExpanded ? 'Collapse evaluation' : 'Expand evaluation'}
                  >
                    {isExpanded ? '▲' : '▼'} Eval
                  </Button>
                ) : (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleEvaluate(resume)}
                    disabled={isEvalLoading}
                  >
                    {isEvalLoading ? <Spinner className="h-3 w-3" /> : null}
                    Evaluate
                  </Button>
                )}

                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleDownload(resume.id)}
                  disabled={loading === `download-${resume.id}`}
                  title="Download"
                >
                  {loading === `download-${resume.id}` ? <Spinner className="h-3.5 w-3.5" /> : (
                    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                  )}
                </Button>

                {!resume.is_primary && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleSetPrimary(resume.id)}
                    disabled={loading === `primary-${resume.id}`}
                  >
                    {loading === `primary-${resume.id}` ? <Spinner className="h-3 w-3" /> : null}
                    Set primary
                  </Button>
                )}

                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => handleDelete(resume.id, resume.name)}
                  disabled={!!loading}
                  title="Delete"
                >
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </Button>
              </div>
            </div>

            {/* Evaluation panel */}
            {isExpanded && evalText && (
              <div className="border-t border-[#1a1a1a] pb-4 pt-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-[10px] font-mono font-semibold uppercase tracking-wider text-blue-400">
                    Resume Evaluation
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleEvaluate(resume)}
                    disabled={isEvalLoading}
                  >
                    {isEvalLoading ? <Spinner className="h-3 w-3" /> : null}
                    Re-evaluate
                  </Button>
                </div>
                <ResumeEvaluationPanel content={evalText} evaluatedAt={evalDate} />
              </div>
            )}
          </div>
        )
      })}
    </div>
    </>
  )
}
