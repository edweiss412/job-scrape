'use client'

import { useJobActions } from '@/lib/hooks/useJobActions'
import { cn } from '@/lib/utils'

interface JobDetailActionsProps {
  jobId: string
}

export function JobDetailActions({ jobId }: JobDetailActionsProps) {
  const { actions, toggle } = useJobActions()
  const current = actions.get(jobId)

  return (
    <div className="flex items-center gap-1">
      <DetailActionBtn
        active={current === 'saved'}
        onClick={() => toggle(jobId, 'saved')}
        label="Save"
        activeClass="text-blue-400 border-blue-800 bg-blue-950/40"
      >
        <svg className="h-3.5 w-3.5" fill={current === 'saved' ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
        </svg>
      </DetailActionBtn>
      <DetailActionBtn
        active={current === 'applied'}
        onClick={() => toggle(jobId, 'applied')}
        label={current === 'applied' ? 'Applied' : 'Mark Applied'}
        activeClass="text-emerald-400 border-emerald-800 bg-emerald-950/40"
      >
        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      </DetailActionBtn>
      <DetailActionBtn
        active={current === 'dismissed'}
        onClick={() => toggle(jobId, 'dismissed')}
        label="Dismiss"
        activeClass="text-zinc-400 border-zinc-600 bg-zinc-800/60"
      >
        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </DetailActionBtn>
    </div>
  )
}

function DetailActionBtn({
  active,
  onClick,
  label,
  activeClass,
  children,
}: {
  active: boolean
  onClick: () => void
  label: string
  activeClass: string
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-[11px] font-medium transition-colors',
        active
          ? activeClass
          : 'border-[#333] text-zinc-500 hover:text-zinc-300 hover:border-zinc-600 bg-transparent',
      )}
    >
      {children}
      <span>{label}</span>
    </button>
  )
}
