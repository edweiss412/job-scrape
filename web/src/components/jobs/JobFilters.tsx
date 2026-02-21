'use client'

import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { Verdict, JobAction } from '@/lib/types'

const VERDICTS: Verdict[] = ['STRONG', 'MODERATE', 'STRETCH', 'WEAK']

const VERDICT_COLORS: Record<Verdict, string> = {
  STRONG:   'text-emerald-400 border-emerald-800 bg-emerald-950/40 hover:bg-emerald-950/70',
  MODERATE: 'text-amber-400 border-amber-800 bg-amber-950/40 hover:bg-amber-950/70',
  STRETCH:  'text-orange-400 border-orange-800 bg-orange-950/40 hover:bg-orange-950/70',
  WEAK:     'text-red-500 border-red-900 bg-red-950/40 hover:bg-red-950/70',
}

export type PayRange = 'all' | 'u100' | '100-130' | '130-160' | '160-200' | '200+' | 'unlisted'
export type SortBy = 'score' | 'date' | 'salary'
export type ActionFilter = 'all' | 'saved' | 'applied' | 'dismissed' | 'hide_dismissed'

const PAY_LABELS: Record<PayRange, string> = {
  all: 'Any pay',
  u100: '<$100k',
  '100-130': '$100–130k',
  '130-160': '$130–160k',
  '160-200': '$160–200k',
  '200+': '$200k+',
  unlisted: 'Unlisted',
}

const ACTION_FILTER_LABELS: Record<ActionFilter, string> = {
  all: 'All',
  hide_dismissed: 'Hide dismissed',
  saved: 'Saved',
  applied: 'Applied',
  dismissed: 'Dismissed',
}

const ACTION_FILTER_COLORS: Record<ActionFilter, string> = {
  all: '',
  hide_dismissed: '',
  saved: 'text-blue-400 border-blue-800 bg-blue-950/40 hover:bg-blue-950/70',
  applied: 'text-emerald-400 border-emerald-800 bg-emerald-950/40 hover:bg-emerald-950/70',
  dismissed: 'text-zinc-400 border-zinc-700 bg-zinc-900/40 hover:bg-zinc-800/70',
}

interface JobFiltersProps {
  onSearch: (q: string) => void
  onVerdictToggle: (v: Verdict) => void
  onLeaveRecommended: (v: Verdict) => void
  onRecommendedToggle: () => void
  onNewOnly: (v: boolean) => void
  onPayRange: (r: PayRange) => void
  onSort: (s: SortBy) => void
  onActionFilter: (f: ActionFilter) => void
  recommended: boolean
  activeVerdicts: Set<Verdict>
  newOnly: boolean
  searchValue: string
  payRange: PayRange
  sortBy: SortBy
  actionFilter: ActionFilter
  counts: Partial<Record<Verdict, number>>
  payCounts: Partial<Record<PayRange, number>>
  actionCounts: Partial<Record<JobAction, number>>
  hasNewJobs: boolean
  totalFiltered: number
  totalAll: number
}

