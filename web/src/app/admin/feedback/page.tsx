'use client'

import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Nav } from '@/components/layout/nav'
import { Feedback, FeedbackStatus, FeedbackPriority, FeedbackType } from '@/lib/types'
import { cn } from '@/lib/utils'

type SuggestField = 'description' | 'use_case' | 'user_impact' | 'steps_to_reproduce' | 'expected_behavior' | 'actual_behavior'

function AISuggestBtn({
  field, loading, disabled, onSuggest,
}: { field: SuggestField; loading: boolean; disabled: boolean; onSuggest: (f: SuggestField) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSuggest(field)}
      disabled={disabled || loading}
      className={`flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[10px] transition-all ${
        loading ? 'cursor-wait text-violet-400'
        : disabled ? 'cursor-not-allowed text-zinc-700'
        : 'cursor-pointer text-zinc-600 hover:bg-violet-950/30 hover:text-violet-400'
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

const STATUS_CYCLE: Record<FeedbackStatus, FeedbackStatus> = {
  open: 'in_progress',
  in_progress: 'done',
  done: 'open',
}

function buildLLMPrompt(item: Feedback): string {
  const typeLabel = item.type === 'bug' ? 'Bug' : 'Feature Request'
  const lines: string[] = [
    `## [${typeLabel}]: ${item.title}`,
    `**Page:** ${item.page_url ?? 'N/A'}`,
    `**Priority:** ${item.priority.toUpperCase()}`,
    `**Reported:** ${new Date(item.created_at).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}`,
    `**Status:** ${item.status.replace('_', ' ').toUpperCase()}`,
    '',
    '### Description',
    item.description,
  ]

  if (item.type === 'bug') {
    if (item.steps_to_reproduce) {
      lines.push('', '### Steps to Reproduce', item.steps_to_reproduce)
    }
    if (item.expected_behavior || item.actual_behavior) {
      lines.push('', '### Expected vs Actual')
      if (item.expected_behavior) lines.push(`**Expected:** ${item.expected_behavior}`)
      if (item.actual_behavior) lines.push(`**Actual:** ${item.actual_behavior}`)
    }
    if (item.screenshot_url) {
      lines.push('', '### Screenshot', item.screenshot_url)
    }
  } else {
    if (item.use_case) lines.push('', '### Use Case', item.use_case)
    if (item.user_impact) lines.push('', '### User Impact', item.user_impact)
  }

  return lines.join('\n')
}

const PRIORITY_DOT: Record<FeedbackPriority, string> = {
  high: 'bg-red-500',
  medium: 'bg-amber-500',
  low: 'bg-zinc-600',
}

const STATUS_BADGE: Record<FeedbackStatus, string> = {
  open: 'border-zinc-700 bg-zinc-900 text-zinc-400',
  in_progress: 'border-amber-900/50 bg-amber-950/30 text-amber-500',
  done: 'border-emerald-900/40 bg-emerald-950/20 text-emerald-500',
}

const STATUS_LABEL: Record<FeedbackStatus, string> = {
  open: 'Open',
  in_progress: 'In Progress',
  done: 'Done',
}

const TYPE_BADGE: Record<FeedbackType, string> = {
  bug: 'border-amber-900/50 bg-amber-950/30 text-amber-500',
  feature: 'border-blue-900/50 bg-blue-950/30 text-blue-400',
}

type EditDraft = {
  title: string
  description: string
  priority: FeedbackPriority
  steps_to_reproduce: string
  expected_behavior: string
  actual_behavior: string
  use_case: string
  user_impact: string
}

function draftFromItem(item: Feedback): EditDraft {
  return {
    title: item.title,
    description: item.description,
    priority: item.priority,
    steps_to_reproduce: item.steps_to_reproduce ?? '',
    expected_behavior: item.expected_behavior ?? '',
    actual_behavior: item.actual_behavior ?? '',
    use_case: item.use_case ?? '',
    user_impact: item.user_impact ?? '',
  }
}

