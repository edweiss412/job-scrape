'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { Spinner } from '@/components/ui/spinner'
import { TailoringSuggestionCard } from './TailoringSuggestionCard'
import type { CardState } from './TailoringSuggestionCard'
import type { TailoringSuggestionsResponse, TailoringQuestion } from '@/lib/types'

type Phase = 'loading' | 'questions' | 'suggestions' | 'generating' | 'download' | 'error'

interface AcceptedItem {
  id: string
  type: 'rewrite' | 'add' | 'remove'
  section: string
  before?: string
  finalText: string
}

interface Props {
  jobId: string
  jobTitle: string
  company: string
  onClose: () => void
}

export function ResumeTailorOverlay({ jobId, jobTitle, company, onClose }: Props) {
  const [phase, setPhase] = useState<Phase>('loading')
  const [loadingLabel, setLoadingLabel] = useState('Checking for cached results...')
  const [data, setData] = useState<TailoringSuggestionsResponse | null>(null)
  const [accepted, setAccepted] = useState<Map<string, AcceptedItem>>(new Map())
  const [skipped, setSkipped] = useState<Set<string>>(new Set())
  const [errorMsg, setErrorMsg] = useState('')
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null)
  const [previewHtml, setPreviewHtml] = useState<string | null>(null)
  const [appliedCount, setAppliedCount] = useState(0)
  const [skippedNotes, setSkippedNotes] = useState<string[]>([])
  const [isCached, setIsCached] = useState(false)
  const [questions, setQuestions] = useState<TailoringQuestion[]>([])
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const abortRef = useRef<AbortController | null>(null)

  // Escape key handler
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  // Lock body scroll
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  // Fetch questions from Gemini Flash
  const fetchQuestions = useCallback(async () => {
    setPhase('loading')
    setLoadingLabel('Generating clarifying questions...')
    abortRef.current = new AbortController()
    try {
      const res = await fetch('/api/resume-tailor/questions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jobId }),
        signal: abortRef.current!.signal,
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.error || 'Failed to generate questions')
      }
      const result = await res.json() as { questions: TailoringQuestion[] }
      setQuestions(result.questions)
      setAnswers({})
      setPhase('questions')
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      setErrorMsg(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }, [jobId])

  // Fetch suggestions from Sonnet (with optional user answers)
  const fetchSuggestions = useCallback(async (force = false, userAnswers?: Record<string, string>) => {
    setPhase('loading')
    setLoadingLabel('Analyzing your resume against this role...')
    setIsCached(false)
    setAccepted(new Map())
    setSkipped(new Set())
    abortRef.current = new AbortController()
    try {
      const res = await fetch('/api/resume-tailor/suggestions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jobId, force, userAnswers }),
        signal: abortRef.current!.signal,
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.error || 'Failed to generate suggestions')
      }
      const result = await res.json() as TailoringSuggestionsResponse & { cached?: boolean }
      setIsCached(!!result.cached)
      setData(result)
      setPhase('suggestions')
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      setErrorMsg(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }, [jobId])

  // On mount: check cache, then either show cached or fetch questions
  useEffect(() => {
    abortRef.current = new AbortController()
    async function init() {
      try {
        // Quick cache check (no LLM call)
        const res = await fetch('/api/resume-tailor/suggestions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ jobId, cacheOnly: true }),
          signal: abortRef.current!.signal,
        })
        if (!res.ok) {
          const err = await res.json()
          throw new Error(err.error || 'Failed to check cache')
        }
        const result = await res.json()
        if (result.cached) {
          // Cache hit — show suggestions immediately
          setIsCached(true)
          setData(result as TailoringSuggestionsResponse)
          setPhase('suggestions')
        } else {
          // No cache — fetch questions
          await fetchQuestions()
        }
      } catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') return
        setErrorMsg(e instanceof Error ? e.message : String(e))
        setPhase('error')
      }
    }
    init()
    return () => { abortRef.current?.abort() }
  }, [jobId, fetchQuestions])

  // Handle submitting question answers
  const handleSubmitAnswers = useCallback(() => {
    // Filter to only non-empty answers
    const filled: Record<string, string> = {}
    for (const q of questions) {
      const a = answers[q.id]?.trim()
      if (a) filled[q.question] = a
    }
    fetchSuggestions(true, Object.keys(filled).length > 0 ? filled : undefined)
  }, [questions, answers, fetchSuggestions])

  // Handle "Regenerate" from cached suggestions — go through questions flow
  const handleRegenerate = useCallback(() => {
    setData(null)
    setIsCached(false)
    fetchQuestions()
  }, [fetchQuestions])

  const handleAccept = useCallback((id: string, finalText: string) => {
    if (!data) return
    const suggestion = data.suggestions.find(s => s.id === id)
    if (!suggestion) return
    setAccepted(prev => {
      const next = new Map(prev)
      next.set(id, {
        id,
        type: suggestion.type,
        section: suggestion.section,
        before: suggestion.before,
        finalText,
      })
      return next
    })
    setSkipped(prev => { const next = new Set(prev); next.delete(id); return next })
  }, [data])

  const handleSkip = useCallback((id: string) => {
    setSkipped(prev => { const next = new Set(prev); next.add(id); return next })
    setAccepted(prev => { const next = new Map(prev); next.delete(id); return next })
  }, [])

  const handleReset = useCallback((id: string) => {
    setAccepted(prev => { const next = new Map(prev); next.delete(id); return next })
    setSkipped(prev => { const next = new Set(prev); next.delete(id); return next })
  }, [])

  const handleAcceptAll = useCallback(() => {
    if (!data) return
    setAccepted(() => {
      const next = new Map<string, AcceptedItem>()
      for (const s of data.suggestions) {
        next.set(s.id, {
          id: s.id,
          type: s.type,
          section: s.section,
          before: s.before,
          finalText: s.after,
        })
      }
      return next
    })
    setSkipped(new Set())
  }, [data])

  // Compute card status from accepted/skipped maps
  const getCardStatus = useCallback((id: string): CardState => {
    if (accepted.has(id)) return 'accepted'
    if (skipped.has(id)) return 'skipped'
    return 'pending'
  }, [accepted, skipped])

  async function handleGenerate() {
    setPhase('generating')
    try {
      const res = await fetch('/api/resume-tailor/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jobId,
          acceptedSuggestions: Array.from(accepted.values()),
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.error || 'Failed to generate resume')
      }
      const result = await res.json() as { tailoredText: string; docxBase64: string; previewHtml: string; applied: number; skipped: string[] }
      setPreviewHtml(result.previewHtml)
      setAppliedCount(result.applied)
      setSkippedNotes(result.skipped ?? [])

      // Convert base64 to downloadable blob URL
      const bytes = Uint8Array.from(atob(result.docxBase64), c => c.charCodeAt(0))
      const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })
      const url = URL.createObjectURL(blob)
      setDownloadUrl(url)
      setPhase('download')
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }

  function handleStartOver() {
    setAccepted(new Map())
    setSkipped(new Set())
    setPreviewHtml(null)
    setAppliedCount(0)
    setSkippedNotes([])
    if (downloadUrl) { URL.revokeObjectURL(downloadUrl); setDownloadUrl(null) }
    setPhase('suggestions')
  }

  // Clean up object URL on unmount
  useEffect(() => {
    return () => { if (downloadUrl) URL.revokeObjectURL(downloadUrl) }
  }, [downloadUrl])

  const acceptedCount = accepted.size
  const totalCount = data?.suggestions.length ?? 0
  const allAccepted = totalCount > 0 && acceptedCount === totalCount
  const answeredCount = questions.filter(q => answers[q.id]?.trim()).length

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/85 backdrop-blur-sm" />

      <div
        className="relative z-10 flex h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-[#2a2a2a] bg-[#0d0d0d]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-[#1f1f1f] px-5 py-3.5">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2.5">
              <span className="rounded border border-orange-800/40 bg-orange-950/30 px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-widest text-orange-400">
                Tailor
              </span>
              <h2 className="truncate text-sm font-semibold text-white" style={{ fontFamily: 'Syne, sans-serif' }}>
                Resume Tailoring
              </h2>
            </div>
            <p className="mt-0.5 truncate text-[11px] text-zinc-600">
              {jobTitle} at {company}
            </p>
          </div>
          <button
            onClick={onClose}
            className="ml-4 shrink-0 rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-[#1a1a1a] hover:text-white"
            title="Close (Esc)"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {/* Loading phase */}
          {phase === 'loading' && (
            <div className="flex h-full flex-col items-center justify-center gap-4">
              <Spinner className="h-6 w-6 text-orange-500" />
              <div className="text-center">
                <p className="text-sm text-zinc-300">{loadingLabel}</p>
                <p className="mt-1 text-[11px] text-zinc-600">This may take a moment</p>
              </div>
            </div>
          )}

          {/* Questions phase */}
          {phase === 'questions' && questions.length > 0 && (
            <div className="p-4 sm:p-5 space-y-4">
              <div className="rounded-lg border border-[#1f1f1f] bg-[#111] p-3.5">
                <p className="text-[13px] leading-relaxed text-zinc-400">
                  Before generating tailored suggestions, help us surface experience that may not be on your resume.
                  Answer what you can — skip any that don&apos;t apply.
                </p>
              </div>

              <div className="space-y-3">
                <div className="font-mono text-[9px] font-bold uppercase tracking-widest text-zinc-600">
                  Clarifying Questions ({questions.length})
                </div>
                {questions.map((q) => (
                  <div key={q.id} className="rounded-lg border border-[#1f1f1f] bg-[#111] p-4">
                    <p className="text-[13px] font-medium text-zinc-200">{q.question}</p>
                    {q.context && (
                      <p className="mt-1 text-[11px] text-zinc-600">{q.context}</p>
                    )}
                    <textarea
                      value={answers[q.id] || ''}
                      onChange={(e) => setAnswers(prev => ({ ...prev, [q.id]: e.target.value }))}
                      placeholder={q.placeholder || 'Type your answer...'}
                      rows={2}
                      className="mt-2.5 w-full rounded-md border border-[#2a2a2a] bg-[#0a0a0a] px-3 py-2 text-[12px] text-zinc-300 placeholder:text-zinc-700 focus:border-orange-800/50 focus:outline-none focus:ring-1 focus:ring-orange-900/30 resize-none"
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Suggestions phase */}
          {phase === 'suggestions' && data && (
            <div className="p-4 sm:p-5 space-y-4">
              {/* Summary */}
              {data.summary && (
                <div className="rounded-lg border border-[#1f1f1f] bg-[#111] p-3.5">
                  <p className="text-[13px] leading-relaxed text-zinc-400">{data.summary}</p>
                </div>
              )}

              {/* Cached indicator + regenerate */}
              {isCached && (
                <div className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/50 px-3.5 py-2">
                  <p className="text-[11px] text-zinc-500">
                    <span className="mr-1.5 text-zinc-600">&#x26A1;</span>
                    Loaded from cache — these are your previous suggestions for this job
                  </p>
                  <button
                    onClick={handleRegenerate}
                    className="ml-3 shrink-0 rounded-md border border-orange-800/30 bg-orange-950/20 px-2.5 py-1 text-[10px] font-medium text-orange-400 hover:bg-orange-950/40 transition-colors"
                  >
                    Regenerate
                  </button>
                </div>
              )}

              {/* ATS Keywords */}
              {data.ats_keywords.length > 0 && (
                <div>
                  <div className="mb-2 font-mono text-[9px] font-bold uppercase tracking-widest text-zinc-600">
                    ATS Keywords to Include
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {data.ats_keywords.map((kw, i) => (
                      <span
                        key={i}
                        className="rounded-full border border-cyan-900/30 bg-cyan-950/15 px-2.5 py-0.5 font-mono text-[10px] text-cyan-400"
                      >
                        {kw}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Suggestion cards */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="font-mono text-[9px] font-bold uppercase tracking-widest text-zinc-600">
                    Suggestions ({totalCount})
                  </div>
                  {!allAccepted && (
                    <button
                      onClick={handleAcceptAll}
                      className="flex items-center gap-1.5 rounded-md border border-emerald-800/30 bg-emerald-950/20 px-2.5 py-1 text-[10px] font-medium text-emerald-400 hover:bg-emerald-950/40 transition-colors"
                    >
                      <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                      </svg>
                      Accept All
                    </button>
                  )}
                </div>
                {data.suggestions.map(s => (
                  <TailoringSuggestionCard
                    key={s.id}
                    suggestion={s}
                    status={getCardStatus(s.id)}
                    onAccept={handleAccept}
                    onSkip={handleSkip}
                    onReset={handleReset}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Generating phase */}
          {phase === 'generating' && (
            <div className="flex h-full flex-col items-center justify-center gap-4">
              <Spinner className="h-6 w-6 text-emerald-500" />
              <div className="text-center">
                <p className="text-sm text-zinc-300">Applying changes and generating your resume...</p>
                <p className="mt-1 text-[11px] text-zinc-600">Building .docx file</p>
              </div>
            </div>
          )}

          {/* Download / preview phase */}
          {phase === 'download' && downloadUrl && (
            <div className="flex h-full flex-col">
              {/* Action bar */}
              <div className="shrink-0 flex items-center justify-between border-b border-[#1f1f1f] bg-[#0a0a0a] px-5 py-3">
                <div className="flex items-center gap-3">
                  <div className="rounded-full border border-emerald-800/40 bg-emerald-950/20 p-1.5">
                    <svg className="h-4 w-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-white" style={{ fontFamily: 'Syne, sans-serif' }}>
                      Resume Ready
                    </p>
                    <p className="text-[11px] text-zinc-600">
                      {appliedCount} change{appliedCount !== 1 ? 's' : ''} applied
                      {skippedNotes.length > 0 && (
                        <span className="ml-1 text-yellow-500">({skippedNotes.length} could not be matched)</span>
                      )}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <a
                    href={downloadUrl}
                    download={`tailored-resume-${company.toLowerCase().replace(/\s+/g, '-')}.docx`}
                    className="inline-flex items-center gap-2 rounded-lg border border-emerald-800/40 bg-emerald-950/30 px-4 py-2 text-xs font-medium text-emerald-400 transition-colors hover:bg-emerald-950/50"
                  >
                    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    Download .docx
                  </a>
                  <button
                    onClick={handleStartOver}
                    className="rounded-lg border border-zinc-800 px-3 py-2 text-xs font-medium text-zinc-500 transition-colors hover:text-zinc-300 hover:border-zinc-700"
                  >
                    Start Over
                  </button>
                </div>
              </div>

              {/* Resume preview */}
              <div className="flex-1 overflow-y-auto bg-[#2a2a2a] p-5 sm:p-8">
                <div
                  className="resume-preview mx-auto"
                  style={{
                    width: 680,
                    minHeight: 880,
                    background: '#fafaf8',
                    borderRadius: 4,
                    boxShadow: '0 2px 20px rgba(0,0,0,0.4)',
                    padding: '40px 48px',
                    fontFamily: 'Calibri, "Segoe UI", Arial, sans-serif',
                    color: '#1a1a1a',
                    lineHeight: 1.25,
                  }}
                >
                  {previewHtml && (
                    <div dangerouslySetInnerHTML={{ __html: previewHtml }} />
                  )}
                </div>
                <style dangerouslySetInnerHTML={{ __html: `
                  .resume-preview .rp-name {
                    text-align: center;
                    font-size: 18px;
                    font-weight: bold;
                    margin-bottom: 2px;
                  }
                  .resume-preview .rp-contact {
                    text-align: center;
                    font-size: 10px;
                    color: #555;
                    margin-bottom: 1px;
                  }
                  .resume-preview .rp-tagline {
                    text-align: center;
                    font-size: 11px;
                    font-weight: bold;
                    margin-bottom: 4px;
                  }
                  .resume-preview .rp-heading {
                    font-size: 12px;
                    font-weight: bold;
                    text-transform: uppercase;
                    border-bottom: 1px solid #ccc;
                    margin: 8px 0 3px 0;
                    padding-bottom: 1px;
                    letter-spacing: 0.3px;
                  }
                  .resume-preview .rp-subheading {
                    font-size: 11px;
                    font-weight: bold;
                    margin: 5px 0 1px 0;
                  }
                  .resume-preview .rp-job {
                    font-size: 11px;
                    margin-top: 6px;
                    margin-bottom: 1px;
                  }
                  .resume-preview .rp-location {
                    font-style: italic;
                    font-size: 10.5px;
                    margin-bottom: 1px;
                  }
                  .resume-preview .rp-bullet {
                    padding-left: 20px;
                    position: relative;
                    font-size: 10.5px;
                    margin-bottom: 1px;
                    line-height: 1.25;
                  }
                  .resume-preview .rp-bullet::before {
                    content: "\\2022";
                    position: absolute;
                    left: 8px;
                  }
                  .resume-preview .rp-body {
                    font-size: 10.5px;
                    margin: 0 0 1px 0;
                    line-height: 1.25;
                  }
                  .resume-preview .rp-spacer {
                    height: 3px;
                  }
                ` }} />
              </div>
            </div>
          )}

          {/* Error phase */}
          {phase === 'error' && (
            <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
              <div className="rounded-full border border-red-900/40 bg-red-950/20 p-3">
                <svg className="h-6 w-6 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                </svg>
              </div>
              <div className="text-center">
                <p className="text-sm text-red-400">{errorMsg || 'Something went wrong'}</p>
              </div>
              <div className="flex items-center gap-3">
                {data && (
                  <button
                    onClick={() => setPhase('suggestions')}
                    className="rounded-lg border border-zinc-800 px-4 py-2 text-xs font-medium text-zinc-400 hover:text-zinc-200 transition-colors"
                  >
                    Back to Suggestions
                  </button>
                )}
                <button
                  onClick={onClose}
                  className="rounded-lg border border-zinc-800 px-4 py-2 text-xs font-medium text-zinc-500 hover:text-zinc-300 transition-colors"
                >
                  Close
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Sticky footer — questions phase */}
        {phase === 'questions' && (
          <div className="shrink-0 border-t border-[#1f1f1f] bg-[#0a0a0a] px-5 py-3 flex items-center justify-between">
            <div className="text-[11px] text-zinc-600">
              <span className="font-mono text-orange-400">{answeredCount}</span>
              {' '}of{' '}
              <span className="font-mono">{questions.length}</span>
              {' '}answered
              <span className="ml-2 text-zinc-700">(optional — skip any)</span>
            </div>
            <button
              onClick={handleSubmitAnswers}
              className="inline-flex items-center gap-2 rounded-lg border border-orange-800/40 bg-orange-950/30 px-4 py-2 text-xs font-medium text-orange-400 transition-all hover:bg-orange-950/50"
            >
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
              </svg>
              {answeredCount > 0 ? 'Generate Suggestions' : 'Skip & Generate'}
            </button>
          </div>
        )}

        {/* Sticky footer — suggestions phase */}
        {phase === 'suggestions' && data && (
          <div className="shrink-0 border-t border-[#1f1f1f] bg-[#0a0a0a] px-5 py-3 flex items-center justify-between">
            <div className="text-[11px] text-zinc-600">
              <span className="font-mono text-emerald-500">{acceptedCount}</span>
              {' '}of{' '}
              <span className="font-mono">{totalCount}</span>
              {' '}accepted
              {skipped.size > 0 && (
                <span className="ml-2 text-zinc-700">({skipped.size} skipped)</span>
              )}
            </div>
            <button
              onClick={handleGenerate}
              disabled={acceptedCount === 0}
              className="inline-flex items-center gap-2 rounded-lg border border-emerald-800/40 bg-emerald-950/30 px-4 py-2 text-xs font-medium text-emerald-400 transition-all hover:bg-emerald-950/50 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Generate Tailored Resume
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
