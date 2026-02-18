import { createClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { JobCard } from '@/components/jobs/JobCard'
import { Job } from '@/lib/types'
import Link from 'next/link'

const PAGE_SIZE = 50

interface Props {
  searchParams: Promise<{ q?: string; verdict?: string; page?: string }>
}

export default async function AllJobsPage({ searchParams }: Props) {
  const { q, verdict, page } = await searchParams
  const pageNum = Math.max(1, parseInt(page ?? '1', 10))
  const offset = (pageNum - 1) * PAGE_SIZE

  const supabase = await createClient()

  let query = supabase
    .from('jobs')
    .select('*', { count: 'exact' })
    .not('match_verdict', 'is', null)
    .order('match_score', { ascending: false })
    .order('first_seen_date', { ascending: false })
    .range(offset, offset + PAGE_SIZE - 1)

  if (verdict && ['STRONG', 'MODERATE', 'STRETCH', 'WEAK'].includes(verdict)) {
    query = query.eq('match_verdict', verdict)
  }

  if (q && q.trim()) {
    query = query.textSearch('fts', q.trim().split(/\s+/).join(' | '), {
      type: 'websearch',
      config: 'english',
    })
  }

  const { data: jobs, count, error } = await query

  const totalPages = Math.ceil((count ?? 0) / PAGE_SIZE)
  const VERDICTS = ['STRONG', 'MODERATE', 'STRETCH', 'WEAK']

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-7xl px-4 py-8">
        {/* Header */}
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1
              className="text-xl font-bold text-white"
              style={{ fontFamily: 'Syne, sans-serif' }}
            >
              All Jobs
            </h1>
            <p className="mt-0.5 text-sm text-zinc-600">
              {count ?? 0} total evaluated
            </p>
          </div>

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2">
            <form method="GET" className="flex items-center gap-2">
              <input
                name="q"
                defaultValue={q ?? ''}
                placeholder="Search…"
                className="rounded-lg border border-[#1f1f1f] bg-[#111] px-3 py-1.5 text-xs text-zinc-300 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none w-40"
              />
              <input name="verdict" type="hidden" value={verdict ?? ''} />
              <button type="submit" className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">Go</button>
            </form>

            <div className="flex items-center gap-1">
              {VERDICTS.map((v) => (
                <Link
                  key={v}
                  href={`/jobs?${verdict === v ? '' : `verdict=${v}`}${q ? `&q=${q}` : ''}`}
                  className={`rounded-full border px-2 py-0.5 font-mono text-[10px] font-semibold uppercase transition-all ${
                    verdict === v
                      ? v === 'STRONG' ? 'border-emerald-800 bg-emerald-950/60 text-emerald-400'
                        : v === 'MODERATE' ? 'border-amber-800 bg-amber-950/60 text-amber-400'
                        : v === 'STRETCH' ? 'border-orange-800 bg-orange-950/60 text-orange-400'
                        : 'border-red-900 bg-red-950/60 text-red-500'
                      : 'border-[#1f1f1f] text-zinc-600 hover:border-[#333] hover:text-zinc-400'
                  }`}
                >
                  {v}
                </Link>
              ))}
            </div>
          </div>
        </div>

        {error ? (
          <p className="text-sm text-red-400">Error: {error.message}</p>
        ) : !jobs?.length ? (
          <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-12 text-center text-sm text-zinc-600">
            No jobs match your search.
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {jobs.map((job: Job) => (
                <JobCard key={job.job_id} job={job} />
              ))}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="mt-6 flex items-center justify-center gap-2">
                {pageNum > 1 && (
                  <Link
                    href={`/jobs?page=${pageNum - 1}${verdict ? `&verdict=${verdict}` : ''}${q ? `&q=${q}` : ''}`}
                    className="rounded-lg border border-[#1f1f1f] bg-[#111] px-3 py-1.5 text-xs text-zinc-400 hover:bg-[#1f1f1f] transition-colors"
                  >
                    ← Prev
                  </Link>
                )}
                <span className="font-mono text-xs text-zinc-600">
                  {pageNum} / {totalPages}
                </span>
                {pageNum < totalPages && (
                  <Link
                    href={`/jobs?page=${pageNum + 1}${verdict ? `&verdict=${verdict}` : ''}${q ? `&q=${q}` : ''}`}
                    className="rounded-lg border border-[#1f1f1f] bg-[#111] px-3 py-1.5 text-xs text-zinc-400 hover:bg-[#1f1f1f] transition-colors"
                  >
                    Next →
                  </Link>
                )}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
