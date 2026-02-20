'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'

const STORAGE_KEY = 'profile-nudge-dismissed'

export function ProfileNudgeBanner() {
  const [dismissed, setDismissed] = useState(true) // default hidden to avoid flash

  useEffect(() => {
    setDismissed(localStorage.getItem(STORAGE_KEY) === '1')
  }, [])

  function dismiss() {
    setDismissed(true)
    localStorage.setItem(STORAGE_KEY, '1')
  }

  if (dismissed) return null

  return (
    <div className="mb-5 flex items-start gap-3 rounded-lg border border-indigo-900/30 bg-indigo-950/10 px-4 py-3">
      <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-950/40">
        <svg className="h-3.5 w-3.5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-indigo-300">Improve your match accuracy</p>
        <p className="mt-0.5 text-[11px] text-indigo-700">
          Adding target roles and career context to your profile helps the AI score jobs more accurately.
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <Link
          href="/profile"
          className="font-mono text-[11px] text-indigo-400 hover:text-indigo-300 transition-colors whitespace-nowrap"
        >
          Go to profile →
        </Link>
        <button
          onClick={dismiss}
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
