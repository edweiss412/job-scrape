import { createClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { FreelanceGrid } from '@/components/freelance/FreelanceGrid'
import { RunSelector } from '@/components/jobs/RunSelector'
import { TriggerScanButton } from '@/components/admin/TriggerScanButton'
import { FreelanceCompany, FreelanceCompanyWithEval, UserFreelanceEvaluation } from '@/lib/types'
import { isJunkFreelanceCompany } from '@/lib/utils'

interface Props {
  searchParams: Promise<{ run?: string }>
}

export default async function FreelancePage({ searchParams }: Props) {
  const { run } = await searchParams
  const supabase = await createClient()

  // Get current user for per-user evaluations
  const { data: { user } } = await supabase.auth.getUser()

  // Fetch companies with per-user evaluations joined
  let query = supabase
    .from('freelance_companies')
    .select('*')
    .order('fit_score', { ascending: false })

  if (run) {
    query = query.eq('first_seen_date', run)
  }

  // Fetch user evaluations if logged in
  const userEvalsPromise = user
    ? supabase
        .from('user_freelance_evaluations')
        .select('*')
        .eq('user_id', user.id)
    : Promise.resolve({ data: [] })

  const [companiesResult, userEvalsResult, runsResult] = await Promise.all([
    query,
    userEvalsPromise,
    // Distinct run dates with counts
    supabase
      .from('freelance_companies')
      .select('first_seen_date, name, fit_tier')
      .in('fit_tier', ['HOT', 'WARM', 'COLD'])
      .gt('fit_score', 0),
  ])

  // Build a map of user evaluations by company_id
  const userEvalMap = new Map<string, UserFreelanceEvaluation>()
  for (const ev of (userEvalsResult.data ?? []) as UserFreelanceEvaluation[]) {
    userEvalMap.set(ev.company_id, ev)
  }

  // Merge: prefer user eval data if available, fall back to legacy fields on freelance_companies
  const rawCompanies = (companiesResult.data ?? []) as FreelanceCompany[]
  const companies: FreelanceCompanyWithEval[] = rawCompanies
    .filter((c) => !isJunkFreelanceCompany(c.name))
    .map((c): FreelanceCompanyWithEval => {
      const userEval = userEvalMap.get(c.company_id) ?? null
      if (userEval) {
        return {
          ...c,
          fit_tier: userEval.fit_tier ?? c.fit_tier,
          fit_score: userEval.fit_score ?? c.fit_score,
          fit_reasoning: userEval.fit_reasoning ?? c.fit_reasoning,
          full_evaluation: userEval.full_evaluation ?? c.full_evaluation,
          outreach_draft: userEval.outreach_draft ?? c.outreach_draft,
          outreach_subject: userEval.outreach_subject ?? c.outreach_subject,
          relationship: userEval.relationship ?? c.relationship,
          relationship_notes: userEval.relationship_notes ?? c.relationship_notes,
          user_eval: userEval,
        }
      }
      return { ...c, user_eval: null }
    })
    .filter((c) => c.fit_tier && ['HOT', 'WARM', 'COLD'].includes(c.fit_tier!) && (c.fit_score ?? 0) > 0)
    .sort((a, b) => (b.fit_score ?? 0) - (a.fit_score ?? 0))

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
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-zinc-800 bg-zinc-900/20 py-20 text-center">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-zinc-800 bg-zinc-900">
              <svg className="h-5 w-5 text-zinc-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
              </svg>
            </div>
            {run ? (
              <>
                <h2 className="mb-1 text-sm font-semibold text-white">No companies found for this scan</h2>
                <p className="max-w-xs text-xs text-zinc-600">
                  This scan date has no freelance prospect results. Try selecting a different run or viewing all runs.
                </p>
              </>
            ) : (
              <>
                <h2 className="mb-1 text-sm font-semibold text-white">No freelance prospects yet</h2>
                <p className="mb-6 max-w-sm text-xs text-zinc-600">
                  Run a freelance scan to discover AV companies for cold outreach.
                </p>
                <TriggerScanButton type="freelance" />
                <p className="mt-4 text-xs text-zinc-700">
                  Or trigger a scan from the admin dashboard.
                </p>
              </>
            )}
          </div>
        ) : (
          <FreelanceGrid companies={companies} />
        )}
      </main>
    </div>
  )
}
