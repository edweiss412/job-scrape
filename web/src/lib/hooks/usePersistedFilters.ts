'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { Verdict } from '@/lib/types'
import { PayRange, SortBy } from '@/components/jobs/JobFilters'

const STORAGE_KEY = 'job-grid-filters'

interface StoredFilters {
  recommended: boolean
  activeVerdicts: Verdict[]
  payRange: PayRange
  sortBy: SortBy
  newOnly: boolean
}

const DEFAULTS: StoredFilters = {
  recommended: true,
  activeVerdicts: ['STRONG', 'MODERATE', 'STRETCH', 'WEAK'],
  payRange: 'all',
  sortBy: 'score',
  newOnly: false,
}

export function usePersistedFilters() {
  const [filters, setFilters] = useState<StoredFilters>(DEFAULTS)
  const [hydrated, setHydrated] = useState(false)
  const skipWrite = useRef(true)

  // Read from localStorage on mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as Partial<StoredFilters>
        setFilters({
          recommended: parsed.recommended ?? DEFAULTS.recommended,
          activeVerdicts: parsed.activeVerdicts ?? DEFAULTS.activeVerdicts,
          payRange: parsed.payRange ?? DEFAULTS.payRange,
          sortBy: parsed.sortBy ?? DEFAULTS.sortBy,
          newOnly: parsed.newOnly ?? DEFAULTS.newOnly,
        })
      }
    } catch { /* ignore corrupt data */ }
    setHydrated(true)
    // Allow writes after initial hydration
    skipWrite.current = false
  }, [])

  // Write to localStorage on change (skip the initial hydration write)
  useEffect(() => {
    if (skipWrite.current) return
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(filters))
    } catch { /* storage full or unavailable */ }
  }, [filters])

  const update = useCallback(<K extends keyof StoredFilters>(key: K, value: StoredFilters[K]) => {
    setFilters((prev) => ({ ...prev, [key]: value }))
  }, [])

  return { filters, update, setFilters, hydrated }
}
