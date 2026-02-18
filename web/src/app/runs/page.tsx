import { createClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { Run } from '@/lib/types'
import Link from 'next/link'
import { formatRunDate, daysAgo } from '@/lib/utils'
import { NewBadge } from '@/components/ui/badge'

function RunCard({ run }: { run: Run }) {
  const total = run.strong_count + run.moderate_count + run.stretch_count + run.weak_count
  const hasNew = run.new_job_ids?.length > 0

  return (
    <Link
      href={`/runs/${run.run_date}`}
      className="group block rounded-xl border border-[#1f1f1f] bg-[#111] p-6 transition-all hover:border-[#2a2a2a] hover:bg-[#161616]"
    >
      {/* Header */}
      <div className="mb-4 flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h2
              className="text-sm font-semibold text-white"
              style={{ fontFamily: 'Syne, sans-serif' }}
            >
              {formatRunDate(run.run_date)}
            </h2>
            {hasNew && <NewBadge />}
          </div>
          <p className="mt-0.5 font-mono text-[11px] text-zinc-600">{daysAgo(run.run_date)}</p>
        </div>
        <span className="text-xs text-zinc-600">{total} evaluated</span>
      </div>

      {/* Verdict bars */}
      <div className="mb-4 flex h-1.5 overflow-hidden rounded-full gap-0.5">
        {run.strong_count > 0 && (
          <div
            className="bg-emerald-500 rounded-full"
            style={{ width: `${(run.strong_count / total) * 100}%` }}
          />
        )}
        {run.moderate_count > 0 && (
          <div
            className="bg-amber-500 rounded-full"
            style={{ width: `${(run.moderate_count / total) * 100}%` }}
          />
        )}
        {run.stretch_count > 0 && (
          <div
            className="bg-orange-500 rounded-full"
            style={{ width: `${(run.stretch_count / total) * 100}%` }}
          />
        )}
        {run.weak_count > 0 && (
          <div
            className="bg-red-700 rounded-full"
            style={{ width: `${(run.weak_count / total) * 100}%` }}
          />
        )}
      </div>

      {/* Counts */}
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {run.strong_count > 0 && (
          <span className="text-xs font-mono text-emerald-500">{run.strong_count} Strong</span>
        )}
        {run.moderate_count > 0 && (
          <span className="text-xs font-mono text-amber-500">{run.moderate_count} Moderate</span>
        )}
        {run.stretch_count > 0 && (
          <span className="text-xs font-mono text-orange-500">{run.stretch_count} Stretch</span>
        )}
        {run.weak_count > 0 && (
          <span className="text-xs font-mono text-zinc-600">{run.weak_count} Weak</span>
        )}
        {hasNew && (
          <span className="ml-auto text-xs font-mono text-blue-500">
            {run.new_job_ids.length} new
          </span>
        )}
      </div>
    </Link>
  )
}

export default async function RunsPage() {
  const supabase = await createClient()
  const { data: runs, error } = await supabase
    .from('runs')
    .select('*')
    .order('run_date', { ascending: false })

  if (error) {
    return (
      <div className="flex min-h-screen flex-col">
        <Nav />
        <main className="flex flex-1 items-center justify-center">
          <p className="text-sm text-red-400">Failed to load runs: {error.message}</p>
        </main>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-4xl px-4 py-8">
        <div className="mb-8">
          <h1
            className="text-xl font-bold text-white"
            style={{ fontFamily: 'Syne, sans-serif' }}
          >
            Scan History
          </h1>
          <p className="mt-1 text-sm text-zinc-600">
            {runs?.length ?? 0} run{runs?.length !== 1 ? 's' : ''} · Mon &amp; Thu 8am CT
          </p>
        </div>

        {!runs?.length ? (
          <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-12 text-center">
            <p className="text-sm text-zinc-600">No scan results yet.</p>
            <p className="mt-1 text-xs text-zinc-700">
              Run <code className="font-mono text-zinc-500">python job_scraper.py</code> locally or
              trigger the GitHub Actions workflow.
            </p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {runs.map((run: Run) => (
              <RunCard key={run.id} run={run} />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
