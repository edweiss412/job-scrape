'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'

interface CollapsibleSectionProps {
  title: string
  subtitle?: string
  defaultOpen?: boolean
  badge?: string
  children: React.ReactNode
}

export function CollapsibleSection({
  title,
  subtitle,
  defaultOpen = true,
  badge,
  children,
}: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="rounded-xl border border-border bg-[#111]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-6 py-4 text-left"
      >
        <svg
          className={cn(
            'h-3.5 w-3.5 shrink-0 text-zinc-500 transition-transform duration-200',
            open && 'rotate-90',
          )}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-white">{title}</h2>
            {badge && (
              <span className="rounded border border-zinc-800 bg-zinc-900/60 px-1.5 py-0.5 text-[10px] font-mono text-zinc-500">
                {badge}
              </span>
            )}
          </div>
          {subtitle && (
            <p className="mt-0.5 text-xs text-zinc-600">{subtitle}</p>
          )}
        </div>
      </button>
      {open && <div className="border-t border-[#1a1a1a]">{children}</div>}
    </div>
  )
}
