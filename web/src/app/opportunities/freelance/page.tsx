import { createClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import Link from 'next/link'
import { formatRunDate, daysAgo } from '@/lib/utils'
import { TriggerScanButton } from '@/components/admin/TriggerScanButton'

interface RunSummary {
  date: string
  hot: number
  warm: number
  cold: number
}

export default async function FreelancePage() {
  const supabase = await createClient()

  const { data: companies } = await supabase
    .from('freelance_companies')
    .select('first_seen_date, fit_tier')

  const byDate: Record<string, RunSummary> = {}
  for (const c of companies ?? []) {
    const d = c.first_seen_date
    if (!byDate[d]) byDate[d] = { date: d, hot: 0, warm: 0, cold: 0 }
    if (c.fit_tier === 'HOT') byDate[d].hot++
    else if (c.fit_tier === 'WARM') byDate[d].warm++
    else if (c.fit_tier === 'COLD') byDate[d].cold++
  }

  const runs = Object.values(byDate).sort((a, b) => b.date.localeCompare(a.date))

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-4xl px-4 py-8">
        <div className="mb-8 flex items-start justify-between gap-4">
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
          <TriggerScanButton type="freelance" />
        </div>

        {!runs.length ? (
          <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-12 text-center">
            <p className="text-sm text-zinc-600">No freelance prospect data yet.</p>
            <p className="mt-1 text-xs text-zinc-700">
              Run <code className="font-mono text-zinc-500">python freelance_finder.py</code>
            </p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {runs.map((run) => (
              <Link
                key={run.date}
                href={`/opportunities/freelance/${run.date}`}
                className="group block rounded-xl border border-[#1f1f1f] bg-[#111] p-6 transition-all hover:border-[#2a2a2a] hover:bg-[#161616]"
              >
                <div className="mb-4 flex items-start justify-between gap-2">
                  <div>
                    <h2
                      className="text-sm font-semibold text-white"
                      style={{ fontFamily: 'Syne, sans-serif' }}
                    >
                      {formatRunDate(run.date)}
                    </h2>
                    <p className="mt-0.5 font-mono text-[11px] text-zinc-600">{daysAgo(run.date)}</p>
                  </div>
                  <span className="text-xs text-zinc-600">
                    {run.hot + run.warm + run.cold} companies
                  </span>
                </div>
                <div className="flex flex-wrap gap-4">
                  {run.hot > 0 && <span className="font-mono text-xs text-emerald-500">{run.hot} HOT</span>}
                  {run.warm > 0 && <span className="font-mono text-xs text-amber-500">{run.warm} WARM</span>}
                  {run.cold > 0 && <span className="font-mono text-xs text-zinc-600">{run.cold} COLD</span>}
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
