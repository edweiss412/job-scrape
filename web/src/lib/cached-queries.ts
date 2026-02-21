import { unstable_cache } from 'next/cache'
import { createServiceClient } from '@/lib/supabase/server'

/**
 * Latest scrape run metadata — only changes on Mon/Thu scans.
 * Uses service client (not cookie-based) since unstable_cache cannot
 * access request cookies on cache hit. These are public catalog queries.
 * Revalidated every hour or on-demand via revalidateTag('scrape-runs').
 */
export const getLatestScrapeRun = unstable_cache(
  async () => {
    const svc = createServiceClient()
    const { data } = await svc
      .from('scrape_runs')
      .select('run_date, new_jobs')
      .order('run_date', { ascending: false })
      .limit(1)
      .maybeSingle()
    return data
  },
  ['latest-scrape-run'],
  { revalidate: 3600, tags: ['scrape-runs'] }
)

/**
 * Evaluation runs list — only changes after evaluation runs.
 * Revalidated every hour or on-demand via revalidateTag('runs-list').
 */
export const getRunsList = unstable_cache(
  async () => {
    const svc = createServiceClient()
    const { data } = await svc
      .from('runs')
      .select('run_date, total_jobs')
      .order('run_date', { ascending: false })
    return data ?? []
  },
  ['runs-list'],
  { revalidate: 3600, tags: ['runs-list'] }
)
