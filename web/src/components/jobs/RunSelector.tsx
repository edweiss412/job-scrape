'use client'

import { useRouter, usePathname } from 'next/navigation'
import { formatRunDate } from '@/lib/utils'

interface Run {
  run_date: string
  total_jobs: number
}

interface RunSelectorProps {
  runs: Run[]
  currentRun: string | null
}

export function RunSelector({ runs, currentRun }: RunSelectorProps) {
  const router = useRouter()
  const pathname = usePathname()

  return (
    <select
      value={currentRun ?? ''}
      onChange={(e) => {
        const val = e.target.value
        router.push(val ? `${pathname}?run=${val}` : pathname)
      }}
      className="rounded-lg border border-border bg-[#111] px-2.5 py-1.5 text-[11px] font-mono text-zinc-400 focus:outline-none focus:border-zinc-600"
    >
      <option value="">All runs</option>
      {runs.map((r) => (
        <option key={r.run_date} value={r.run_date}>
          {formatRunDate(r.run_date)} ({r.total_jobs})
        </option>
      ))}
    </select>
  )
}
