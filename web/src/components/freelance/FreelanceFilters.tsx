'use client'

import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { FitTier } from '@/lib/types'

const TIERS: FitTier[] = ['HOT', 'WARM', 'COLD']

const TIER_COLORS: Record<FitTier, string> = {
  HOT:  'text-emerald-400 border-emerald-800 bg-emerald-950/40 hover:bg-emerald-950/70',
  WARM: 'text-amber-400 border-amber-800 bg-amber-950/40 hover:bg-amber-950/70',
  COLD: 'text-zinc-400 border-zinc-700 bg-zinc-900/40 hover:bg-zinc-800/60',
  SKIP: 'text-zinc-600 border-zinc-800 bg-zinc-950/40 hover:bg-zinc-900/60',
}

export type SortBy = 'score' | 'date'

const CATEGORY_LABELS: Record<string, string> = {
  av_rental: 'AV Rental',
  production_co: 'Production Co.',
  venue: 'Venue',
  touring: 'Touring',
  corporate_av: 'Corporate AV',
  university: 'University',
}

interface FreelanceFiltersProps {
  onSearch: (q: string) => void
  onTierToggle: (t: FitTier) => void
  onSelectAllTiers: () => void
  onCategoryToggle: (c: string) => void
  onSort: (s: SortBy) => void
  activeTiers: Set<FitTier>
  activeCategories: Set<string>
  searchValue: string
  sortBy: SortBy
  tierCounts: Partial<Record<FitTier, number>>
  categoryCounts: Record<string, number>
  totalFiltered: number
  totalAll: number
}

export function FreelanceFilters({
  onSearch, onTierToggle, onSelectAllTiers, onCategoryToggle, onSort,
  activeTiers, activeCategories, searchValue, sortBy,
  tierCounts, categoryCounts, totalFiltered, totalAll,
}: FreelanceFiltersProps) {
  const pillBase = 'rounded-full border px-2.5 py-1 text-[11px] font-mono font-semibold uppercase tracking-wider transition-all cursor-pointer'
  const pillOff = 'border-border text-zinc-600 bg-transparent hover:border-[#333] hover:text-zinc-400'

  const categories = Object.entries(categoryCounts)
    .sort(([, a], [, b]) => b - a)

  return (
    <div className="space-y-2.5">
      {/* Row 1: search + sort + count */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1 sm:w-52 sm:flex-none">
            <Input
              placeholder="Search companies..."
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
            <option value="date">Sort: Date discovered</option>
          </select>
        </div>

        <span className="text-[11px] text-zinc-700 sm:ml-auto">
          {totalFiltered === totalAll ? `${totalAll} companies` : `${totalFiltered} of ${totalAll}`}
        </span>
      </div>

      {/* Row 2: tier filter pills */}
      <div className="flex flex-wrap items-center gap-1.5">
        {(() => {
          const allActive = TIERS.every((t) => activeTiers.has(t))
          return (
            <button
              onClick={onSelectAllTiers}
              className={cn(
                pillBase,
                allActive ? 'border-zinc-500 bg-zinc-800 text-white' : pillOff,
              )}
            >
              All
            </button>
          )
        })()}
        {TIERS.map((t) => {
          const count = tierCounts[t] ?? 0
          if (!count) return null
          const active = activeTiers.has(t)
          return (
            <button
              key={t}
              onClick={() => onTierToggle(t)}
              className={cn(
                pillBase,
                active ? TIER_COLORS[t] : pillOff,
              )}
            >
              {t} <span className="opacity-60">{count}</span>
            </button>
          )
        })}
      </div>

      {/* Row 3: category pills */}
      {categories.length > 1 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {categories.map(([cat, count]) => {
            const active = activeCategories.has(cat)
            const label = CATEGORY_LABELS[cat] ?? cat.replace(/_/g, ' ')
            return (
              <button
                key={cat}
                onClick={() => onCategoryToggle(cat)}
                className={cn(
                  pillBase,
                  active ? 'border-zinc-500 bg-zinc-800 text-white' : pillOff,
                )}
              >
                {label} <span className="opacity-60">{count}</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