export function JobFilters({
  onSearch, onVerdictToggle, onLeaveRecommended, onRecommendedToggle, onNewOnly, onPayRange, onSort, onActionFilter,
  recommended, activeVerdicts, newOnly, searchValue, payRange, sortBy, actionFilter,
  counts, payCounts, actionCounts, hasNewJobs, totalFiltered, totalAll,
}: JobFiltersProps) {
  const [filtersExpanded, setFiltersExpanded] = useState(false)

  const pillBase = 'rounded-full border px-2.5 py-1 text-[11px] font-mono font-semibold uppercase tracking-wider transition-all'
  const pillOff = 'border-border text-zinc-600 bg-transparent hover:border-[#333] hover:text-zinc-400'
  const pillOn = 'border-zinc-500 bg-zinc-800 text-white'

  const recommendedCount = (counts.STRONG ?? 0) + (counts.MODERATE ?? 0) + (counts.STRETCH ?? 0)
  const hasAnyActions = (actionCounts.saved ?? 0) + (actionCounts.applied ?? 0) + (actionCounts.dismissed ?? 0) > 0

  // Show dot indicator when secondary filters are non-default
  const hasActiveSecondaryFilters = payRange !== 'all' || actionFilter !== 'hide_dismissed'

  return (
    <div className="space-y-2.5">
      {/* Row 1: search + sort */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1 sm:w-52 sm:flex-none">
            <Input
              placeholder="Search jobs…"
              value={searchValue}
              onChange={(e) => onSearch(e.target.value)}
              icon={
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              }
            />
          </div>

          <select
            value={sortBy}
            onChange={(e) => onSort(e.target.value as SortBy)}
            className="shrink-0 rounded-lg border border-border bg-[#111] px-2.5 py-1.5 text-[11px] font-mono text-zinc-400 focus:outline-none focus:border-zinc-600"
          >
            <option value="score">Sort: Score</option>
            <option value="date">Sort: Date posted</option>
            <option value="salary">Sort: Salary</option>
          </select>
        </div>

        <span className="text-[11px] text-zinc-700 sm:ml-auto">
          {totalFiltered === totalAll ? `${totalAll} jobs` : `${totalFiltered} of ${totalAll}`}
        </span>
      </div>

      {/* Row 2: verdict filters + Filters toggle */}
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          onClick={onRecommendedToggle}
          className={cn(pillBase, recommended ? pillOn : pillOff)}
        >
          Recommended <span className="opacity-60">{recommendedCount}</span>
        </button>

        {/* Separator between recommended and individual verdicts */}
        <span className="h-4 w-px bg-zinc-800" />

        {VERDICTS.map((v) => {
          const count = counts[v] ?? 0
          if (!count) return null
          const active = !recommended && activeVerdicts.has(v)
          return (
            <button
              key={v}
              onClick={() => { if (recommended) onLeaveRecommended(v); else onVerdictToggle(v) }}
              className={cn(
                pillBase,
                !recommended && active ? VERDICT_COLORS[v] : pillOff,
                recommended && 'opacity-50',
              )}
            >
              {v} <span className="opacity-60">{count}</span>
            </button>
          )
        })}

        {hasNewJobs && (
          <button
            onClick={() => onNewOnly(!newOnly)}
            className={cn(
              pillBase,
              newOnly ? 'border-blue-700 bg-blue-950/50 text-blue-400' : pillOff,
            )}
          >
            New only
          </button>
        )}

        {/* Filters toggle for secondary rows */}
        <span className="h-4 w-px bg-zinc-800" />
        <button
          onClick={() => setFiltersExpanded(prev => !prev)}
          className={cn(
            pillBase,
            filtersExpanded ? pillOn : pillOff,
            'relative',
          )}
        >
          Filters
          {hasActiveSecondaryFilters && !filtersExpanded && (
            <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-amber-500" />
          )}
        </button>
      </div>

      {/* Collapsible secondary filter rows */}
      {filtersExpanded && (
        <>
          {/* Row 3: pay range */}
          <div className="flex flex-wrap items-center gap-1.5">
            {(Object.keys(PAY_LABELS) as PayRange[]).map((r) => {
              const count = payCounts[r] ?? 0
              if (r !== 'all' && !count) return null
              return (
                <button
                  key={r}
                  onClick={() => onPayRange(r)}
                  className={cn(
                    pillBase,
                    payRange === r ? pillOn : pillOff,
                  )}
                >
                  {PAY_LABELS[r]}
                  {r !== 'all' && <span className="opacity-60 ml-1">{count}</span>}
                </button>
              )
            })}
          </div>

          {/* Row 4: action filters — shown when user has any actions */}
          {hasAnyActions && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] text-zinc-700 mr-0.5">Status:</span>
              {(Object.keys(ACTION_FILTER_LABELS) as ActionFilter[]).map((f) => {
                const count = f === 'all' || f === 'hide_dismissed' ? null : actionCounts[f] ?? 0
                if (count === 0 && f !== 'all' && f !== 'hide_dismissed') return null
                const isActive = actionFilter === f
                const colorClass = ACTION_FILTER_COLORS[f]
                return (
                  <button
                    key={f}
                    onClick={() => onActionFilter(f)}
                    className={cn(
                      pillBase,
                      isActive ? (colorClass || pillOn) : pillOff,
                    )}
                  >
                    {ACTION_FILTER_LABELS[f]}
                    {count != null && count > 0 && <span className="opacity-60 ml-1">{count}</span>}
                  </button>
                )
              })}
            </div>
          )}
        </>
      )}
    </div>
  )
}
