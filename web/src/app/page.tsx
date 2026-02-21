import { createClient, createServiceClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { Verdict } from '@/lib/types'
import { normalizeLocation } from '@/lib/utils'
import Link from 'next/link'

export default async function DashboardPage() {
  const supabase = await createClient()
  const svc = createServiceClient()

  const { data: { user } } = await supabase.auth.getUser()

  // ── Parallel data fetches ───────────────────────────────────────────────
  const [
    profileResult,
    resumeResult,
    evalDataResult,
    topMatchesResult,
    freelanceDataResult,
    latestScrapeResult,
    unevaluatedResult,
  ] = await Promise.all([
    user
      ? svc.from('user_profiles')
          .select('full_name, eval_status, eval_completed_at')
          .eq('user_id', user.id)
          .maybeSingle()
      : Promise.resolve({ data: null }),
    user
      ? svc.from('resumes')
          .select('id')
          .eq('user_id', user.id)
          .eq('is_primary', true)
          .maybeSingle()
      : Promise.resolve({ data: null }),
    supabase
      .from('user_evaluations')
      .select('match_verdict')
      .not('match_verdict', 'is', null),
    supabase
      .from('user_evaluations')
      .select('match_score, match_verdict, job_summary, jobs(job_id, title, company, location)')
      .eq('match_verdict', 'STRONG')
      .order('match_score', { ascending: false })
      .limit(3),
    supabase
      .from('freelance_companies')
      .select('fit_tier')
      .is('archived_at', null)
      .in('fit_tier', ['HOT', 'WARM', 'COLD']),
    supabase
      .from('scrape_runs')
      .select('run_date, new_jobs')
      .order('run_date', { ascending: false })
      .limit(1)
      .maybeSingle(),
    user
      ? svc.rpc('count_unevaluated_jobs', { p_user_id: user.id })
      : Promise.resolve({ data: null }),
  ])

  // ── Process results ─────────────────────────────────────────────────────
  const profile = profileResult.data
  const hasResume = !!resumeResult.data
  const firstName = profile?.full_name?.split(' ')[0]
    ?? user?.email?.split('@')[0]
    ?? 'there'

  // Verdict counts
  const verdicts: Record<Verdict, number> = { STRONG: 0, MODERATE: 0, STRETCH: 0, WEAK: 0 }
  for (const row of (evalDataResult.data ?? [])) {
    if (row.match_verdict && row.match_verdict in verdicts) {
      verdicts[row.match_verdict as Verdict]++
    }
  }
  const totalEvals = Object.values(verdicts).reduce((a, b) => a + b, 0)

  // Top matches
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const topMatches = (topMatchesResult.data ?? []).map((row: any) => ({
    job_id: row.jobs?.job_id as string | undefined,
    title: row.jobs?.title as string | undefined,
    company: row.jobs?.company as string | undefined,
    location: row.jobs?.location ? normalizeLocation(row.jobs.location) : null,
    score: row.match_score as number | null,
    summary: row.job_summary as string | null,
  })).filter(m => m.job_id)

  // Freelance tier counts
  const tiers = { HOT: 0, WARM: 0, COLD: 0 }
  for (const row of (freelanceDataResult.data ?? [])) {
    if (row.fit_tier && row.fit_tier in tiers) {
      tiers[row.fit_tier as keyof typeof tiers]++
    }
  }
  const totalFreelance = Object.values(tiers).reduce((a, b) => a + b, 0)

  // Latest scrape
  const latestScrape = latestScrapeResult.data
  const latestScrapeLabel = latestScrape?.run_date
    ? new Date(latestScrape.run_date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : null

  // Unevaluated count
  const unevaluated = (unevaluatedResult?.data as { count: number } | null)?.count ?? 0

  // Last evaluation date
  const lastEvalLabel = profile?.eval_completed_at
    ? new Date(profile.eval_completed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : null

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:py-14">

        {/* ── Hero ───────────────────────────────────────────────────────── */}
        <div className="mb-10 sm:mb-14">
          <p className="mb-3 font-mono text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-600">
            Dashboard
          </p>
          <h1
            className="text-2xl font-extrabold tracking-tight text-white sm:text-3xl"
            style={{ fontFamily: 'Syne, sans-serif' }}
          >
            Welcome back, {firstName}.
          </h1>
          {latestScrapeLabel && (
            <p className="mt-2 text-sm text-zinc-600">
              Last scan {latestScrapeLabel}
              {latestScrape?.new_jobs != null && latestScrape.new_jobs > 0 && (
                <span className="text-zinc-700"> &middot; {latestScrape.new_jobs} new listings</span>
              )}
            </p>
          )}
        </div>

        {/* ── Setup prompt (no resume) ───────────────────────────────────── */}
        {!hasResume && (
          <div className="mb-10 rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30 p-8 sm:p-12">
            <div className="max-w-lg">
              <h2
                className="mb-2 text-lg font-bold text-white"
                style={{ fontFamily: 'Syne, sans-serif' }}
              >
                Get started
              </h2>
              <p className="mb-6 text-sm leading-relaxed text-zinc-500">
                Upload your resume and we&apos;ll evaluate job listings against your experience.
                AI-powered match scoring across 5+ sources, updated automatically.
              </p>
              <Link
                href="/profile"
                className="inline-flex items-center gap-2 rounded-lg border border-emerald-800/40 bg-emerald-950/20 px-5 py-2.5 text-sm font-medium text-emerald-400 transition-all hover:border-emerald-700/40 hover:bg-emerald-950/40"
              >
                Upload Resume
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                </svg>
              </Link>
            </div>
          </div>
        )}

        {/* ── Channel Cards ──────────────────────────────────────────────── */}
        <div className="grid gap-4 sm:grid-cols-3 sm:gap-5">

          {/* Full Time */}
          <Link
            href="/opportunities/fulltime"
            className="group relative overflow-hidden rounded-xl border border-border bg-[#111] p-6 transition-all hover:border-[#2a2a2a] hover:bg-surface-2"
          >
            <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-emerald-500/80 to-emerald-500/0" />

            <div className="mb-5 flex items-center justify-between">
              <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.15em] text-zinc-500">
                Full Time
              </span>
              <svg className="h-4 w-4 text-zinc-700 transition-transform group-hover:translate-x-0.5 group-hover:text-zinc-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
            </div>

            {totalEvals > 0 ? (
              <>
                <div className="mb-4">
                  <span
                    className="text-4xl font-extrabold tabular-nums text-white"
                    style={{ fontFamily: 'Syne, sans-serif' }}
                  >
                    {verdicts.STRONG}
                  </span>
                  <span className="ml-2 text-sm text-emerald-500/80">strong</span>
                </div>
                <div className="space-y-1.5">
                  <MetricRow label="Moderate" count={verdicts.MODERATE} color="text-amber-500/70" />
                  <MetricRow label="Stretch" count={verdicts.STRETCH} color="text-orange-500/60" />
                  <MetricRow label="Weak" count={verdicts.WEAK} color="text-zinc-600" />
                </div>
                {/* Verdict distribution bar */}
                <div className="mt-4 flex h-1 w-full overflow-hidden rounded-full bg-zinc-900">
                  <div className="bg-emerald-500/80 transition-all" style={{ width: `${(verdicts.STRONG / totalEvals) * 100}%` }} />
                  <div className="bg-amber-500/80 transition-all" style={{ width: `${(verdicts.MODERATE / totalEvals) * 100}%` }} />
                  <div className="bg-orange-500/70 transition-all" style={{ width: `${(verdicts.STRETCH / totalEvals) * 100}%` }} />
                  <div className="bg-red-500/50 transition-all" style={{ width: `${(verdicts.WEAK / totalEvals) * 100}%` }} />
                </div>
                {unevaluated > 0 && (
                  <div className="mt-4 rounded-md border border-emerald-900/30 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-400/80">
                    {unevaluated} new job{unevaluated !== 1 ? 's' : ''} to evaluate
                  </div>
                )}
                {lastEvalLabel && (
                  <p className="mt-4 border-t border-zinc-800/50 pt-3 text-[11px] text-zinc-700">
                    Evaluated {lastEvalLabel}
                  </p>
                )}
              </>
            ) : hasResume ? (
              <div className="py-4">
                <p className="mb-1 text-sm text-zinc-500">No evaluations yet</p>
                <p className="text-xs text-zinc-700">
                  Trigger an evaluation to score jobs against your resume.
                </p>
              </div>
            ) : (
              <div className="py-4">
                <p className="mb-1 text-sm text-zinc-500">Upload a resume to start</p>
                <p className="text-xs text-zinc-700">
                  AI-scored matches from 5+ job sources.
                </p>
              </div>
            )}
          </Link>

          {/* Freelance */}
          <Link
            href="/opportunities/freelance"
            className="group relative overflow-hidden rounded-xl border border-border bg-[#111] p-6 transition-all hover:border-[#2a2a2a] hover:bg-surface-2"
          >
            <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-amber-500/80 to-amber-500/0" />

            <div className="mb-5 flex items-center justify-between">
              <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.15em] text-zinc-500">
                Freelance
              </span>
              <svg className="h-4 w-4 text-zinc-700 transition-transform group-hover:translate-x-0.5 group-hover:text-zinc-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
            </div>

            {totalFreelance > 0 ? (
              <>
                <div className="mb-4">
                  <span
                    className="text-4xl font-extrabold tabular-nums text-white"
                    style={{ fontFamily: 'Syne, sans-serif' }}
                  >
                    {tiers.HOT}
                  </span>
                  <span className="ml-2 text-sm text-amber-500/80">hot leads</span>
                </div>
                <div className="space-y-1.5">
                  <MetricRow label="Warm" count={tiers.WARM} color="text-amber-600/60" />
                  <MetricRow label="Cold" count={tiers.COLD} color="text-zinc-600" />
                </div>
                {/* Tier distribution bar */}
                <div className="mt-4 flex h-1 w-full overflow-hidden rounded-full bg-zinc-900">
                  <div className="bg-emerald-500/80 transition-all" style={{ width: `${(tiers.HOT / totalFreelance) * 100}%` }} />
                  <div className="bg-amber-500/80 transition-all" style={{ width: `${(tiers.WARM / totalFreelance) * 100}%` }} />
                  <div className="bg-zinc-600 transition-all" style={{ width: `${(tiers.COLD / totalFreelance) * 100}%` }} />
                </div>
              </>
            ) : (
              <div className="py-4">
                <p className="mb-1 text-sm text-zinc-500">No prospects yet</p>
                <p className="text-xs text-zinc-700">
                  Companies discovered for cold outreach.
                </p>
              </div>
            )}
          </Link>

          {/* Social (coming soon) */}
          <div className="group relative overflow-hidden rounded-xl border border-dashed border-zinc-800 bg-[#0d0d0d] p-6">
            <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-blue-500/30 to-blue-500/0" />

            <div className="mb-5 flex items-center justify-between">
              <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.15em] text-zinc-600">
                Social
              </span>
              <span className="rounded-full border border-zinc-800 bg-zinc-900 px-2 py-0.5 font-mono text-[9px] text-zinc-600">
                Soon
              </span>
            </div>

            <div className="py-4">
              <p className="mb-1 text-sm text-zinc-600">Group monitoring</p>
              <p className="text-xs text-zinc-800">
                Automated gig alerts from AV community groups on Facebook.
              </p>
            </div>
          </div>
        </div>

        {/* ── Top Matches ────────────────────────────────────────────────── */}
        {topMatches.length > 0 && (
          <div className="mt-10 sm:mt-14">
            <div className="mb-5 flex items-center justify-between">
              <h2 className="font-mono text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-600">
                Top Matches
              </h2>
              <Link
                href="/opportunities/fulltime"
                className="text-xs text-zinc-600 transition-colors hover:text-zinc-400"
              >
                View all &rarr;
              </Link>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              {topMatches.map((match, i) => (
                <Link
                  key={match.job_id}
                  href={`/opportunities/fulltime/${match.job_id}`}
                  className="group rounded-xl border border-border bg-[#111] p-5 transition-all hover:border-[#2a2a2a] hover:bg-surface-2"
                >
                  <div className="mb-3 flex items-center gap-2">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-950/60 font-mono text-[9px] font-bold text-emerald-500/60">
                      {i + 1}
                    </span>
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-800 bg-emerald-950/60 px-2 py-0.5 font-mono text-[10px] font-semibold text-emerald-400">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                      {match.score}
                    </span>
                    {match.location && (
                      <span className="text-[11px] text-zinc-600">{match.location}</span>
                    )}
                  </div>
                  <h3 className="mb-1 truncate text-sm font-semibold text-white group-hover:text-zinc-100">
                    {match.title}
                  </h3>
                  <p className="mb-2 text-xs text-zinc-500">{match.company}</p>
                  {match.summary && (
                    <p className="line-clamp-2 text-xs leading-relaxed text-zinc-600">
                      {match.summary}
                    </p>
                  )}
                </Link>
              ))}
            </div>
          </div>
        )}

      </main>
    </div>
  )
}

function MetricRow({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-zinc-600">{label}</span>
      <span className={`font-mono text-xs font-medium tabular-nums ${color}`}>{count}</span>
    </div>
  )
}
