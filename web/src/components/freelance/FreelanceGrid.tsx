'use client'

import { useState, useMemo, useCallback } from 'react'
import { FreelanceCompany, FreelanceCompanyWithEval, FitTier } from '@/lib/types'
import { CompanyCard } from './CompanyCard'
import { FreelanceFilters, SortBy } from './FreelanceFilters'

interface FreelanceGridProps {
  companies: (FreelanceCompany | FreelanceCompanyWithEval)[]
}

/** Normalize a raw category value to a slug, stripping markdown artifacts */
function normalizeCategory(raw: string): string {
  let cat = raw.split('|')[0].trim()
  cat = cat.replace(/\*\*/g, '').trim()
  return cat.toLowerCase().replace(/\s+/g, '_')
}

export function FreelanceGrid({ companies }: FreelanceGridProps) {
  const [search, setSearch] = useState('')
  const [activeTiers, setActiveTiers] = useState<Set<FitTier>>(
    new Set<FitTier>(['HOT', 'WARM', 'COLD']),
  )
  const [activeCategories, setActiveCategories] = useState<Set<string>>(new Set())
  const [sortBy, setSortBy] = useState<SortBy>('score')

  const toggleTier = useCallback((t: FitTier) => {
    setActiveTiers((prev) => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t)
      else next.add(t)
      return next
    })
  }, [])

  const toggleCategory = useCallback((c: string) => {
    setActiveCategories((prev) => {
      const next = new Set(prev)
      if (next.has(c)) next.delete(c)
      else next.add(c)
      return next
    })
  }, [])

  // Pre-compute normalized categories
  const companiesWithCategory = useMemo(
    () => companies.map((c) => ({
      ...c,
      _normalizedCategory: c.category ? normalizeCategory(c.category) : null,
    })),
    [companies],
  )

  const tierCounts = useMemo(() => {
    const c: Partial<Record<FitTier, number>> = {}
    for (const company of companies) {
      if (company.fit_tier && company.fit_tier !== 'SKIP') {
        c[company.fit_tier] = (c[company.fit_tier] ?? 0) + 1
      }
    }
    return c
  }, [companies])

  const categoryCounts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const company of companiesWithCategory) {
      if (company._normalizedCategory) {
        c[company._normalizedCategory] = (c[company._normalizedCategory] ?? 0) + 1
      }
    }
    return c
  }, [companiesWithCategory])

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return companiesWithCategory.filter((company) => {
      if (!company.fit_tier || !activeTiers.has(company.fit_tier)) return false
      if (activeCategories.size > 0 && (!company._normalizedCategory || !activeCategories.has(company._normalizedCategory))) return false
      if (q) {
        const hay = `${company.name} ${company.city ?? ''} ${company.state ?? ''}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [companiesWithCategory, activeTiers, activeCategories, search])

  const sorted = useMemo(() => {
    const arr = [...filtered]
    if (sortBy === 'score') {
      arr.sort((a, b) => (b.fit_score ?? 0) - (a.fit_score ?? 0))
    } else if (sortBy === 'date') {
      arr.sort((a, b) => (b.first_seen_date ?? '').localeCompare(a.first_seen_date ?? ''))
    }
    return arr
  }, [filtered, sortBy])

  return (
    <div>
      <div className="mb-5">
        <FreelanceFilters
          onSearch={setSearch}
          onTierToggle={toggleTier}
          onCategoryToggle={toggleCategory}
          onSort={setSortBy}
          activeTiers={activeTiers}
          activeCategories={activeCategories}
          searchValue={search}
          sortBy={sortBy}
          tierCounts={tierCounts}
          categoryCounts={categoryCounts}
          totalFiltered={sorted.length}
          totalAll={companies.length}
        />
      </div>

      {sorted.length === 0 ? (
        <div className="py-16 text-center text-sm text-zinc-600">
          {search || activeCategories.size > 0 ? 'No matches for current filters.' : 'No companies found.'}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sorted.map((company) => (
            <CompanyCard key={company.company_id} company={company} />
          ))}
        </div>
      )}
    </div>
  )
}
