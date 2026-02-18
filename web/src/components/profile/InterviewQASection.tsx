'use client'

import { useState, useEffect } from 'react'
import { InterviewQA, QACategory, Resume } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { formatDate } from '@/lib/utils'

const CATEGORY_META: Record<QACategory, { label: string; bg: string; text: string; border: string }> = {
  technical:   { label: 'Technical',   bg: 'bg-blue-950/60',   text: 'text-blue-400',   border: 'border-blue-800' },
  behavioral:  { label: 'Behavioral',  bg: 'bg-purple-950/60', text: 'text-purple-400', border: 'border-purple-800' },
  situational: { label: 'Situational', bg: 'bg-amber-950/60',  text: 'text-amber-400',  border: 'border-amber-800' },
  general:     { label: 'General',     bg: 'bg-zinc-900/60',   text: 'text-zinc-400',   border: 'border-zinc-700' },
}

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
    <div className="space-y-3">
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
          rows={4}
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

interface QACardProps {
  item: InterviewQA
  isExpanded: boolean
  isEditing: boolean
  editDraft: Partial<InterviewQA>
  saving: boolean
  onToggle: () => void
  onEditStart: () => void
  onEditChange: (d: Partial<InterviewQA>) => void
  onEditSave: () => void
  onEditCancel: () => void
  onDelete: () => void
}

function QACard({
  item, isExpanded, isEditing, editDraft, saving,
  onToggle, onEditStart, onEditChange, onEditSave, onEditCancel, onDelete,
}: QACardProps) {
  return (
    <div className="rounded-xl border border-border bg-[#0d0d0d]">
      {/* Header */}
      <button
        onClick={onToggle}
        className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-[#111] rounded-xl"
      >
        <span className="mt-0.5 text-xs text-zinc-600 transition-transform" style={{ transform: isExpanded ? 'rotate(90deg)' : 'none' }}>
          ▶
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-white leading-snug">{item.question}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <CategoryBadge category={item.category} />
            {item.source === 'ai_generated' && <AIBadge />}
            <span className="text-[10px] text-zinc-700">{formatDate(item.created_at)}</span>
          </div>
        </div>
      </button>

      {/* Expanded content */}
      {isExpanded && !isEditing && (
        <div className="border-t border-[#1a1a1a] px-4 pb-4 pt-3">
          {item.answer ? (
            <p className="text-sm text-zinc-300 leading-relaxed whitespace-pre-wrap">{item.answer}</p>
          ) : (
            <p className="text-sm text-zinc-600 italic">No answer yet.</p>
          )}
          <div className="mt-3 flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={onEditStart}>
              Edit
            </Button>
            <Button variant="danger" size="sm" onClick={onDelete}>
              Delete
            </Button>
          </div>
        </div>
      )}

      {/* Edit form */}
      {isEditing && (
        <div className="border-t border-[#1a1a1a] px-4 pb-4 pt-3">
          <EditForm
            draft={editDraft}
            onChange={onEditChange}
            onSave={onEditSave}
            onCancel={onEditCancel}
            saving={saving}
          />
        </div>
      )}
    </div>
  )
}

interface InterviewQASectionProps {
  resumes: Resume[]
}

export function InterviewQASection({ resumes }: InterviewQASectionProps) {
  const [qaItems, setQaItems] = useState<InterviewQA[]>([])
  const [loading, setLoading] = useState(true)
  const [showAddForm, setShowAddForm] = useState(false)
  const [addDraft, setAddDraft] = useState<Partial<InterviewQA>>({})
  const [addSaving, setAddSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [generateResumeId, setGenerateResumeId] = useState<string>(resumes[0]?.id ?? '')
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState<Partial<InterviewQA>>({})
  const [editSaving, setEditSaving] = useState(false)
  const [filterCategory, setFilterCategory] = useState<QACategory | ''>('')

  useEffect(() => {
    fetch('/api/interview-qa')
      .then(r => r.json())
      .then(data => {
        setQaItems(Array.isArray(data) ? data : [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  // Keep generateResumeId in sync if resumes changes
  useEffect(() => {
    if (!generateResumeId && resumes.length > 0) {
      setGenerateResumeId(resumes[0].id)
    }
  }, [resumes, generateResumeId])

  function toggleExpand(id: string) {
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

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
    } else {
      const err = await res.json()
      alert(`Failed to add: ${err.error}`)
    }
    setAddSaving(false)
  }

  function startEdit(item: InterviewQA) {
    setEditingId(item.id)
    setEditDraft({ question: item.question, answer: item.answer ?? '', category: item.category })
    setExpandedIds(prev => new Set(prev).add(item.id))
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
    // Optimistic
    setQaItems(prev => prev.filter(item => item.id !== id))
    const res = await fetch(`/api/interview-qa/${id}`, { method: 'DELETE' })
    if (!res.ok) {
      // Rollback on failure
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
    } else {
      const err = await res.json()
      alert(`Generation failed: ${err.error}`)
    }
    setGenerating(false)
  }

  const filteredItems = filterCategory
    ? qaItems.filter(item => item.category === filterCategory)
    : qaItems

  const categoryCounts = qaItems.reduce((acc, item) => {
    if (item.category) acc[item.category] = (acc[item.category] ?? 0) + 1
    return acc
  }, {} as Record<string, number>)

  return (
    <div>
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

      {/* List */}
      {loading ? (
        <div className="flex justify-center py-8">
          <Spinner className="h-5 w-5" />
        </div>
      ) : filteredItems.length === 0 ? (
        <p className="py-8 text-center text-sm text-zinc-600">
          {qaItems.length === 0
            ? 'No Q&A pairs yet. Add one manually or generate from your resume.'
            : 'No questions in this category.'}
        </p>
      ) : (
        <div className="space-y-2">
          {filteredItems.map(item => (
            <QACard
              key={item.id}
              item={item}
              isExpanded={expandedIds.has(item.id)}
              isEditing={editingId === item.id}
              editDraft={editDraft}
              saving={editSaving}
              onToggle={() => toggleExpand(item.id)}
              onEditStart={() => startEdit(item)}
              onEditChange={setEditDraft}
              onEditSave={handleEditSave}
              onEditCancel={() => { setEditingId(null); setEditDraft({}) }}
              onDelete={() => handleDelete(item.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
