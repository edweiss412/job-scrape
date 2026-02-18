'use client'

import { useState, useMemo, useCallback } from 'react'
import { JobWithRunMeta, Verdict } from '@/lib/types'
import { JobCard } from './JobCard'
import { JobFilters, PayRange, SortBy } from './JobFilters'

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

export function JobGrid({ jobs, newJobIds = new Set() }: JobGridProps) {
  const [search, setSearch] = useState('')
  const [recommended, setRecommended] = useState(true)
  const [activeVerdicts, setActiveVerdicts] = useState<Set<Verdict>>(
    new Set<Verdict>(['STRONG', 'MODERATE', 'STRETCH', 'WEAK']),
  )
  const [newOnly, setNewOnly] = useState(false)
  const [payRange, setPayRange] = useState<PayRange>('all')
  const [sortBy, setSortBy] = useState<SortBy>('score')

  const toggleVerdict = useCallback((v: Verdict) => {
    setActiveVerdicts((prev) => {
      const next = new Set(prev)
      if (next.has(v)) next.delete(v)
      else next.add(v)
      return next
    })
  }, [])

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

  const hasNewJobs = newJobIds.size > 0 || jobs.some((j) => j.is_new_this_run)

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return jobsWithSalary.filter((job) => {
      if (!job.match_verdict) return false
      if (recommended) {
        if (job.match_verdict === 'WEAK') return false
      } else {
        if (!activeVerdicts.has(job.match_verdict)) return false
      }
      if (newOnly && !job.is_new_this_run && !newJobIds.has(job.job_id)) return false
      if (!matchesPay(job._salaryNum, payRange)) return false
      if (q) {
        const hay = `${job.title} ${job.company} ${job.location}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [jobsWithSalary, recommended, activeVerdicts, newOnly, newJobIds, payRange, search])

  const sorted = useMemo(() => {
    const arr = [...filtered]
    if (sortBy === 'score') {
      arr.sort((a, b) => (b.match_score ?? 0) - (a.match_score ?? 0))
    } else if (sortBy === 'date') {
      arr.sort((a, b) => (b.date_posted ?? '').localeCompare(a.date_posted ?? ''))
    } else if (sortBy === 'salary') {
      arr.sort((a, b) => b._salaryNum - a._salaryNum)
    }
    return arr
  }, [filtered, sortBy])

  return (
    <div>
      <div className="mb-5">
        <JobFilters
          onSearch={setSearch}
          onVerdictToggle={toggleVerdict}
          onLeaveRecommended={(v) => { setRecommended(false); setActiveVerdicts(new Set([v])) }}
          onRecommendedToggle={() => setRecommended((r) => !r)}
          onNewOnly={setNewOnly}
          onPayRange={setPayRange}
          onSort={setSortBy}
          recommended={recommended}
          activeVerdicts={activeVerdicts}
          newOnly={newOnly}
          searchValue={search}
          payRange={payRange}
          sortBy={sortBy}
          counts={counts}
          payCounts={payCounts}
          hasNewJobs={hasNewJobs}
          totalFiltered={sorted.length}
          totalAll={jobs.length}
        />
      </div>

      {sorted.length === 0 ? (
        <div className="py-16 text-center text-sm text-zinc-600">
          {search || newOnly || payRange !== 'all' ? 'No matches for current filters.' : 'No evaluated jobs in this run.'}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sorted.map((job) => (
            <JobCard key={job.job_id} job={job} isNew={job.is_new_this_run || newJobIds.has(job.job_id)} />
          ))}
        </div>
      )}
    </div>
  )
}
