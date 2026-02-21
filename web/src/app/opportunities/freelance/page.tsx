import { Suspense } from 'react'
import { createClient } from '@/lib/supabase/server'
import { RunSelector } from '@/components/jobs/RunSelector'
import { TriggerScanButton } from '@/components/admin/TriggerScanButton'
import { FreelanceJobList } from '@/components/freelance/FreelanceJobList'
import { FreelanceGridSkeleton } from '@/components/dashboard/skeletons'
import { isAdmin } from '@/lib/admin'
import { isJunkFreelanceCompany } from '@/lib/utils'

interface Props {
  searchParams: Promise<{ run?: string }>
}

export default async function FreelancePage({ searchParams }: Props) {
  const { run } = await searchParams
  const supabase = await createClient()

  const { data: { user } } = await supabase.auth.getUser()
  const userIsAdmin = isAdmin(user?.email)

  // Lightweight query for header run selector only
  const { data: runsData } = await supabase
    .from('freelance_companies')
    .select('first_seen_date, name, fit_tier')
    .is('archived_at', null)
    .in('fit_tier', ['HOT', 'WARM', 'COLD'])
    .gt('fit_score', 0)

  const runMap: Record<string, number> = {}
  for (const c of (runsData ?? [])) {
    if (!isJunkFreelanceCompany(c.name)) {
      runMap[c.first_seen_date] = (runMap[c.first_seen_date] ?? 0) + 1
    }
  }
  const runs = Object.entries(runMap)
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([run_date, total_jobs]) => ({ run_date, total_jobs }))

  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-5 sm:py-8">
      <div className="mb-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1
              className="text-xl font-bold text-white"
              style={{ fontFamily: 'Syne, sans-serif' }}
            >
              Freelance
            </h1>
            <p className="mt-1 text-sm text-zinc-600">
              AV companies discovered for cold outreach
            </p>
          </div>
          <div className="flex items-center gap-2">
            <TriggerScanButton type="freelance" />
            <RunSelector runs={runs} currentRun={run ?? null} />
          </div>
        </div>
      </div>

      <Suspense fallback={<FreelanceGridSkeleton />}>
        <FreelanceJobList run={run} userIsAdmin={userIsAdmin} userId={user?.id ?? null} />
      </Suspense>
    </main>
  )
}
