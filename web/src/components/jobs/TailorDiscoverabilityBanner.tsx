'use client'

import { useState, useEffect } from 'react'

const STORAGE_KEY = 'tailor-banner-dismissed'

export function TailorDiscoverabilityBanner() {
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
    <div className="mb-5 flex items-start gap-3 rounded-lg border border-teal-900/30 bg-teal-950/10 px-4 py-3">
      <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-teal-950/40">
        <svg className="h-3.5 w-3.5 text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
        </svg>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-teal-300">Resume tailoring available</p>
        <p className="mt-0.5 text-[11px] text-teal-700">
          Click into any Strong or Moderate match to generate a tailored resume for that specific role.
        </p>
      </div>
      <button
        onClick={dismiss}
        className="text-zinc-600 hover:text-zinc-400 transition-colors p-1 shrink-0"
        aria-label="Dismiss"
      >
        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}
