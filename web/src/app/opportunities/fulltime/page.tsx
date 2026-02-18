import { createClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { JobGrid } from '@/components/jobs/JobGrid'
import { RunSelector } from '@/components/jobs/RunSelector'
import { JobWithRunMeta } from '@/lib/types'

interface Props {
  searchParams: Promise<{ run?: string }>
}

export default async function FullTimePage({ searchParams }: Props) {
  const { run } = await searchParams
  const supabase = await createClient()

  // Always fetch available runs for the dropdown
  const { data: runs } = await supabase
    .from('runs')
    .select('run_date, total_jobs')
    .order('run_date', { ascending: false })

  let jobs: JobWithRunMeta[] = []
  let newJobIds: Set<string> = new Set()

  if (run) {
    // Load jobs for the selected run via junction table
    const { data: runRecord } = await supabase
      .from('runs')
      .select('*')
      .eq('run_date', run)
      .single()

    if (runRecord) {
      const { data: runJobs } = await supabase
        .from('run_jobs')
        .select('is_new_this_run, jobs(*)')
        .eq('run_id', runRecord.id)
        .order('jobs(match_score)', { ascending: false })

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      jobs = (runJobs ?? [] as any[])
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .filter((rj: any) => rj.jobs !== null)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .map((rj: any) => ({
          ...rj.jobs,
          is_new_this_run: rj.is_new_this_run,
        }))
        .sort((a: JobWithRunMeta, b: JobWithRunMeta) => (b.match_score ?? 0) - (a.match_score ?? 0))

      newJobIds = new Set<string>((runRecord.new_job_ids ?? []) as string[])
    }
  } else {
    // Load all evaluated jobs
    const { data } = await supabase
      .from('jobs')
      .select('*')
      .not('match_verdict', 'is', null)
      .order('match_score', { ascending: false })
      .order('first_seen_date', { ascending: false })

    jobs = (data ?? []) as JobWithRunMeta[]
  }

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-7xl px-4 py-8">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <h1
            className="text-xl font-bold text-white"
            style={{ fontFamily: 'Syne, sans-serif' }}
          >
            Full Time
          </h1>
          <RunSelector runs={runs ?? []} currentRun={run ?? null} />
        </div>

        <JobGrid jobs={jobs} newJobIds={newJobIds} />
      </main>
    </div>
  )
}
