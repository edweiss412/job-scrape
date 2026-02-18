'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { InterviewQA, QACategory, Resume } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { formatDate } from '@/lib/utils'

/* ─────────── Constants ─────────── */

const CATEGORY_META: Record<QACategory, { label: string; bg: string; text: string; border: string; accent: string }> = {
  technical:   { label: 'Technical',   bg: 'bg-blue-950/60',   text: 'text-blue-400',   border: 'border-blue-800',   accent: '#3b82f6' },
  behavioral:  { label: 'Behavioral',  bg: 'bg-purple-950/60', text: 'text-purple-400', border: 'border-purple-800', accent: '#a855f7' },
  situational: { label: 'Situational', bg: 'bg-amber-950/60',  text: 'text-amber-400',  border: 'border-amber-800',  accent: '#f59e0b' },
  general:     { label: 'General',     bg: 'bg-zinc-900/60',   text: 'text-zinc-400',   border: 'border-zinc-700',   accent: '#71717a' },
}

const DEFAULT_ACCENT = '#71717a'

function getAccent(category: QACategory | null): string {
  return category ? CATEGORY_META[category].accent : DEFAULT_ACCENT
}

/* ─────────── CSS Keyframes ─────────── */

const CAROUSEL_STYLES = `
@keyframes card-exit-left {
  from { transform: translateX(0) scale(1); opacity: 1; }
  to   { transform: translateX(-60px) scale(0.95); opacity: 0; }
}
@keyframes card-exit-right {
  from { transform: translateX(0) scale(1); opacity: 1; }
  to   { transform: translateX(60px) scale(0.95); opacity: 0; }
}
@keyframes card-enter-left {
  from { transform: translateX(60px) scale(0.95); opacity: 0; }
  to   { transform: translateX(0) scale(1); opacity: 1; }
}
@keyframes card-enter-right {
  from { transform: translateX(-60px) scale(0.95); opacity: 0; }
  to   { transform: translateX(0) scale(1); opacity: 1; }
}
.card-exit-left  { animation: card-exit-left 250ms ease-in forwards; }
.card-exit-right { animation: card-exit-right 250ms ease-in forwards; }
.card-enter-left  { animation: card-enter-left 300ms ease-out forwards; }
.card-enter-right { animation: card-enter-right 300ms ease-out forwards; }
`

/* ─────────── Small sub-components ─────────── */

