import { createClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { JobGrid } from '@/components/jobs/JobGrid'
import { JobWithRunMeta } from '@/lib/types'

export default async function AllJobsPage() {
  const supabase = await createClient()

  const { data: jobs, error } = await supabase
    .from('jobs')
    .select('*')
    .not('match_verdict', 'is', null)
    .order('match_score', { ascending: false })
    .order('first_seen_date', { ascending: false })

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-7xl px-4 py-8">
        <div className="mb-6">
          <h1
            className="text-xl font-bold text-white"
            style={{ fontFamily: 'Syne, sans-serif' }}
          >
            All Jobs
          </h1>
        </div>

        {error ? (
          <p className="text-sm text-red-400">Error: {error.message}</p>
        ) : (
          <JobGrid jobs={(jobs ?? []) as JobWithRunMeta[]} />
        )}
      </main>
    </div>
  )
}
