'use client'

import { useState, useEffect } from 'react'
import { EvaluateForUserButton } from './EvaluateForUserButton'

interface Props {
  initialCount: number
  latestScrape: string | null
  evalStatus: 'idle' | 'pending' | 'running' | 'completed' | 'error'
}

export function NewJobsBanner({ initialCount, latestScrape, evalStatus }: Props) {
  const [count, setCount] = useState(initialCount)
  const [dismissed, setDismissed] = useState(false)

  // Re-fetch count periodically in case it changes (e.g. after scrape completes)
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch('/api/jobs/unevaluated')
        if (res.ok) {
          const data = await res.json()
          setCount(data.count ?? 0)
        }
      } catch { /* ignore */ }
    }, 60_000)
    return () => clearInterval(interval)
  }, [])

  if (dismissed || count === 0) return null
  if (evalStatus === 'pending' || evalStatus === 'running') return null

  const scrapeDate = latestScrape
    ? new Date(latestScrape + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : null

  return (
    <div className="mb-5 flex flex-col gap-3 rounded-lg border border-emerald-900/30 bg-emerald-950/10 px-4 py-3 sm:flex-row sm:items-center">
      <div className="flex items-start gap-3 flex-1">
        <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-950/40">
          <svg className="h-3.5 w-3.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
          </svg>
        </div>
        <div>
          <p className="text-xs font-medium text-emerald-300">
            {count} new job{count !== 1 ? 's' : ''} found
            {scrapeDate && <span className="text-emerald-600"> on {scrapeDate}</span>}
          </p>
          <p className="mt-0.5 text-[11px] text-emerald-700">
            Evaluate them against your resume to see match scores.
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <EvaluateForUserButton />
        <button
          onClick={() => setDismissed(true)}
          className="text-zinc-600 hover:text-zinc-400 transition-colors p-1"
          aria-label="Dismiss"
        >
          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  )
}
