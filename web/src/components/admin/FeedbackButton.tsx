'use client'

import { useState, useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { ADMIN_EMAIL, canSubmitFeedback } from '@/lib/admin'
import { FeedbackPriority, FeedbackType } from '@/lib/types'

interface FormState {
  type: FeedbackType | null
  title: string
  description: string
  priority: FeedbackPriority
  steps_to_reproduce: string
  expected_behavior: string
  actual_behavior: string
  use_case: string
  user_impact: string
}

type SuggestField = 'description' | 'use_case' | 'user_impact' | 'steps_to_reproduce' | 'expected_behavior' | 'actual_behavior'

const INITIAL: FormState = {
  type: null,
  title: '',
  description: '',
  priority: 'medium',
  steps_to_reproduce: '',
  expected_behavior: '',
  actual_behavior: '',
  use_case: '',
  user_impact: '',
}

// Sparkle button shown next to field labels
function AISuggestButton({
  field,
  disabled,
  loading,
  onSuggest,
}: {
  field: SuggestField
  disabled: boolean
  loading: boolean
  onSuggest: (field: SuggestField) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onSuggest(field)}
      disabled={disabled || loading}
      title={disabled ? 'Enter a title first' : 'AI suggest'}
      className={`flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[10px] transition-all ${
        loading
          ? 'text-violet-400 cursor-wait'
          : disabled
            ? 'text-zinc-700 cursor-not-allowed'
            : 'text-zinc-600 hover:bg-violet-950/30 hover:text-violet-400 cursor-pointer'
      }`}
    >
      {loading ? (
        <svg className="h-2.5 w-2.5 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      ) : (
        <svg className="h-2.5 w-2.5" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6z" />
        </svg>
      )}
      {loading ? 'thinking…' : 'AI'}
    </button>
  )
}

// Field label row with optional AI button
function FieldLabel({
  label,
  required,
  field,
  suggesting,
  titleEmpty,
  onSuggest,
}: {
  label: string
  required?: boolean
  field: SuggestField
  suggesting: SuggestField | null
  titleEmpty: boolean
  onSuggest: (f: SuggestField) => void
}) {
  return (
    <div className="mb-1.5 flex items-center gap-2">
      <label className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">
        {label}
        {required && <span className="ml-1 text-zinc-700">*</span>}
      </label>
      <AISuggestButton
        field={field}
        disabled={titleEmpty}
        loading={suggesting === field}
        onSuggest={onSuggest}
      />
    </div>
  )
}

// Screenshot section shown in bug form
function ScreenshotSection({
  screenshot,
  includeScreenshot,
  capturing,
  onToggle,
  onRetake,
  onRemove,
  onFileUpload,
}: {
  screenshot: string | null
  includeScreenshot: boolean
  capturing: boolean
  onToggle: () => void
  onRetake: () => void
  onRemove: () => void
  onFileUpload: (dataUrl: string) => void
}) {
  const fileInputRef = useRef<HTMLInputElement>(null)

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      const result = ev.target?.result
      if (typeof result === 'string') onFileUpload(result)
    }
    reader.readAsDataURL(file)
    // reset so same file can be re-selected
    e.target.value = ''
  }

  return (
    <div className="rounded-lg border border-border bg-background">
      {/* Header row */}
      <div className="flex items-center justify-between px-3 py-2">
        <div className="flex items-center gap-2">
          <label className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">
            Screenshot
          </label>
          {capturing && (
            <span className="flex items-center gap-1 font-mono text-[10px] text-amber-500">
              <svg className="h-2.5 w-2.5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              capturing…
            </span>
          )}
        </div>

        {/* Include toggle */}
        {screenshot && !capturing && (
          <button
            type="button"
            onClick={onToggle}
            className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[10px] transition-all ${
              includeScreenshot
                ? 'border-emerald-900/50 bg-emerald-950/20 text-emerald-500'
                : 'border-border text-zinc-600 hover:border-[#2a2a2a] hover:text-zinc-400'
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full transition-colors ${includeScreenshot ? 'bg-emerald-500' : 'bg-zinc-700'}`} />
            {includeScreenshot ? 'included' : 'excluded'}
          </button>
        )}
      </div>

      {/* Body */}
      {capturing ? (
        <div className="flex items-center justify-center px-3 pb-3 pt-1">
          <div className="h-16 w-full animate-pulse rounded bg-zinc-900" />
        </div>
      ) : screenshot ? (
        <div className="px-3 pb-3">
          {/* Thumbnail */}
          <div className={`relative overflow-hidden rounded-lg border transition-all ${includeScreenshot ? 'border-zinc-700' : 'border-border opacity-40'}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={screenshot}
              alt="Page screenshot"
              className="w-full object-cover"
              style={{ maxHeight: '120px', objectPosition: 'top' }}
            />
            {!includeScreenshot && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/60">
                <span className="font-mono text-[10px] text-zinc-500">excluded from report</span>
              </div>
            )}
          </div>
          {/* Actions */}
          <div className="mt-2 flex items-center gap-3">
            <button
              type="button"
              onClick={onRetake}
              className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
            >
              ↺ Retake
            </button>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
            >
              ↑ Upload instead
            </button>
            <button
              type="button"
              onClick={onRemove}
              className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-red-500"
            >
              Remove
            </button>
          </div>
        </div>
      ) : (
        /* No screenshot — file upload fallback */
        <div className="px-3 pb-3">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-zinc-800 bg-zinc-950 py-4 text-zinc-600 transition-colors hover:border-zinc-700 hover:text-zinc-400"
          >
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <span className="font-mono text-[10px]">Upload screenshot</span>
          </button>
          <button
            type="button"
            onClick={onRetake}
            className="mt-1.5 w-full text-center font-mono text-[10px] text-zinc-700 transition-colors hover:text-zinc-500"
          >
            or auto-capture page
          </button>
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleFile}
      />
    </div>
  )
}

