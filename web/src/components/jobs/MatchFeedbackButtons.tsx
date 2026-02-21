'use client'

import { useState } from 'react'
import { MatchFeedback } from '@/lib/types'
import { cn } from '@/lib/utils'

interface MatchFeedbackButtonsProps {
  jobId: string
  initialFeedback: MatchFeedback | null
}

export function MatchFeedbackButtons({ jobId, initialFeedback }: MatchFeedbackButtonsProps) {
  const [feedback, setFeedback] = useState<MatchFeedback | null>(initialFeedback)
  const [saving, setSaving] = useState(false)

  async function toggle(value: MatchFeedback) {
    const next = feedback === value ? null : value
    setFeedback(next)
    setSaving(true)
    try {
      await fetch('/api/job-actions/feedback', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, feedback: next }),
      })
    } catch {
      setFeedback(feedback) // revert
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[11px] text-zinc-600 mr-0.5">Match accuracy</span>
      <button
        onClick={() => toggle('up')}
        disabled={saving}
        className={cn(
          'rounded p-1.5 transition-colors',
          feedback === 'up'
            ? 'text-emerald-400 bg-emerald-950/40'
            : 'text-zinc-600 hover:text-zinc-400 hover:bg-zinc-800/50',
        )}
        title="Good match"
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21h-4.017c-.163 0-.326-.02-.485-.06L7 20m7-10V5a2 2 0 00-2-2h-.095c-.5 0-.905.405-.905.905 0 .714-.211 1.412-.608 2.006L7 11v9m7-10h-2M7 20H5a2 2 0 01-2-2v-6a2 2 0 012-2h2.5" />
        </svg>
      </button>
      <button
        onClick={() => toggle('down')}
        disabled={saving}
        className={cn(
          'rounded p-1.5 transition-colors',
          feedback === 'down'
            ? 'text-red-400 bg-red-950/40'
            : 'text-zinc-600 hover:text-zinc-400 hover:bg-zinc-800/50',
        )}
        title="Poor match"
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 14H5.236a2 2 0 01-1.789-2.894l3.5-7A2 2 0 018.736 3h4.018c.163 0 .326.02.485.06L17 4m-7 10v2a3.5 3.5 0 003.5 3.5h.174c.421 0 .762-.34.762-.762a2.466 2.466 0 01.733-1.757l2.83-2.83V4.5m-7 9.5h2M17 4h2a2 2 0 012 2v6a2 2 0 01-2 2h-2.5" />
        </svg>
      </button>
    </div>
  )
}
