import { createClient } from '@/lib/supabase/server'
import { normalizeLocation } from '@/lib/utils'
import { TopMatchesCarousel, MatchItem } from './TopMatchesCarousel'
import Link from 'next/link'

export async function DashboardTopMatches() {
  const supabase = await createClient()

  const { data } = await supabase
    .from('user_evaluations')
    .select('match_score, match_verdict, job_summary, jobs(job_id, title, company, location)')
    .in('match_verdict', ['STRONG', 'MODERATE'])
    .order('match_score', { ascending: false })
    .limit(12)

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const topMatches: MatchItem[] = (data ?? []).map((row: any) => ({
    job_id: row.jobs?.job_id as string,
    title: (row.jobs?.title as string) ?? '',
    company: (row.jobs?.company as string) ?? '',
    location: row.jobs?.location ? normalizeLocation(row.jobs.location) : null,
    score: row.match_score as number | null,
    verdict: (row.match_verdict as string) ?? 'MODERATE',
    summary: row.job_summary as string | null,
  })).filter(m => m.job_id)

  if (topMatches.length === 0) return null

  return (
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
      <TopMatchesCarousel matches={topMatches} />
    </div>
  )
}
