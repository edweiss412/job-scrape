'use client'

import { useState, useMemo, useCallback } from 'react'
import { JobWithRunMeta, Verdict, JobAction } from '@/lib/types'
import { JobCard } from './JobCard'
import { JobFilters, PayRange, SortBy, ActionFilter } from './JobFilters'
import { usePersistedFilters } from '@/lib/hooks/usePersistedFilters'
import { useJobActions } from '@/lib/hooks/useJobActions'

interface JobGridProps {
  jobs: JobWithRunMeta[]
  newJobIds?: Set<string>
}

const PAY_RANGES: Record<PayRange, [number, number]> = {
  all:       [0, Infinity],
  u100:      [1, 99_999],
  '100-130': [100_000, 130_000],
  '130-160': [130_000, 160_000],
  '160-200': [160_000, 200_000],
  '200+':    [200_000, Infinity],
  unlisted:  [0, 0],
}

function parseSalaryNum(salary: string | null): number {
  if (!salary) return 0
  const cleaned = salary.replace(/,/g, '')
  const nums = cleaned.match(/\d+(?:\.\d+)?[kK]?/g)
  if (!nums) return 0
  const values = nums.map((n) => {
    const v = parseFloat(n)
    return /[kK]$/.test(n) ? v * 1000 : v < 1000 ? v * 1000 : v
  }).filter((v) => v >= 20_000) // ignore noise like "5 years"
  if (!values.length) return 0
  return values.length > 1 ? (values[0] + values[values.length - 1]) / 2 : values[0]
}

function matchesPay(salaryNum: number, range: PayRange): boolean {
  if (range === 'all') return true
  if (range === 'unlisted') return salaryNum === 0
  const [lo, hi] = PAY_RANGES[range]
  return salaryNum >= lo && salaryNum <= hi
}

function matchesAction(jobAction: JobAction | undefined, filter: ActionFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'hide_dismissed') return jobAction !== 'dismissed'
  return jobAction === filter
}

export function JobGrid({ jobs, newJobIds = new Set() }: JobGridProps) {
  const [search, setSearch] = useState('')
  const { filters, update, hydrated } = usePersistedFilters()
  const { actions, toggle: toggleAction } = useJobActions()

  const activeVerdictsSet = useMemo(
    () => new Set<Verdict>(filters.activeVerdicts),
    [filters.activeVerdicts],
  )

  const setRecommended = useCallback((v: boolean | ((prev: boolean) => boolean)) => {
    update('recommended', typeof v === 'function' ? v(filters.recommended) : v)
  }, [update, filters.recommended])

  const toggleVerdict = useCallback((v: Verdict) => {
    const prev = new Set(filters.activeVerdicts)
    if (prev.has(v)) prev.delete(v)
    else prev.add(v)
    update('activeVerdicts', Array.from(prev))
  }, [update, filters.activeVerdicts])

  // Pre-compute salary numbers once
  const jobsWithSalary = useMemo(
    () => jobs.map((j) => ({ ...j, _salaryNum: parseSalaryNum(j.salary) })),
    [jobs],
  )

  const counts = useMemo(() => {
    const c: Partial<Record<Verdict, number>> = {}
    for (const job of jobs) {
      if (job.match_verdict) c[job.match_verdict] = (c[job.match_verdict] ?? 0) + 1
    }
    return c
  }, [jobs])

  const payCounts = useMemo(() => {
    const c: Partial<Record<PayRange, number>> = {}
    for (const job of jobsWithSalary) {
      for (const r of Object.keys(PAY_RANGES) as PayRange[]) {
        if (r === 'all') continue
        if (matchesPay(job._salaryNum, r)) c[r] = (c[r] ?? 0) + 1
      }
    }
    return c
  }, [jobsWithSalary])

  const actionCounts = useMemo(() => {
    const c: Partial<Record<JobAction, number>> = {}
    for (const [, action] of actions) {
      c[action] = (c[action] ?? 0) + 1
    }
    return c
  }, [actions])

  const hasNewJobs = newJobIds.size > 0 || jobs.some((j) => j.is_new_this_run)

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return jobsWithSalary.filter((job) => {
      if (!job.match_verdict) return false
      if (filters.recommended) {
        if (job.match_verdict === 'WEAK') return false
      } else {
        if (!activeVerdictsSet.has(job.match_verdict)) return false
      }
      if (filters.newOnly && !job.is_new_this_run && !newJobIds.has(job.job_id)) return false
      if (!matchesPay(job._salaryNum, filters.payRange)) return false
      if (!matchesAction(actions.get(job.job_id), filters.actionFilter)) return false
      if (q) {
        const hay = `${job.title} ${job.company} ${job.location}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [jobsWithSalary, filters.recommended, activeVerdictsSet, filters.newOnly, newJobIds, filters.payRange, filters.actionFilter, actions, search])

  const sorted = useMemo(() => {
    const arr = [...filtered]
    if (filters.sortBy === 'score') {
      arr.sort((a, b) => (b.match_score ?? 0) - (a.match_score ?? 0))
    } else if (filters.sortBy === 'date') {
      arr.sort((a, b) => (b.date_posted ?? '').localeCompare(a.date_posted ?? ''))
    } else if (filters.sortBy === 'salary') {
      arr.sort((a, b) => b._salaryNum - a._salaryNum)
    }
    return arr
  }, [filtered, filters.sortBy])

  // Don't render filters until hydrated to prevent SSR mismatch
  if (!hydrated) {
    return (
      <div className="py-16 text-center text-sm text-zinc-600">Loading…</div>
    )
  }

  return (
    <div>
      <div className="mb-5">
        <JobFilters
          onSearch={setSearch}
          onVerdictToggle={toggleVerdict}
          onLeaveRecommended={(v) => { update('recommended', false); update('activeVerdicts', [v]) }}
          onRecommendedToggle={() => setRecommended((r) => !r)}
          onNewOnly={(v) => update('newOnly', v)}
          onPayRange={(r) => update('payRange', r)}
          onSort={(s) => update('sortBy', s)}
          onActionFilter={(f) => update('actionFilter', f)}
          recommended={filters.recommended}
          activeVerdicts={activeVerdictsSet}
          newOnly={filters.newOnly}
          searchValue={search}
          payRange={filters.payRange}
          sortBy={filters.sortBy}
          actionFilter={filters.actionFilter}
          counts={counts}
          payCounts={payCounts}
          actionCounts={actionCounts}
          hasNewJobs={hasNewJobs}
          totalFiltered={sorted.length}
          totalAll={jobs.length}
        />
      </div>

      {sorted.length === 0 ? (
        <div className="py-16 text-center text-sm text-zinc-600">
          {search || filters.newOnly || filters.payRange !== 'all' || filters.actionFilter !== 'hide_dismissed' ? 'No matches for current filters.' : 'No evaluated jobs in this run.'}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sorted.map((job) => (
            <JobCard
              key={job.job_id}
              job={job}
              isNew={job.is_new_this_run || newJobIds.has(job.job_id)}
              action={actions.get(job.job_id)}
              onAction={(jobId, action) => toggleAction(jobId, action)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
