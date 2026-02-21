'use client'

import { useRouter } from 'next/navigation'
import { JobWithRunMeta, JobAction } from '@/lib/types'
import { VerdictBadge, NewBadge } from '@/components/ui/badge'
import { getSourceLabel, normalizeLocation, cn, ACTION_STYLES } from '@/lib/utils'

interface JobCardProps {
  job: JobWithRunMeta
  isNew?: boolean
  runDate?: string
  action?: JobAction
  onAction?: (jobId: string, action: JobAction) => void
}

export function JobCard({ job, isNew, action, onAction }: JobCardProps) {
  const router = useRouter()

  if (!job.match_verdict) return null

  const city = normalizeLocation(job.location)
  const actionStyle = action ? ACTION_STYLES[action] : null

  return (
    <div
      onClick={() => router.push(`/opportunities/fulltime/${job.job_id}`)}
      className={cn(
        'group rounded-xl border p-5 transition-all duration-150 cursor-pointer',
        'bg-[#111] border-border',
        'hover:border-[#2a2a2a] hover:bg-surface-2',
        action && `border-l-2 ${actionStyle!.border}`,
      )}
    >
      {/* Top row */}
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <VerdictBadge verdict={job.match_verdict} score={job.match_score} size="sm" />
            {isNew && <NewBadge />}
            {action && (
              <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-mono font-semibold uppercase tracking-wider', actionStyle!.text, actionStyle!.bg)}>
                {ACTION_STYLES[action].label}
              </span>
            )}
          </div>
          <h3 className="mt-2 truncate text-sm font-semibold text-white group-hover:text-zinc-100">
            {job.title}
          </h3>
          <p className="mt-0.5 text-xs text-zinc-500">{job.company}</p>
        </div>

        {job.tier && (
          <span className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-mono text-zinc-600 border border-border">
            {job.tier}
          </span>
        )}
      </div>

      {/* Summary snippet */}
      {job.job_summary && (
        <p className="mb-3 text-xs leading-relaxed text-zinc-500 line-clamp-2">
          {job.job_summary}
        </p>
      )}

      {/* Footer meta */}
      <div className="flex flex-wrap items-center gap-3 text-[11px] text-zinc-600">
        {city && (
          <span className="flex items-center gap-1">
            <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            {city}
          </span>
        )}
        {job.salary && (
          <span className="text-emerald-600">{job.salary}</span>
        )}
        {getSourceLabel(job.source) && (
          <span className="ml-auto text-zinc-700">{getSourceLabel(job.source)}</span>
        )}
        {job.match_verdict && ['STRONG', 'MODERATE'].includes(job.match_verdict) && (
          <svg className="h-3 w-3 text-orange-800/60" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <title>Resume tailoring available</title>
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
          </svg>
        )}
      </div>

      {/* Action buttons */}
      {onAction && (
        <div className="mt-3 flex items-center gap-1 border-t border-[#1a1a1a] pt-3">
          <ActionBtn
            active={action === 'saved'}
            onClick={(e) => { e.stopPropagation(); onAction(job.job_id, 'saved') }}
            label="Save"
            activeClass="text-blue-400"
          >
            <svg className="h-3.5 w-3.5" fill={action === 'saved' ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
            </svg>
          </ActionBtn>
          <ActionBtn
            active={action === 'applied'}
            onClick={(e) => { e.stopPropagation(); onAction(job.job_id, 'applied') }}
            label="Applied"
            activeClass="text-emerald-400"
          >
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </ActionBtn>
          <ActionBtn
            active={action === 'dismissed'}
            onClick={(e) => { e.stopPropagation(); onAction(job.job_id, 'dismissed') }}
            label="Dismiss"
            activeClass="text-zinc-400"
          >
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </ActionBtn>
        </div>
      )}
    </div>
  )
}

function ActionBtn({
  active,
  onClick,
  label,
  activeClass,
  children,
}: {
  active: boolean
  onClick: (e: React.MouseEvent) => void
  label: string
  activeClass: string
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex items-center gap-1 rounded-md px-2 py-1 text-[11px] transition-colors',
        active
          ? `${activeClass} bg-zinc-800/60`
          : 'text-zinc-600 hover:text-zinc-400 hover:bg-zinc-800/40',
      )}
    >
      {children}
      <span>{label}</span>
    </button>
  )
}