export function AdminFeedbackButton() {
  const [canSubmit, setCanSubmit] = useState(false)
  const [currentIsAdmin, setCurrentIsAdmin] = useState(false)
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<1 | 2>(1)
  const [form, setForm] = useState<FormState>(INITIAL)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [suggesting, setSuggesting] = useState<SuggestField | null>(null)
  const [suggestError, setSuggestError] = useState<string | null>(null)
  const [capturing, setCapturing] = useState(false)
  const [screenshot, setScreenshot] = useState<string | null>(null)
  const [includeScreenshot, setIncludeScreenshot] = useState(true)
  const pathname = usePathname()

  useEffect(() => {
    createClient()
      .auth.getUser()
      .then(({ data }) => {
        setCanSubmit(canSubmitFeedback(data.user))
        setCurrentIsAdmin(data.user?.email === ADMIN_EMAIL)
      })
  }, [])

  async function captureScreenshot(): Promise<string | null> {
    try {
      const html2canvas = (await import('html2canvas')).default
      const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), 8000))
      const capture = html2canvas(document.body, {
        scale: 0.5,
        useCORS: true,
        allowTaint: false,
        logging: false,
        ignoreElements: (el) => el.classList.contains('feedback-modal-ignore'),
      }).then((canvas) => canvas.toDataURL('image/jpeg', 0.7)).catch(() => null)
      return await Promise.race([capture, timeout])
    } catch {
      return null
    }
  }

  async function handleOpen() {
    // Open modal immediately — don't block on capture
    setOpen(true)
    setStep(1)
    setForm(INITIAL)
    setSubmitted(false)
    setSuggesting(null)
    setIncludeScreenshot(true)
    setScreenshot(null)

    // Capture in background (modal is already visible with "capturing…" state)
    setCapturing(true)
    try {
      const dataUrl = await captureScreenshot()
      setScreenshot(dataUrl)
    } finally {
      setCapturing(false)
    }
  }

  async function handleRetake() {
    setCapturing(true)
    const dataUrl = await captureScreenshot()
    setScreenshot(dataUrl)
    setCapturing(false)
  }

  function handleClose() {
    if (submitting) return
    setOpen(false)
  }

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function suggest(field: SuggestField) {
    if (!form.title.trim() || !form.type) return
    setSuggesting(field)
    setSuggestError(null)
    try {
      const res = await fetch('/api/feedback/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: form.title,
          type: form.type,
          field,
          currentValues: {
            description: form.description,
            use_case: form.use_case,
            user_impact: form.user_impact,
            steps_to_reproduce: form.steps_to_reproduce,
            expected_behavior: form.expected_behavior,
            actual_behavior: form.actual_behavior,
          },
          // Pass screenshot to vision model if bug type and screenshot is included
          screenshotBase64: form.type === 'bug' && includeScreenshot && screenshot ? screenshot : undefined,
        }),
      })
      const data = await res.json()
      if (data.suggestion) {
        set(field, data.suggestion)
      } else {
        setSuggestError(data.error ?? 'No suggestion returned')
        setTimeout(() => setSuggestError(null), 4000)
      }
    } catch {
      setSuggestError('Network error — try again')
      setTimeout(() => setSuggestError(null), 4000)
    } finally {
      setSuggesting(null)
    }
  }

  async function handleSubmit() {
    if (!form.type || !form.title.trim() || !form.description.trim()) return
    setSubmitting(true)
    try {
      let screenshotUrl: string | null = null

      // Upload screenshot to Supabase Storage if bug type and screenshot included
      if (form.type === 'bug' && includeScreenshot && screenshot) {
        try {
          const supabase = createClient()
          const blob = await fetch(screenshot).then((r) => r.blob())
          const path = `screenshots/${Date.now()}.jpg`
          const { data, error } = await supabase.storage
            .from('feedback-screenshots')
            .upload(path, blob, { contentType: 'image/jpeg' })
          if (!error && data) {
            const { data: urlData } = supabase.storage
              .from('feedback-screenshots')
              .getPublicUrl(path)
            screenshotUrl = urlData.publicUrl
          }
        } catch {
          // Non-fatal: continue without screenshot URL
        }
      }

      await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form,
          page_url: typeof window !== 'undefined' ? window.location.href : pathname,
          screenshot_url: screenshotUrl,
        }),
      })
      setSubmitted(true)
      setTimeout(() => setOpen(false), 1500)
    } finally {
      setSubmitting(false)
    }
  }

  if (!canSubmit) return null

  const titleEmpty = !form.title.trim()
  const canSubmitForm = !titleEmpty && form.description.trim() && !submitting

  const textareaClass =
    'w-full resize-none rounded-lg border border-border bg-[#111] px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-700 focus:border-zinc-600 focus:outline-none'

  return (
    <>
      {/* ── Floating trigger ── */}
      <button
        onClick={handleOpen}
        title={currentIsAdmin ? 'Log feedback (admin)' : 'Submit feedback'}
        className="fixed bottom-5 right-5 z-50 group flex items-center gap-2 rounded-full border border-[#2a2a2a] bg-[#111]/90 px-3 py-2 shadow-xl backdrop-blur-sm transition-all duration-200 hover:border-[#3a3a3a] hover:bg-surface-2"
      >
        <span className="relative flex h-2 w-2 shrink-0">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-500 opacity-40" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
        </span>
        <svg
          className="h-3.5 w-3.5 text-zinc-500 transition-colors group-hover:text-zinc-300"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11 19a8 8 0 008-8V9a4 4 0 00-4-4H9a4 4 0 00-4 4v2a8 8 0 008 8zM9 3h6M5.5 7l-2-2M18.5 7l2-2M5.5 17l-2 2M18.5 17l2 2" />
        </svg>
        <span className="font-mono text-[10px] tracking-widest text-zinc-600 transition-colors group-hover:text-zinc-400">
          {currentIsAdmin ? 'ADMIN' : 'FEEDBACK'}
        </span>
      </button>

      {/* ── Modal ── */}
      {open && (
        <div className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={handleClose} />

          <div className="relative w-full max-w-lg rounded-2xl border border-[#252525] bg-[#0e0e0e] shadow-2xl">

            {/* Header */}
            <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[10px] uppercase tracking-widest text-amber-500">Admin</span>
                <span className="font-mono text-[10px] text-zinc-700">/</span>
                <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">Feedback</span>
                {form.type && (
                  <>
                    <span className="font-mono text-[10px] text-zinc-700">/</span>
                    <span className={`font-mono text-[10px] uppercase tracking-widest ${form.type === 'bug' ? 'text-amber-400' : 'text-blue-400'}`}>
                      {form.type}
                    </span>
                  </>
                )}
              </div>
              <button onClick={handleClose} className="text-zinc-600 transition-colors hover:text-zinc-400">
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* ── Success ── */}
            {submitted ? (
              <div className="flex flex-col items-center gap-3 px-5 py-14">
                <div className="flex h-10 w-10 items-center justify-center rounded-full border border-emerald-900/40 bg-emerald-950/40">
                  <svg className="h-5 w-5 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <p className="text-sm text-zinc-400">Logged. Thanks.</p>
              </div>

            /* ── Step 1: Type selection ── */
            ) : step === 1 ? (
              <div className="p-5">
                <p className="mb-1 text-sm font-bold text-white" style={{ fontFamily: 'Syne, sans-serif' }}>
                  What are you logging?
                </p>
                <p className="mb-5 text-xs text-zinc-600">Select a type to continue.</p>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => { set('type', 'bug'); setStep(2) }}
                    className="group flex flex-col items-start gap-3 rounded-xl border border-border bg-[#111] p-4 text-left transition-all hover:border-amber-900/50 hover:bg-amber-950/10"
                  >
                    <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-amber-900/30 bg-amber-950/40 text-amber-500">
                      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                      </svg>
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-white">Bug</p>
                      <p className="mt-0.5 text-xs leading-relaxed text-zinc-600">Something's broken or behaving wrong</p>
                    </div>
                  </button>
                  <button
                    onClick={() => { set('type', 'feature'); setStep(2) }}
                    className="group flex flex-col items-start gap-3 rounded-xl border border-border bg-[#111] p-4 text-left transition-all hover:border-blue-900/50 hover:bg-blue-950/10"
                  >
                    <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-blue-900/30 bg-blue-950/40 text-blue-400">
                      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.663 17h4.673M12 3v1M6.343 6.343l-.707-.707M17.657 6.343l.707-.707M3 12h1m17 0h1M4.929 19.071l.707-.707M19.071 19.071l-.707-.707M12 21a9 9 0 100-18 9 9 0 000 18z" />
                      </svg>
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-white">Feature request</p>
                      <p className="mt-0.5 text-xs leading-relaxed text-zinc-600">An idea or improvement to add</p>
                    </div>
                  </button>
                </div>
              </div>

            /* ── Step 2: Form ── */
            ) : (
              <div className="max-h-[72vh] space-y-4 overflow-y-auto px-5 py-4">
                {/* Back + type pill */}
                <div className="flex items-center gap-2">
                  <button onClick={() => setStep(1)} className="text-xs text-zinc-600 transition-colors hover:text-zinc-400">
                    ← Back
                  </button>
                  <span className={`rounded-full border px-2 py-0.5 font-mono text-[10px] font-semibold uppercase ${
                    form.type === 'bug'
                      ? 'border-amber-900/50 bg-amber-950/30 text-amber-500'
                      : 'border-blue-900/50 bg-blue-950/30 text-blue-400'
                  }`}>
                    {form.type}
                  </span>
                  {/* AI hint */}
                  {!titleEmpty && (
                    <span className="ml-auto flex items-center gap-1 font-mono text-[10px] text-zinc-700">
                      <svg className="h-2.5 w-2.5 text-violet-600" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6z" />
                      </svg>
                      {form.type === 'bug' && includeScreenshot && screenshot ? 'AI + screenshot' : 'AI assist available'}
                    </span>
                  )}
                </div>

                {/* Title */}
                <div>
                  <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-zinc-500">
                    Title <span className="text-zinc-700">*</span>
                  </label>
                  <input
                    value={form.title}
                    onChange={(e) => set('title', e.target.value)}
                    placeholder={form.type === 'bug' ? 'What went wrong?' : 'What should be added?'}
                    className="w-full rounded-lg border border-border bg-[#111] px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-700 focus:border-zinc-600 focus:outline-none"
                  />
                  {titleEmpty && (
                    <p className="mt-1 font-mono text-[10px] text-zinc-700">Enter a title to unlock AI assist ↑</p>
                  )}
                </div>

                {/* Description */}
                <div>
                  <FieldLabel
                    label="Description"
                    required
                    field="description"
                    suggesting={suggesting}
                    titleEmpty={titleEmpty}
                    onSuggest={suggest}
                  />
                  <textarea
                    value={form.description}
                    onChange={(e) => set('description', e.target.value)}
                    rows={3}
                    placeholder={form.type === 'bug' ? 'Describe what happened…' : 'Describe what you want and why…'}
                    className={textareaClass}
                  />
                </div>

                {/* Bug-specific fields */}
                {form.type === 'bug' && (
                  <>
                    <div>
                      <FieldLabel
                        label="Steps to reproduce"
                        field="steps_to_reproduce"
                        suggesting={suggesting}
                        titleEmpty={titleEmpty}
                        onSuggest={suggest}
                      />
                      <textarea
                        value={form.steps_to_reproduce}
                        onChange={(e) => set('steps_to_reproduce', e.target.value)}
                        rows={2}
                        placeholder="1. Go to… 2. Click… 3. See error"
                        className={textareaClass}
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <FieldLabel
                          label="Expected"
                          field="expected_behavior"
                          suggesting={suggesting}
                          titleEmpty={titleEmpty}
                          onSuggest={suggest}
                        />
                        <textarea
                          value={form.expected_behavior}
                          onChange={(e) => set('expected_behavior', e.target.value)}
                          rows={2}
                          placeholder="What should happen…"
                          className={textareaClass}
                        />
                      </div>
                      <div>
                        <FieldLabel
                          label="Actual"
                          field="actual_behavior"
                          suggesting={suggesting}
                          titleEmpty={titleEmpty}
                          onSuggest={suggest}
                        />
                        <textarea
                          value={form.actual_behavior}
                          onChange={(e) => set('actual_behavior', e.target.value)}
                          rows={2}
                          placeholder="What actually happens…"
                          className={textareaClass}
                        />
                      </div>
                    </div>

                    {/* Screenshot section — bugs only */}
                    <ScreenshotSection
                      screenshot={screenshot}
                      includeScreenshot={includeScreenshot}
                      capturing={capturing}
                      onToggle={() => setIncludeScreenshot((v) => !v)}
                      onRetake={handleRetake}
                      onRemove={() => { setScreenshot(null); setIncludeScreenshot(true) }}
                      onFileUpload={(dataUrl) => { setScreenshot(dataUrl); setIncludeScreenshot(true) }}
                    />
                  </>
                )}

                {/* Feature-specific fields */}
                {form.type === 'feature' && (
                  <>
                    <div>
                      <FieldLabel
                        label="Use case"
                        field="use_case"
                        suggesting={suggesting}
                        titleEmpty={titleEmpty}
                        onSuggest={suggest}
                      />
                      <textarea
                        value={form.use_case}
                        onChange={(e) => set('use_case', e.target.value)}
                        rows={2}
                        placeholder="When would you use this? What problem does it solve?"
                        className={textareaClass}
                      />
                    </div>
                    <div>
                      <FieldLabel
                        label="Impact"
                        field="user_impact"
                        suggesting={suggesting}
                        titleEmpty={titleEmpty}
                        onSuggest={suggest}
                      />
                      <textarea
                        value={form.user_impact}
                        onChange={(e) => set('user_impact', e.target.value)}
                        rows={2}
                        placeholder="How would this improve your workflow?"
                        className={textareaClass}
                      />
                    </div>
                  </>
                )}

                {/* Priority */}
                <div>
                  <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-zinc-500">
                    Priority
                  </label>
                  <div className="flex gap-2">
                    {(['low', 'medium', 'high'] as FeedbackPriority[]).map((p) => (
                      <button
                        key={p}
                        type="button"
                        onClick={() => set('priority', p)}
                        className={`flex-1 rounded-lg border py-1.5 font-mono text-[10px] font-semibold uppercase transition-all ${
                          form.priority === p
                            ? p === 'high'
                              ? 'border-red-900/50 bg-red-950/30 text-red-400'
                              : p === 'medium'
                                ? 'border-amber-900/50 bg-amber-950/30 text-amber-500'
                                : 'border-zinc-700 bg-zinc-900 text-zinc-300'
                            : 'border-border text-zinc-700 hover:border-[#2a2a2a] hover:text-zinc-500'
                        }`}
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Auto-captured context */}
                <div className="rounded-lg border border-border bg-background px-3 py-2">
                  <p className="font-mono text-[10px] text-zinc-700">
                    Page: <span className="text-zinc-500">{typeof window !== 'undefined' ? window.location.pathname : pathname}</span>
                  </p>
                </div>

                {/* AI error */}
                {suggestError && (
                  <div className="rounded-lg border border-red-900/40 bg-red-950/20 px-3 py-2">
                    <p className="font-mono text-[10px] text-red-400">AI error: {suggestError}</p>
                  </div>
                )}

                {/* Submit */}
                <button
                  onClick={handleSubmit}
                  disabled={!canSubmitForm}
                  className="w-full rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-black transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-30"
                >
                  {submitting ? 'Logging…' : 'Submit feedback'}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
