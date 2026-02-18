import { createClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { JobGrid } from '@/components/jobs/JobGrid'
import { JobWithRunMeta } from '@/lib/types'
import { formatRunDate } from '@/lib/utils'
import Link from 'next/link'
import { notFound } from 'next/navigation'

interface Props {
  params: Promise<{ runDate: string }>
}

export default async function RunDetailPage({ params }: Props) {
  const { runDate } = await params
  const supabase = await createClient()

  // Load the run record
  const { data: run } = await supabase
    .from('runs')
    .select('*')
    .eq('run_date', runDate)
    .single()

  if (!run) notFound()

  // Load jobs for this run via run_jobs junction
  const { data: runJobs, error } = await supabase
    .from('run_jobs')
    .select(`
      is_new_this_run,
      jobs (*)
    `)
    .eq('run_id', run.id)
    .order('jobs(match_score)', { ascending: false })

  if (error) {
    return (
      <div className="flex min-h-screen flex-col">
        <Nav />
        <main className="flex flex-1 items-center justify-center">
          <p className="text-sm text-red-400">Error: {error.message}</p>
        </main>
      </div>
    )
  }

  // Flatten: attach is_new_this_run to each job
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const jobs: JobWithRunMeta[] = (runJobs ?? [] as any[])
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .filter((rj: any) => rj.jobs !== null)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .map((rj: any) => ({
      ...rj.jobs,
      is_new_this_run: rj.is_new_this_run,
    }))
    .sort((a: JobWithRunMeta, b: JobWithRunMeta) => (b.match_score ?? 0) - (a.match_score ?? 0))

  const newJobIds = new Set<string>((run.new_job_ids ?? []) as string[])

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-7xl px-4 py-8">
        {/* Header */}
        <div className="mb-6 flex items-center gap-3">
          <Link
            href="/runs"
            className="text-zinc-600 hover:text-zinc-400 transition-colors"
            aria-label="Back to runs"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </Link>

          <div>
            <h1
              className="text-lg font-bold text-white"
              style={{ fontFamily: 'Syne, sans-serif' }}
            >
              {formatRunDate(runDate)}
            </h1>
            <div className="mt-0.5 flex flex-wrap gap-3 font-mono text-[11px]">
              {run.strong_count > 0   && <span className="text-emerald-500">{run.strong_count} Strong</span>}
              {run.moderate_count > 0 && <span className="text-amber-500">{run.moderate_count} Moderate</span>}
              {run.stretch_count > 0  && <span className="text-orange-500">{run.stretch_count} Stretch</span>}
              {run.weak_count > 0     && <span className="text-zinc-600">{run.weak_count} Weak</span>}
              {newJobIds.size > 0     && <span className="text-blue-500">{newJobIds.size} new</span>}
            </div>
          </div>
        </div>

        <JobGrid jobs={jobs} newJobIds={newJobIds} />
      </main>
    </div>
  )
}
