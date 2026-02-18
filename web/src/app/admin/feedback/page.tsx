'use client'

import { useState, useEffect, useCallback } from 'react'
import { Nav } from '@/components/layout/nav'
import { Feedback, FeedbackStatus, FeedbackPriority, FeedbackType } from '@/lib/types'

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

export default function AdminFeedbackPage() {
  const [items, setItems] = useState<Feedback[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [copied, setCopied] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('')

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
          <span className="ml-2 rounded-full border border-[#1f1f1f] px-2.5 py-1 font-mono text-[10px] text-zinc-600">
            {counts.bugs} bugs
          </span>
          <span className="rounded-full border border-[#1f1f1f] px-2.5 py-1 font-mono text-[10px] text-zinc-600">
            {counts.features} features
          </span>
        </div>

        {/* Filters */}
        <div className="mb-4 flex flex-wrap gap-2">
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="rounded-lg border border-[#1f1f1f] bg-[#111] px-2.5 py-1.5 font-mono text-[10px] uppercase text-zinc-500 focus:border-zinc-600 focus:outline-none"
          >
            <option value="">All types</option>
            <option value="bug">Bug</option>
            <option value="feature">Feature</option>
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-[#1f1f1f] bg-[#111] px-2.5 py-1.5 font-mono text-[10px] uppercase text-zinc-500 focus:border-zinc-600 focus:outline-none"
          >
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="in_progress">In Progress</option>
            <option value="done">Done</option>
          </select>
          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
            className="rounded-lg border border-[#1f1f1f] bg-[#111] px-2.5 py-1.5 font-mono text-[10px] uppercase text-zinc-500 focus:border-zinc-600 focus:outline-none"
          >
            <option value="">All priorities</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          {(typeFilter || statusFilter || priorityFilter) && (
            <button
              onClick={() => { setTypeFilter(''); setStatusFilter(''); setPriorityFilter('') }}
              className="rounded-lg border border-[#1f1f1f] px-2.5 py-1.5 font-mono text-[10px] text-zinc-600 transition-colors hover:border-[#2a2a2a] hover:text-zinc-400"
            >
              Clear
            </button>
          )}
        </div>

        {/* List */}
        {loading ? (
          <div className="py-16 text-center font-mono text-xs text-zinc-700">Loading…</div>
        ) : !filtered.length ? (
          <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-12 text-center text-sm text-zinc-600">
            No feedback items match your filters.
          </div>
        ) : (
          <div className="space-y-2">
            {filtered.map((item) => {
              const isExpanded = expanded.has(item.id)

              return (
                <div
                  key={item.id}
                  className="overflow-hidden rounded-xl border border-[#1f1f1f] bg-[#111] transition-colors hover:border-[#252525]"
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
                      <span className="hidden max-w-[100px] truncate font-mono text-[10px] text-zinc-700 sm:block">
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
                      className="shrink-0 rounded-lg border border-[#1f1f1f] px-2 py-1 font-mono text-[10px] text-zinc-600 transition-all hover:border-[#2a2a2a] hover:text-zinc-400"
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
                    <div className="space-y-4 border-t border-[#1f1f1f] bg-[#0d0d0d] px-4 py-4">
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
                      <div className="rounded-lg border border-[#1a1a1a] bg-[#0a0a0a] p-3">
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

                      {/* Delete */}
                      <div className="flex justify-end">
                        <button
                          onClick={() => deleteItem(item.id)}
                          className="font-mono text-[10px] text-zinc-700 transition-colors hover:text-red-500"
                        >
                          Delete item
                        </button>
                      </div>
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