function CategoryBadge({ category }: { category: QACategory | null }) {
  if (!category) return null
  const meta = CATEGORY_META[category]
  return (
    <span className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 font-mono text-[10px] font-semibold ${meta.bg} ${meta.text} ${meta.border}`}>
      {meta.label}
    </span>
  )
}

function AIBadge() {
  return (
    <span className="inline-flex shrink-0 items-center rounded border border-violet-800 bg-violet-950/60 px-1.5 py-0.5 font-mono text-[9px] font-bold text-violet-400">
      AI
    </span>
  )
}

/* ─────────── EditForm (unchanged logic) ─────────── */

interface EditFormProps {
  draft: Partial<InterviewQA>
  onChange: (d: Partial<InterviewQA>) => void
  onSave: () => void
  onCancel: () => void
  saving: boolean
  isNew?: boolean
}

function EditForm({ draft, onChange, onSave, onCancel, saving, isNew }: EditFormProps) {
  return (
    <div className="space-y-3" onClick={e => e.stopPropagation()}>
      <div>
        <label className="mb-1 block text-[10px] font-mono font-semibold uppercase tracking-wider text-zinc-500">
          Question *
        </label>
        <textarea
          className="w-full rounded-lg border border-[#2a2a2a] bg-[#0d0d0d] px-3 py-2 text-sm text-white placeholder-zinc-600 focus:border-[#444] focus:outline-none resize-none"
          rows={2}
          value={draft.question ?? ''}
          onChange={e => onChange({ ...draft, question: e.target.value })}
          placeholder="Interview question..."
        />
      </div>
      <div>
        <label className="mb-1 block text-[10px] font-mono font-semibold uppercase tracking-wider text-zinc-500">
          Answer
        </label>
        <textarea
          className="w-full rounded-lg border border-[#2a2a2a] bg-[#0d0d0d] px-3 py-2 text-sm text-white placeholder-zinc-600 focus:border-[#444] focus:outline-none resize-none"
          rows={3}
          value={draft.answer ?? ''}
          onChange={e => onChange({ ...draft, answer: e.target.value })}
          placeholder="Your answer..."
        />
      </div>
      <div>
        <label className="mb-1 block text-[10px] font-mono font-semibold uppercase tracking-wider text-zinc-500">
          Category
        </label>
        <select
          className="rounded-lg border border-[#2a2a2a] bg-[#0d0d0d] px-3 py-2 text-sm text-white focus:border-[#444] focus:outline-none"
          value={draft.category ?? ''}
          onChange={e => onChange({ ...draft, category: (e.target.value || null) as QACategory | null })}
        >
          <option value="">— none —</option>
          {(Object.keys(CATEGORY_META) as QACategory[]).map(cat => (
            <option key={cat} value={cat}>{CATEGORY_META[cat].label}</option>
          ))}
        </select>
      </div>
      <div className="flex items-center gap-2 pt-1">
        <Button
          variant="primary"
          size="sm"
          onClick={onSave}
          disabled={saving || !draft.question?.trim()}
        >
          {saving ? <Spinner className="h-3 w-3" /> : null}
          {isNew ? 'Add' : 'Save'}
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

/* ─────────── NavArrow ─────────── */

function NavArrow({ direction, onClick, disabled }: { direction: 'left' | 'right'; onClick: () => void; disabled: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={direction === 'left' ? 'Previous card' : 'Next card'}
      className={`
        z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full
        border border-[#2a2a2a] bg-[#141414] text-zinc-400
        transition-all hover:border-[#444] hover:bg-[#1f1f1f] hover:text-white
        disabled:opacity-0 disabled:pointer-events-none
        active:scale-90
      `}
    >
      {direction === 'left' ? (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M10 12L6 8L10 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M6 4L10 8L6 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
      )}
    </button>
  )
}

/* ─────────── FlashCard ─────────── */

interface FlashCardProps {
  item: InterviewQA
  index: number
  total: number
  isFlipped: boolean
  onFlip: () => void
  isEditing: boolean
  editDraft: Partial<InterviewQA>
  saving: boolean
  onEditStart: () => void
  onEditChange: (d: Partial<InterviewQA>) => void
  onEditSave: () => void
  onEditCancel: () => void
  onDelete: () => void
  animationClass: string
}

function FlashCard({
  item, index, total, isFlipped, onFlip,
  isEditing, editDraft, saving,
  onEditStart, onEditChange, onEditSave, onEditCancel, onDelete,
  animationClass,
}: FlashCardProps) {
  const accent = getAccent(item.category)

  return (
    <div className={`w-full ${animationClass}`}>
      {/* Perspective wrapper */}
      <div style={{ perspective: '1200px' }}>
        <div
          onClick={isEditing ? undefined : onFlip}
          className="relative h-[340px] w-full cursor-pointer select-none"
          style={{
            transformStyle: 'preserve-3d',
            transition: 'transform 0.6s cubic-bezier(0.4, 0, 0.2, 1)',
            transform: isFlipped ? 'rotateY(180deg)' : 'rotateY(0deg)',
          }}
        >
          {/* ── Front face (Question) ── */}
          <div
            className="absolute inset-0 flex flex-col rounded-2xl border border-[#1f1f1f] overflow-hidden"
            style={{
              backfaceVisibility: 'hidden',
              WebkitBackfaceVisibility: 'hidden',
              background: `radial-gradient(ellipse at 10% 20%, ${accent}08, #0a0a0a 60%)`,
              boxShadow: '0 4px 24px rgba(0,0,0,0.4), 0 1px 4px rgba(0,0,0,0.3)',
            }}
          >
            {/* Accent stripe */}
            <div className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l-2xl" style={{ backgroundColor: accent }} />

            {/* Top badges */}
            <div className="flex items-center gap-1.5 px-5 pt-4">
              <CategoryBadge category={item.category} />
              {item.source === 'ai_generated' && <AIBadge />}
            </div>

            {/* Question text */}
            <div className="flex flex-1 items-center px-5">
              <p className="text-[17px] font-medium leading-relaxed text-white">{item.question}</p>
            </div>

            {/* Bottom row */}
            <div className="flex items-center justify-between px-5 pb-4">
              <span className="text-[11px] text-zinc-600">tap to reveal</span>
              <span className="font-mono text-[11px] text-zinc-600">{index + 1} / {total}</span>
            </div>
          </div>

          {/* ── Back face (Answer) ── */}
          <div
            className="absolute inset-0 flex flex-col rounded-2xl border border-[#1f1f1f] overflow-hidden"
            style={{
              backfaceVisibility: 'hidden',
              WebkitBackfaceVisibility: 'hidden',
              transform: 'rotateY(180deg)',
              background: `radial-gradient(ellipse at 10% 20%, ${accent}08, #0a0a0a 60%)`,
              boxShadow: '0 4px 24px rgba(0,0,0,0.4), 0 1px 4px rgba(0,0,0,0.3)',
            }}
          >
            {/* Accent stripe */}
            <div className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l-2xl" style={{ backgroundColor: accent }} />

            {isEditing ? (
              /* Edit form replaces the entire back face content */
              <div className="flex-1 overflow-y-auto px-5 py-4" onClick={e => e.stopPropagation()}>
                <EditForm
                  draft={editDraft}
                  onChange={onEditChange}
                  onSave={onEditSave}
                  onCancel={onEditCancel}
                  saving={saving}
                />
              </div>
            ) : (
              <>
                {/* Top: ANSWER label + date */}
                <div className="flex items-center justify-between px-5 pt-4">
                  <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-zinc-500">Answer</span>
                  <span className="text-[10px] text-zinc-700">{formatDate(item.created_at)}</span>
                </div>

                {/* Answer text (scrollable) */}
                <div className="flex-1 overflow-y-auto px-5 py-3">
                  {item.answer ? (
                    <p className="text-sm leading-relaxed text-zinc-300 whitespace-pre-wrap">{item.answer}</p>
                  ) : (
                    <p className="text-sm italic text-zinc-600">No answer yet — edit to add one.</p>
                  )}
                </div>

                {/* Bottom: actions + hint */}
                <div className="flex items-center justify-between px-5 pb-4">
                  <div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
                    <Button variant="secondary" size="sm" onClick={onEditStart}>Edit</Button>
                    <Button variant="danger" size="sm" onClick={onDelete}>Delete</Button>
                  </div>
                  <span className="text-[11px] text-zinc-600">tap to flip back</span>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/* ─────────── Progress Indicator ─────────── */

function ProgressIndicator({ total, current, onNavigate }: { total: number; current: number; onNavigate: (i: number) => void }) {
  if (total <= 12) {
    // Dot indicators
    return (
      <div className="flex items-center justify-center gap-1.5 pt-4">
        {Array.from({ length: total }, (_, i) => (
          <button
            key={i}
            onClick={() => onNavigate(i)}
            aria-label={`Go to card ${i + 1}`}
            className={`rounded-full transition-all duration-300 ${
              i === current
                ? 'h-2 w-6 bg-zinc-400'
                : 'h-2 w-2 bg-zinc-700 hover:bg-zinc-500'
            }`}
          />
        ))}
      </div>
    )
  }

  // Numeric counter + progress bar for > 12 cards
  const pct = ((current + 1) / total) * 100
  return (
    <div className="flex flex-col items-center gap-2 pt-4">
      <span className="font-mono text-xs text-zinc-500">{current + 1} / {total}</span>
      <div className="h-0.5 w-32 overflow-hidden rounded-full bg-zinc-800">
        <div className="h-full rounded-full bg-zinc-500 transition-all duration-300" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

/* ─────────── Main Section ─────────── */

interface InterviewQASectionProps {
  resumes: Resume[]
}

export function InterviewQASection({ resumes }: InterviewQASectionProps) {
  // CRUD state (unchanged)
  const [qaItems, setQaItems] = useState<InterviewQA[]>([])
  const [loading, setLoading] = useState(true)
  const [showAddForm, setShowAddForm] = useState(false)
  const [addDraft, setAddDraft] = useState<Partial<InterviewQA>>({})
  const [addSaving, setAddSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [generateResumeId, setGenerateResumeId] = useState<string>(resumes[0]?.id ?? '')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState<Partial<InterviewQA>>({})
  const [editSaving, setEditSaving] = useState(false)
  const [filterCategory, setFilterCategory] = useState<QACategory | ''>('')

  // Carousel state
  const [currentIndex, setCurrentIndex] = useState(0)
  const [isFlipped, setIsFlipped] = useState(false)
  const [slidePhase, setSlidePhase] = useState<'idle' | 'exit' | 'enter'>('idle')
  const [slideDirection, setSlideDirection] = useState<'left' | 'right'>('left')
  const isAnimating = slidePhase !== 'idle'

  // Touch / swipe tracking
  const pointerStart = useRef<{ x: number; y: number; t: number } | null>(null)

  useEffect(() => {
    fetch('/api/interview-qa')
      .then(r => r.json())
      .then(data => {
        setQaItems(Array.isArray(data) ? data : [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!generateResumeId && resumes.length > 0) {
      setGenerateResumeId(resumes[0].id)
    }
  }, [resumes, generateResumeId])

  const filteredItems = filterCategory
    ? qaItems.filter(item => item.category === filterCategory)
    : qaItems

  const categoryCounts = qaItems.reduce((acc, item) => {
    if (item.category) acc[item.category] = (acc[item.category] ?? 0) + 1
    return acc
  }, {} as Record<string, number>)

  // ── Carousel navigation ──

  const navigateTo = useCallback((targetIndex: number, dir: 'left' | 'right') => {
    if (isAnimating || filteredItems.length <= 1) return
    setIsFlipped(false)
    setEditingId(null)
    setEditDraft({})
    setSlideDirection(dir)
    setSlidePhase('exit')

    setTimeout(() => {
      setCurrentIndex(targetIndex)
      setSlidePhase('enter')

      setTimeout(() => {
        setSlidePhase('idle')
      }, 300)
    }, 250)
  }, [isAnimating, filteredItems.length])

  const goNext = useCallback(() => {
    if (filteredItems.length <= 1) return
    const next = (currentIndex + 1) % filteredItems.length
    navigateTo(next, 'left')
  }, [currentIndex, filteredItems.length, navigateTo])

  const goPrev = useCallback(() => {
    if (filteredItems.length <= 1) return
    const prev = (currentIndex - 1 + filteredItems.length) % filteredItems.length
    navigateTo(prev, 'right')
  }, [currentIndex, filteredItems.length, navigateTo])

  const goToDot = useCallback((i: number) => {
    if (i === currentIndex || isAnimating) return
    navigateTo(i, i > currentIndex ? 'left' : 'right')
  }, [currentIndex, isAnimating, navigateTo])

  // ── Keyboard ──

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      // Don't capture if user is typing in an input/textarea
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (filteredItems.length === 0) return

      if (e.key === 'ArrowRight') { e.preventDefault(); goNext() }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); goPrev() }
      else if (e.key === ' ') { e.preventDefault(); setIsFlipped(f => !f) }
      else if (e.key === 'Escape') { setIsFlipped(false); setEditingId(null); setEditDraft({}) }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [filteredItems.length, goNext, goPrev])

  // ── Touch swipe ──

  function handlePointerDown(e: React.PointerEvent) {
    pointerStart.current = { x: e.clientX, y: e.clientY, t: Date.now() }
  }

  function handlePointerUp(e: React.PointerEvent) {
    if (!pointerStart.current) return
    const dx = e.clientX - pointerStart.current.x
    const dy = e.clientY - pointerStart.current.y
    const dt = Date.now() - pointerStart.current.t
    pointerStart.current = null

    // Only count horizontal swipes: > 50px, < 500ms, more horizontal than vertical
    if (Math.abs(dx) > 50 && dt < 500 && Math.abs(dx) > Math.abs(dy)) {
      if (dx < 0) goNext()
      else goPrev()
    }
    // Otherwise, fall through to click (flip) handler
  }

  // ── Reset carousel on filter change ──

  useEffect(() => {
    setCurrentIndex(0)
    setIsFlipped(false)
    setEditingId(null)
    setEditDraft({})
  }, [filterCategory])

  // ── CRUD handlers (unchanged) ──

  async function handleAdd() {
    if (!addDraft.question?.trim()) return
    setAddSaving(true)
    const res = await fetch('/api/interview-qa', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(addDraft),
    })
    if (res.ok) {
      const newItem = await res.json()
      setQaItems(prev => [newItem, ...prev])
      setAddDraft({})
      setShowAddForm(false)
      // Navigate to the new card
      setCurrentIndex(0)
      setIsFlipped(false)
    } else {
      const err = await res.json()
      alert(`Failed to add: ${err.error}`)
    }
    setAddSaving(false)
  }

  function startEdit(item: InterviewQA) {
    setEditingId(item.id)
    setEditDraft({ question: item.question, answer: item.answer ?? '', category: item.category })
  }

  async function handleEditSave() {
    if (!editingId || !editDraft.question?.trim()) return
    setEditSaving(true)
    const res = await fetch(`/api/interview-qa/${editingId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(editDraft),
    })
    if (res.ok) {
      const updated = await res.json()
      setQaItems(prev => prev.map(item => item.id === editingId ? updated : item))
      setEditingId(null)
      setEditDraft({})
    } else {
      const err = await res.json()
      alert(`Save failed: ${err.error}`)
    }
    setEditSaving(false)
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this Q&A pair?')) return
    setIsFlipped(false)
    setEditingId(null)
    setEditDraft({})
    setQaItems(prev => {
      const next = prev.filter(item => item.id !== id)
      // Adjust currentIndex if we deleted the last card
      const newFiltered = filterCategory ? next.filter(item => item.category === filterCategory) : next
      if (currentIndex >= newFiltered.length && newFiltered.length > 0) {
        setCurrentIndex(newFiltered.length - 1)
      } else if (newFiltered.length === 0) {
        setCurrentIndex(0)
      }
      return next
    })
    const res = await fetch(`/api/interview-qa/${id}`, { method: 'DELETE' })
    if (!res.ok) {
      fetch('/api/interview-qa')
        .then(r => r.json())
        .then(data => setQaItems(Array.isArray(data) ? data : []))
    }
  }

  async function handleGenerate() {
    if (!generateResumeId) {
      alert('Please select a resume first.')
      return
    }
    setGenerating(true)
    const res = await fetch('/api/interview-qa/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resumeId: generateResumeId }),
    })
    if (res.ok) {
      const newItems = await res.json()
      setQaItems(prev => [...(Array.isArray(newItems) ? newItems : []), ...prev])
      setCurrentIndex(0)
      setIsFlipped(false)
    } else {
      const err = await res.json()
      alert(`Generation failed: ${err.error}`)
    }
    setGenerating(false)
  }

  // ── Determine animation class ──

  let animationClass = ''
  if (slidePhase === 'exit') {
    animationClass = slideDirection === 'left' ? 'card-exit-left' : 'card-exit-right'
  } else if (slidePhase === 'enter') {
    animationClass = slideDirection === 'left' ? 'card-enter-left' : 'card-enter-right'
  }

  // Clamp currentIndex
  const safeIndex = filteredItems.length > 0 ? currentIndex % filteredItems.length : 0
  const currentItem = filteredItems[safeIndex]

  return (
    <div>
      <style dangerouslySetInnerHTML={{ __html: CAROUSEL_STYLES }} />

      {/* Section header */}
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-white">Interview Q&amp;A</h2>
          <p className="mt-0.5 text-xs text-zinc-600">
            {qaItems.length} {qaItems.length === 1 ? 'pair' : 'pairs'} saved
            {Object.entries(categoryCounts).map(([cat, count]) => (
              <span key={cat} className="ml-1.5 text-zinc-700">
                · {count} {cat}
              </span>
            ))}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => { setShowAddForm(v => !v); setAddDraft({}) }}
          >
            {showAddForm ? 'Cancel' : '+ Add question'}
          </Button>
        </div>
      </div>

      {/* Add form */}
      {showAddForm && (
        <div className="mb-5 rounded-xl border border-[#2a2a2a] bg-background p-4">
          <p className="mb-3 text-[10px] font-mono font-semibold uppercase tracking-wider text-zinc-500">New question</p>
          <EditForm
            draft={addDraft}
            onChange={setAddDraft}
            onSave={handleAdd}
            onCancel={() => { setShowAddForm(false); setAddDraft({}) }}
            saving={addSaving}
            isNew
          />
        </div>
      )}

      {/* Generate from resume */}
      {resumes.length > 0 && (
        <div className="mb-5 flex flex-wrap items-center gap-2 rounded-xl border border-border bg-background px-4 py-3">
          <span className="text-xs text-zinc-500">Generate from resume:</span>
          {resumes.length > 1 ? (
            <select
              className="rounded-lg border border-[#2a2a2a] bg-[#0d0d0d] px-2 py-1 text-xs text-white focus:border-[#444] focus:outline-none"
              value={generateResumeId}
              onChange={e => setGenerateResumeId(e.target.value)}
            >
              {resumes.map(r => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
          ) : (
            <span className="text-xs font-medium text-zinc-300">{resumes[0]?.name}</span>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={handleGenerate}
            disabled={generating || !generateResumeId}
          >
            {generating ? <Spinner className="h-3 w-3" /> : null}
            {generating ? 'Generating...' : 'Generate Q&As'}
          </Button>
          <span className="text-[10px] text-zinc-700">~8-10 AI-generated pairs</span>
        </div>
      )}

      {/* Category filter */}
      {qaItems.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => setFilterCategory('')}
            className={`rounded-full border px-3 py-1 text-[10px] font-mono font-semibold transition-colors ${
              filterCategory === ''
                ? 'border-zinc-600 bg-zinc-800 text-zinc-200'
                : 'border-zinc-800 bg-transparent text-zinc-600 hover:border-zinc-700 hover:text-zinc-400'
            }`}
          >
            All ({qaItems.length})
          </button>
          {(Object.keys(CATEGORY_META) as QACategory[]).map(cat => {
            const count = categoryCounts[cat] ?? 0
            if (count === 0) return null
            const meta = CATEGORY_META[cat]
            return (
              <button
                key={cat}
                onClick={() => setFilterCategory(cat === filterCategory ? '' : cat)}
                className={`rounded-full border px-3 py-1 text-[10px] font-mono font-semibold transition-colors ${
                  filterCategory === cat
                    ? `${meta.bg} ${meta.text} ${meta.border}`
                    : 'border-zinc-800 bg-transparent text-zinc-600 hover:border-zinc-700 hover:text-zinc-400'
                }`}
              >
                {meta.label} ({count})
              </button>
            )
          })}
        </div>
      )}

      {/* Carousel */}
      {loading ? (
        <div className="flex justify-center py-8">
          <Spinner className="h-5 w-5" />
        </div>
      ) : filteredItems.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <svg className="mb-3 h-10 w-10 text-zinc-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
          </svg>
          <p className="text-sm text-zinc-600">
            {qaItems.length === 0
              ? 'No Q&A pairs yet. Add one manually or generate from your resume.'
              : 'No questions in this category.'}
          </p>
        </div>
      ) : (
        <div>
          {/* Card + arrows */}
          <div
            className="flex items-center gap-3 px-2 sm:px-4"
            onPointerDown={handlePointerDown}
            onPointerUp={handlePointerUp}
          >
            <NavArrow direction="left" onClick={goPrev} disabled={filteredItems.length <= 1} />

            <div className="min-w-0 flex-1">
              <FlashCard
                key={currentItem.id}
                item={currentItem}
                index={safeIndex}
                total={filteredItems.length}
                isFlipped={isFlipped}
                onFlip={() => { if (!isAnimating) setIsFlipped(f => !f) }}
                isEditing={editingId === currentItem.id}
                editDraft={editDraft}
                saving={editSaving}
                onEditStart={() => startEdit(currentItem)}
                onEditChange={setEditDraft}
                onEditSave={handleEditSave}
                onEditCancel={() => { setEditingId(null); setEditDraft({}) }}
                onDelete={() => handleDelete(currentItem.id)}
                animationClass={animationClass}
              />
            </div>

            <NavArrow direction="right" onClick={goNext} disabled={filteredItems.length <= 1} />
          </div>

          {/* Progress indicator */}
          {filteredItems.length > 1 && (
            <ProgressIndicator total={filteredItems.length} current={safeIndex} onNavigate={goToDot} />
          )}

          {/* Keyboard hints */}
          <div className="mt-3 flex items-center justify-center gap-3 text-[10px] text-zinc-700">
            <span><kbd className="rounded border border-zinc-800 bg-zinc-900 px-1 py-0.5 font-mono">←</kbd> <kbd className="rounded border border-zinc-800 bg-zinc-900 px-1 py-0.5 font-mono">→</kbd> navigate</span>
            <span><kbd className="rounded border border-zinc-800 bg-zinc-900 px-1 py-0.5 font-mono">Space</kbd> flip</span>
            <span><kbd className="rounded border border-zinc-800 bg-zinc-900 px-1 py-0.5 font-mono">Esc</kbd> unflip</span>
          </div>
        </div>
      )}
    </div>
  )
}
