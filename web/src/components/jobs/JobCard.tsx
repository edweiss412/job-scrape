import Link from 'next/link'
import { JobWithRunMeta } from '@/lib/types'
import { VerdictBadge, NewBadge } from '@/components/ui/badge'
import { getSourceLabel, normalizeLocation, cn } from '@/lib/utils'

interface JobCardProps {
  job: JobWithRunMeta
  isNew?: boolean
  runDate?: string
}

export function JobCard({ job, isNew }: JobCardProps) {
  if (!job.match_verdict) return null

  const city = normalizeLocation(job.location)

  return (
    <Link
      href={`/opportunities/fulltime/${job.job_id}`}
      className={cn(
        'group block rounded-xl border p-5 transition-all duration-150',
        'bg-[#111] border-border',
        'hover:border-[#2a2a2a] hover:bg-surface-2',
      )}
    >
      {/* Top row */}
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <VerdictBadge verdict={job.match_verdict} score={job.match_score} size="sm" />
            {isNew && <NewBadge />}
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
      </div>
    </Link>
  )
}