function ScreenshotPreview({ url }: { url: string }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div>
      <div className="mb-1.5 flex items-center gap-2">
        <p className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Screenshot</p>
        <button
          onClick={() => setExpanded((v) => !v)}
          className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-zinc-400"
        >
          {expanded ? 'collapse' : 'expand'}
        </button>
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-zinc-400"
        >
          open ↗
        </a>
      </div>
      {/* Thumbnail always shown, full view when expanded */}
      <div
        className={`overflow-hidden rounded-lg border border-zinc-800 transition-all duration-200 ${expanded ? '' : 'max-h-28'}`}
        style={{ cursor: 'pointer' }}
        onClick={() => setExpanded((v) => !v)}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={url}
          alt="Bug screenshot"
          className="w-full object-cover object-top"
        />
      </div>
    </div>
  )
}

export default function AdminFeedbackPage() {
  const pathname = usePathname()
  const [items, setItems] = useState<Feedback[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [copied, setCopied] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null)
  const [saving, setSaving] = useState(false)
  const [editSuggesting, setEditSuggesting] = useState<SuggestField | null>(null)
  const [editSuggestError, setEditSuggestError] = useState<string | null>(null)

  const fetchItems = useCallback(async () => {
    const res = await fetch('/api/feedback')
    const data = await res.json()
    setItems(Array.isArray(data) ? data : [])
    setLoading(false)
  }, [])

  useEffect(() => { fetchItems() }, [fetchItems])

  async function cycleStatus(id: string, current: FeedbackStatus) {
    const next = STATUS_CYCLE[current]
    setItems((prev) => prev.map((i) => i.id === id ? { ...i, status: next } : i))
    await fetch(`/api/feedback/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: next }),
    })
  }

  async function copyForLLM(item: Feedback) {
    await navigator.clipboard.writeText(buildLLMPrompt(item))
    setCopied(item.id)
    setTimeout(() => setCopied(null), 2000)
  }

  async function deleteItem(id: string) {
    if (!confirm('Delete this feedback item?')) return
    setItems((prev) => prev.filter((i) => i.id !== id))
    await fetch(`/api/feedback/${id}`, { method: 'DELETE' })
  }

  function startEdit(item: Feedback) {
    setEditingId(item.id)
    setEditDraft(draftFromItem(item))
  }

  function cancelEdit() {
    setEditingId(null)
    setEditDraft(null)
    setEditSuggestError(null)
  }

  async function suggestEdit(field: SuggestField, itemType: FeedbackType) {
    if (!editDraft?.title.trim()) return
    setEditSuggesting(field)
    setEditSuggestError(null)
    try {
      const res = await fetch('/api/feedback/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: editDraft.title,
          type: itemType,
          field,
          currentValues: {
            description: editDraft.description,
            use_case: editDraft.use_case,
            user_impact: editDraft.user_impact,
            steps_to_reproduce: editDraft.steps_to_reproduce,
            expected_behavior: editDraft.expected_behavior,
            actual_behavior: editDraft.actual_behavior,
          },
        }),
      })
      const data = await res.json()
      if (data.suggestion) {
        setEditDraft((d) => d && { ...d, [field]: data.suggestion })
      } else {
        setEditSuggestError(data.error ?? 'No suggestion returned')
        setTimeout(() => setEditSuggestError(null), 4000)
      }
    } catch {
      setEditSuggestError('Network error — try again')
      setTimeout(() => setEditSuggestError(null), 4000)
    } finally {
      setEditSuggesting(null)
    }
  }

  async function saveEdit(id: string) {
    if (!editDraft) return
    setSaving(true)
    try {
      const res = await fetch(`/api/feedback/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editDraft),
      })
      const updated = await res.json()
      setItems((prev) => prev.map((i) => i.id === id ? { ...i, ...updated } : i))
      setEditingId(null)
      setEditDraft(null)
    } finally {
      setSaving(false)
    }
  }

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const filtered = items.filter((i) => {
    if (typeFilter && i.type !== typeFilter) return false
    if (statusFilter && i.status !== statusFilter) return false
    if (priorityFilter && i.priority !== priorityFilter) return false
    return true
  })

  const counts = {
    open: items.filter((i) => i.status === 'open').length,
    in_progress: items.filter((i) => i.status === 'in_progress').length,
    done: items.filter((i) => i.status === 'done').length,
    bugs: items.filter((i) => i.type === 'bug').length,
    features: items.filter((i) => i.type === 'feature').length,
  }

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-4xl px-4 py-8">

        {/* Sub-nav */}
        <div className="mb-6 flex items-center gap-1 border-b border-border pb-4">
          <Link href="/admin/feedback" className={cn('rounded-md px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider transition-colors', pathname === '/admin/feedback' ? 'bg-amber-950/40 text-amber-400' : 'text-zinc-600 hover:bg-surface-2 hover:text-zinc-400')}>Feedback</Link>
          <Link href="/admin/users" className={cn('rounded-md px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider transition-colors', pathname === '/admin/users' ? 'bg-amber-950/40 text-amber-400' : 'text-zinc-600 hover:bg-surface-2 hover:text-zinc-400')}>Users</Link>
        </div>

        {/* Header */}
        <div className="mb-6">
          <div className="mb-1 flex items-center gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-widest text-amber-500">Admin</span>
            <span className="font-mono text-[10px] text-zinc-700">/</span>
            <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">Feedback</span>
          </div>
          <h1 className="text-xl font-bold text-white" style={{ fontFamily: 'Syne, sans-serif' }}>
            Feedback Log
          </h1>
          <p className="mt-0.5 text-sm text-zinc-600">{items.length} items total</p>
        </div>

        {/* Summary chips */}
        <div className="mb-5 flex flex-wrap gap-2">
          <span className="rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 font-mono text-[10px] text-zinc-400">
            {counts.open} open
          </span>
          <span className="rounded-full border border-amber-900/50 bg-amber-950/30 px-2.5 py-1 font-mono text-[10px] text-amber-500">
            {counts.in_progress} in progress
          </span>
          <span className="rounded-full border border-emerald-900/40 bg-emerald-950/20 px-2.5 py-1 font-mono text-[10px] text-emerald-500">
            {counts.done} done
          </span>
          <span className="ml-2 rounded-full border border-border px-2.5 py-1 font-mono text-[10px] text-zinc-600">
            {counts.bugs} bugs
          </span>
          <span className="rounded-full border border-border px-2.5 py-1 font-mono text-[10px] text-zinc-600">
            {counts.features} features
          </span>
        </div>

        {/* Filters */}
        <div className="mb-4 flex flex-wrap gap-2">
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="rounded-lg border border-border bg-[#111] px-2.5 py-1.5 font-mono text-[10px] uppercase text-zinc-500 focus:border-zinc-600 focus:outline-none"
          >
            <option value="">All types</option>
            <option value="bug">Bug</option>
            <option value="feature">Feature</option>
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-border bg-[#111] px-2.5 py-1.5 font-mono text-[10px] uppercase text-zinc-500 focus:border-zinc-600 focus:outline-none"
          >
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="in_progress">In Progress</option>
            <option value="done">Done</option>
          </select>
          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
            className="rounded-lg border border-border bg-[#111] px-2.5 py-1.5 font-mono text-[10px] uppercase text-zinc-500 focus:border-zinc-600 focus:outline-none"
          >
            <option value="">All priorities</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          {(typeFilter || statusFilter || priorityFilter) && (
            <button
              onClick={() => { setTypeFilter(''); setStatusFilter(''); setPriorityFilter('') }}
              className="rounded-lg border border-border px-2.5 py-1.5 font-mono text-[10px] text-zinc-600 transition-colors hover:border-[#2a2a2a] hover:text-zinc-400"
            >
              Clear
            </button>
          )}
        </div>

        {/* List */}
        {loading ? (
          <div className="py-16 text-center font-mono text-xs text-zinc-700">Loading…</div>
        ) : !filtered.length ? (
          <div className="rounded-xl border border-border bg-[#111] p-12 text-center text-sm text-zinc-600">
            No feedback items match your filters.
          </div>
        ) : (
          <div className="space-y-2">
            {filtered.map((item) => {
              const isExpanded = expanded.has(item.id)

              return (
                <div
                  key={item.id}
                  className="overflow-hidden rounded-xl border border-border bg-[#111] transition-colors hover:border-[#252525]"
                >
                  {/* ── Row header ── */}
                  <div className="flex items-center gap-3 px-4 py-3">
                    {/* Type badge */}
                    <span
                      className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase ${TYPE_BADGE[item.type]}`}
                    >
                      {item.type}
                    </span>

                    {/* Priority dot */}
                    <span
                      className={`h-1.5 w-1.5 shrink-0 rounded-full ${PRIORITY_DOT[item.priority]}`}
                      title={`Priority: ${item.priority}`}
                    />

                    {/* Title (clickable to expand) */}
                    <button
                      onClick={() => toggleExpand(item.id)}
                      className="flex-1 truncate text-left text-sm font-medium text-zinc-200 transition-colors hover:text-white"
                    >
                      {item.title}
                    </button>

                    {/* Page path */}
                    {item.page_url && (
                      <span className="hidden max-w-25 truncate font-mono text-[10px] text-zinc-700 sm:block">
                        {(() => {
                          try { return new URL(item.page_url).pathname }
                          catch { return item.page_url }
                        })()}
                      </span>
                    )}

                    {/* Date */}
                    <span className="shrink-0 font-mono text-[10px] text-zinc-700">
                      {new Date(item.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                    </span>

                    {/* Status badge — click to cycle */}
                    <button
                      onClick={() => cycleStatus(item.id, item.status)}
                      title="Click to advance status"
                      className={`shrink-0 rounded-full border px-2 py-0.5 font-mono text-[10px] font-semibold transition-opacity hover:opacity-70 ${STATUS_BADGE[item.status]}`}
                    >
                      {STATUS_LABEL[item.status]}
                    </button>

                    {/* Copy for LLM */}
                    <button
                      onClick={() => copyForLLM(item)}
                      title="Copy Claude Code prompt"
                      className="shrink-0 rounded-lg border border-border px-2 py-1 font-mono text-[10px] text-zinc-600 transition-all hover:border-[#2a2a2a] hover:text-zinc-400"
                    >
                      {copied === item.id ? '✓ copied' : '⌘ copy'}
                    </button>

                    {/* Expand chevron */}
                    <button
                      onClick={() => toggleExpand(item.id)}
                      className="shrink-0 text-zinc-700 transition-colors hover:text-zinc-500"
                    >
                      <svg
                        className={`h-3.5 w-3.5 transition-transform duration-150 ${isExpanded ? 'rotate-180' : ''}`}
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </button>
                  </div>

                  {/* ── Expanded detail ── */}
                  {isExpanded && (
                    <div className="space-y-4 border-t border-border bg-[#0d0d0d] px-4 py-4">
                      {editingId === item.id && editDraft ? (
                        /* ── Edit mode ── */
                        <>
                          {/* Title */}
                          <div>
                            <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">Title</p>
                            <input
                              value={editDraft.title}
                              onChange={(e) => setEditDraft((d) => d && { ...d, title: e.target.value })}
                              className="w-full rounded-lg border border-border bg-[#111] px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-700 focus:border-zinc-600 focus:outline-none"
                            />
                          </div>

                          {/* Priority */}
                          <div>
                            <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-600">Priority</p>
                            <div className="flex gap-2">
                              {(['low', 'medium', 'high'] as FeedbackPriority[]).map((p) => (
                                <button
                                  key={p}
                                  type="button"
                                  onClick={() => setEditDraft((d) => d && { ...d, priority: p })}
                                  className={`flex-1 rounded-lg border py-1.5 font-mono text-[10px] font-semibold uppercase transition-all ${
                                    editDraft.priority === p
                                      ? p === 'high' ? 'border-red-900/50 bg-red-950/30 text-red-400'
                                        : p === 'medium' ? 'border-amber-900/50 bg-amber-950/30 text-amber-500'
                                        : 'border-zinc-700 bg-zinc-900 text-zinc-300'
                                      : 'border-border text-zinc-700 hover:border-[#2a2a2a] hover:text-zinc-500'
                                  }`}
                                >
                                  {p}
                                </button>
                              ))}
                            </div>
                          </div>

                          {/* Description */}
                          <div>
                            <div className="mb-1 flex items-center gap-2">
                              <p className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Description</p>
                              <AISuggestBtn field="description" loading={editSuggesting === 'description'} disabled={!editDraft.title.trim()} onSuggest={(f) => suggestEdit(f, item.type)} />
                            </div>
                            <textarea
                              value={editDraft.description}
                              onChange={(e) => setEditDraft((d) => d && { ...d, description: e.target.value })}
                              rows={3}
                              className="w-full resize-none rounded-lg border border-border bg-[#111] px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-700 focus:border-zinc-600 focus:outline-none"
                            />
                          </div>

                          {/* Bug fields */}
                          {item.type === 'bug' && (
                            <>
                              <div>
                                <div className="mb-1 flex items-center gap-2">
                                  <p className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Steps to reproduce</p>
                                  <AISuggestBtn field="steps_to_reproduce" loading={editSuggesting === 'steps_to_reproduce'} disabled={!editDraft.title.trim()} onSuggest={(f) => suggestEdit(f, item.type)} />
                                </div>
                                <textarea
                                  value={editDraft.steps_to_reproduce}
                                  onChange={(e) => setEditDraft((d) => d && { ...d, steps_to_reproduce: e.target.value })}
                                  rows={2}
                                  className="w-full resize-none rounded-lg border border-border bg-[#111] px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-700 focus:border-zinc-600 focus:outline-none"
                                />
                              </div>
                              <div className="grid grid-cols-2 gap-3">
                                <div>
                                  <div className="mb-1 flex items-center gap-2">
                                    <p className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Expected</p>
                                    <AISuggestBtn field="expected_behavior" loading={editSuggesting === 'expected_behavior'} disabled={!editDraft.title.trim()} onSuggest={(f) => suggestEdit(f, item.type)} />
                                  </div>
                                  <textarea
                                    value={editDraft.expected_behavior}
                                    onChange={(e) => setEditDraft((d) => d && { ...d, expected_behavior: e.target.value })}
                                    rows={2}
                                    className="w-full resize-none rounded-lg border border-border bg-[#111] px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-700 focus:border-zinc-600 focus:outline-none"
                                  />
                                </div>
                                <div>
                                  <div className="mb-1 flex items-center gap-2">
                                    <p className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Actual</p>
                                    <AISuggestBtn field="actual_behavior" loading={editSuggesting === 'actual_behavior'} disabled={!editDraft.title.trim()} onSuggest={(f) => suggestEdit(f, item.type)} />
                                  </div>
                                  <textarea
                                    value={editDraft.actual_behavior}
                                    onChange={(e) => setEditDraft((d) => d && { ...d, actual_behavior: e.target.value })}
                                    rows={2}
                                    className="w-full resize-none rounded-lg border border-border bg-[#111] px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-700 focus:border-zinc-600 focus:outline-none"
                                  />
                                </div>
                              </div>
                            </>
                          )}

                          {/* Feature fields */}
                          {item.type === 'feature' && (
                            <>
                              <div>
                                <div className="mb-1 flex items-center gap-2">
                                  <p className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Use case</p>
                                  <AISuggestBtn field="use_case" loading={editSuggesting === 'use_case'} disabled={!editDraft.title.trim()} onSuggest={(f) => suggestEdit(f, item.type)} />
                                </div>
                                <textarea
                                  value={editDraft.use_case}
                                  onChange={(e) => setEditDraft((d) => d && { ...d, use_case: e.target.value })}
                                  rows={2}
                                  className="w-full resize-none rounded-lg border border-border bg-[#111] px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-700 focus:border-zinc-600 focus:outline-none"
                                />
                              </div>
                              <div>
                                <div className="mb-1 flex items-center gap-2">
                                  <p className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Impact</p>
                                  <AISuggestBtn field="user_impact" loading={editSuggesting === 'user_impact'} disabled={!editDraft.title.trim()} onSuggest={(f) => suggestEdit(f, item.type)} />
                                </div>
                                <textarea
                                  value={editDraft.user_impact}
                                  onChange={(e) => setEditDraft((d) => d && { ...d, user_impact: e.target.value })}
                                  rows={2}
                                  className="w-full resize-none rounded-lg border border-border bg-[#111] px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-700 focus:border-zinc-600 focus:outline-none"
                                />
                              </div>
                            </>
                          )}

                          {/* AI error */}
                          {editSuggestError && (
                            <div className="rounded-lg border border-red-900/40 bg-red-950/20 px-3 py-2">
                              <p className="font-mono text-[10px] text-red-400">AI error: {editSuggestError}</p>
                            </div>
                          )}

                          {/* Save / Cancel */}
                          <div className="flex items-center justify-end gap-3">
                            <button
                              onClick={cancelEdit}
                              className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
                            >
                              Cancel
                            </button>
                            <button
                              onClick={() => saveEdit(item.id)}
                              disabled={saving}
                              className="rounded-lg bg-white px-3 py-1.5 font-mono text-[10px] font-semibold text-black transition-opacity hover:opacity-90 disabled:opacity-40"
                            >
                              {saving ? 'Saving…' : 'Save changes'}
                            </button>
                          </div>
                        </>
                      ) : (
                        /* ── Read mode ── */
                        <>
                          {/* Description */}
                          <div>
                            <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">Description</p>
                            <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-400">{item.description}</p>
                          </div>

                          {/* Bug fields */}
                          {item.type === 'bug' && (
                            <>
                              {item.steps_to_reproduce && (
                                <div>
                                  <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">Steps to reproduce</p>
                                  <p className="whitespace-pre-wrap text-sm text-zinc-400">{item.steps_to_reproduce}</p>
                                </div>
                              )}
                              {(item.expected_behavior || item.actual_behavior) && (
                                <div className="grid grid-cols-2 gap-4">
                                  {item.expected_behavior && (
                                    <div>
                                      <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">Expected</p>
                                      <p className="whitespace-pre-wrap text-sm text-zinc-400">{item.expected_behavior}</p>
                                    </div>
                                  )}
                                  {item.actual_behavior && (
                                    <div>
                                      <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">Actual</p>
                                      <p className="whitespace-pre-wrap text-sm text-zinc-400">{item.actual_behavior}</p>
                                    </div>
                                  )}
                                </div>
                              )}
                              {item.screenshot_url && (
                                <ScreenshotPreview url={item.screenshot_url} />
                              )}
                            </>
                          )}

                          {/* Feature fields */}
                          {item.type === 'feature' && (
                            <>
                              {item.use_case && (
                                <div>
                                  <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">Use case</p>
                                  <p className="whitespace-pre-wrap text-sm text-zinc-400">{item.use_case}</p>
                                </div>
                              )}
                              {item.user_impact && (
                                <div>
                                  <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">Impact</p>
                                  <p className="whitespace-pre-wrap text-sm text-zinc-400">{item.user_impact}</p>
                                </div>
                              )}
                            </>
                          )}

                          {/* LLM prompt preview + copy */}
                          <div className="rounded-lg border border-[#1a1a1a] bg-background p-3">
                            <div className="mb-2 flex items-center justify-between">
                              <p className="font-mono text-[10px] uppercase tracking-wider text-zinc-700">
                                Claude Code prompt
                              </p>
                              <button
                                onClick={() => copyForLLM(item)}
                                className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
                              >
                                {copied === item.id ? '✓ Copied' : 'Copy'}
                              </button>
                            </div>
                            <pre className="whitespace-pre-wrap font-mono text-[10px] leading-relaxed text-zinc-600">
                              {buildLLMPrompt(item)}
                            </pre>
                          </div>

                          {/* Edit + Delete */}
                          <div className="flex items-center justify-end gap-4">
                            <button
                              onClick={() => startEdit(item)}
                              className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-300"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => deleteItem(item.id)}
                              className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-red-500"
                            >
                              Delete item
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </main>
    </div>
  )
}
