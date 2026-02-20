'use client'

import { useState } from 'react'
import type { TailoringSuggestion } from '@/lib/types'

export type CardState = 'pending' | 'accepted' | 'skipped'

interface Props {
  suggestion: TailoringSuggestion
  status: CardState
  onAccept: (id: string, finalText: string) => void
  onSkip: (id: string) => void
  onReset: (id: string) => void
}

const PRIORITY_STYLES = {
  high:   { bg: 'bg-orange-950/30', border: 'border-orange-800/40', text: 'text-orange-400', label: 'HIGH' },
  medium: { bg: 'bg-yellow-950/20', border: 'border-yellow-800/30', text: 'text-yellow-500', label: 'MED' },
  low:    { bg: 'bg-zinc-800/30',   border: 'border-zinc-700/40',   text: 'text-zinc-500',   label: 'LOW' },
} as const

const TYPE_STYLES = {
  rewrite: { text: 'text-blue-400',    label: 'REWRITE' },
  add:     { text: 'text-emerald-400', label: 'ADD' },
  remove:  { text: 'text-red-400',     label: 'REMOVE' },
} as const

export function TailoringSuggestionCard({ suggestion, status, onAccept, onSkip, onReset }: Props) {
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState(suggestion.after)
  const [showWhy, setShowWhy] = useState(false)

  const priority = PRIORITY_STYLES[suggestion.priority]
  const type = TYPE_STYLES[suggestion.type]

  function handleAccept() {
    onAccept(suggestion.id, editText)
    setEditing(false)
  }

  function handleSkip() {
    onSkip(suggestion.id)
  }

  function handleReset() {
    setEditText(suggestion.after)
    onReset(suggestion.id)
  }

  function handleEdit() {
    setEditing(true)
  }

  function handleSaveEdit() {
    handleAccept()
  }

  function handleCancelEdit() {
    setEditText(suggestion.after)
    setEditing(false)
  }

  const isResolved = status === 'accepted' || status === 'skipped'

  return (
    <div
      className={`rounded-lg border overflow-hidden transition-all duration-200 ${
        status === 'accepted'
          ? 'border-emerald-800/40 bg-emerald-950/10'
          : status === 'skipped'
            ? 'border-zinc-800/30 bg-zinc-900/20 opacity-50'
            : 'border-border bg-[#0c0c0c]'
      }`}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[#1a1a1a] bg-background">
        <span className={`font-mono text-[9px] font-bold tracking-widest ${type.text}`}>
          {type.label}
        </span>
        <span className={`rounded px-1.5 py-0.5 font-mono text-[9px] font-bold tracking-wider border ${priority.bg} ${priority.border} ${priority.text}`}>
          {priority.label}
        </span>
        <span className="flex-1 truncate text-[11px] text-zinc-500 font-medium" style={{ fontFamily: 'Syne, sans-serif' }}>
          {suggestion.section}
        </span>
        {status === 'accepted' && (
          <span className="flex items-center gap-1 text-[10px] text-emerald-500 font-mono">
            <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
            </svg>
            accepted
          </span>
        )}
        {status === 'skipped' && (
          <span className="text-[10px] text-zinc-600 font-mono">skipped</span>
        )}
      </div>

      {/* Before section (rewrite & remove) */}
      {suggestion.before && (
        <div className="px-3 py-2.5 bg-[#1a0e0a] border-b border-[#2a1a12]">
          <div className="font-mono text-[9px] font-bold tracking-widest text-red-500/70 mb-1 uppercase">Before</div>
          <div className="text-[13px] leading-relaxed text-[#c0a090]">{suggestion.before}</div>
        </div>
      )}

      {/* After section / edit mode */}
      {suggestion.type !== 'remove' && (
        <div className={`px-3 py-2.5 ${suggestion.before ? 'bg-[#0a1a0f]' : 'bg-[#0a1a0f] border-b border-[#1a2a1a]'}`}>
          <div className="font-mono text-[9px] font-bold tracking-widest text-emerald-500/70 mb-1 uppercase">
            {suggestion.type === 'add' ? 'Add' : 'After'}
          </div>
          {editing ? (
            <div className="space-y-2">
              <textarea
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                className="w-full rounded-md border border-emerald-800/30 bg-[#0d1a0f] px-2.5 py-2 text-[13px] leading-relaxed text-emerald-200 placeholder-zinc-600 focus:border-emerald-600/50 focus:outline-none resize-y min-h-16"
                rows={3}
                autoFocus
              />
              <div className="flex gap-2">
                <button
                  onClick={handleSaveEdit}
                  className="rounded-md border border-emerald-800/40 bg-emerald-950/30 px-3 py-1 text-[11px] font-medium text-emerald-400 hover:bg-emerald-950/50 transition-colors"
                >
                  Save & Accept
                </button>
                <button
                  onClick={handleCancelEdit}
                  className="rounded-md border border-zinc-800/40 px-3 py-1 text-[11px] font-medium text-zinc-500 hover:text-zinc-300 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="text-[13px] leading-relaxed text-[#90c0a0]">{editText}</div>
          )}
        </div>
      )}

      {/* Why (expandable) */}
      {suggestion.reasoning && (
        <button
          onClick={() => setShowWhy(!showWhy)}
          className="w-full text-left px-3 py-1.5 bg-[#0d0d0d] border-t border-[#1a1a1a] flex items-center gap-2 hover:bg-[#111] transition-colors"
        >
          <span className="font-mono text-[9px] text-zinc-600 uppercase tracking-wider">Why</span>
          <svg
            className={`h-2.5 w-2.5 text-zinc-600 transition-transform ${showWhy ? 'rotate-180' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
          {!showWhy && (
            <span className="text-[11px] text-zinc-700 truncate">{suggestion.reasoning}</span>
          )}
        </button>
      )}
      {showWhy && suggestion.reasoning && (
        <div className="px-3 py-2 bg-[#0d0d0d] border-t border-[#141414]">
          <p className="text-[12px] text-zinc-500 leading-relaxed italic">{suggestion.reasoning}</p>
        </div>
      )}

      {/* Actions */}
      {!editing && (
        <div className="flex items-center gap-1 px-3 py-2 bg-[#080808] border-t border-[#1a1a1a]">
          {isResolved ? (
            <button
              onClick={handleReset}
              className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-medium text-zinc-600 hover:text-zinc-400 hover:bg-zinc-800/30 transition-colors"
            >
              <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              undo
            </button>
          ) : (
            <>
              <button
                onClick={handleAccept}
                className="flex items-center gap-1.5 rounded-md border border-emerald-800/30 bg-emerald-950/20 px-2.5 py-1 text-[11px] font-medium text-emerald-400 hover:bg-emerald-950/40 transition-colors"
              >
                <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                </svg>
                Accept
              </button>
              <button
                onClick={handleEdit}
                className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-medium text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/30 transition-colors"
              >
                <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
                Edit
              </button>
              <button
                onClick={handleSkip}
                className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-medium text-zinc-600 hover:text-zinc-400 hover:bg-zinc-800/30 transition-colors"
              >
                <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
                Skip
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
