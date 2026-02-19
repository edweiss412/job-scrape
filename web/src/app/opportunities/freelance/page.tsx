import { createClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { FreelanceGrid } from '@/components/freelance/FreelanceGrid'
import { RunSelector } from '@/components/jobs/RunSelector'
import { TriggerScanButton } from '@/components/admin/TriggerScanButton'
import { FreelanceCompany } from '@/lib/types'
import { isJunkFreelanceCompany } from '@/lib/utils'

interface Props {
  searchParams: Promise<{ run?: string }>
}

export default async function FreelancePage({ searchParams }: Props) {
  const { run } = await searchParams
  const supabase = await createClient()

  // Fetch companies: all or filtered by run date
  let query = supabase
    .from('freelance_companies')
    .select('*')
    .in('fit_tier', ['HOT', 'WARM', 'COLD'])
    .order('fit_score', { ascending: false })

  if (run) {
    query = query.eq('first_seen_date', run)
  }

  const [companiesResult, runsResult] = await Promise.all([
    query,
    // Distinct run dates with counts
    supabase
      .from('freelance_companies')
      .select('first_seen_date, name, fit_tier')
      .in('fit_tier', ['HOT', 'WARM', 'COLD']),
  ])

  const companies = (companiesResult.data ?? [])
    .filter((c: FreelanceCompany) => !isJunkFreelanceCompany(c.name))

  // Build run list from all companies (not filtered by current run)
  const runMap: Record<string, number> = {}
  for (const c of (runsResult.data ?? [])) {
    if (!isJunkFreelanceCompany(c.name)) {
      runMap[c.first_seen_date] = (runMap[c.first_seen_date] ?? 0) + 1
    }
  }
  const runs = Object.entries(runMap)
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([run_date, total_jobs]) => ({ run_date, total_jobs }))

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
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

        {companies.length === 0 ? (
          <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-12 text-center">
            <p className="text-sm text-zinc-600">
              {run ? 'No companies found for this scan date.' : 'No freelance prospect data yet.'}
            </p>
            {!run && (
              <p className="mt-1 text-xs text-zinc-700">
                Run <code className="font-mono text-zinc-500">python freelance_finder.py</code>
              </p>
            )}
          </div>
        ) : (
          <FreelanceGrid companies={companies} />
        )}
      </main>
    </div>
  )
}
