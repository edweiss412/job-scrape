import { createServiceClient } from '@/lib/supabase/server'
import { getLatestScrapeRun } from '@/lib/cached-queries'

export async function DashboardHero({ userId, userEmail }: { userId: string | null; userEmail: string | null }) {
  const svc = createServiceClient()

  const [profileResult, latestScrape] = await Promise.all([
    userId
      ? svc.from('user_profiles')
          .select('full_name')
          .eq('user_id', userId)
          .maybeSingle()
      : Promise.resolve({ data: null }),
    getLatestScrapeRun(),
  ])

  const firstName = profileResult.data?.full_name?.split(' ')[0]
    ?? userEmail?.split('@')[0]
    ?? 'there'

  const latestScrapeLabel = latestScrape?.run_date
    ? new Date(latestScrape.run_date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : null

  return (
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
  )
}
