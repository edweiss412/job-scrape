import { createClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { EvaluationRenderer } from '@/components/jobs/EvaluationRenderer'
import { VerdictBadge } from '@/components/ui/badge'
import { normalizeLocation, formatDate, VERDICT_STYLES } from '@/lib/utils'
import { Verdict } from '@/lib/types'
import Link from 'next/link'
import { notFound } from 'next/navigation'

interface Props {
  params: Promise<{ jobId: string }>
}

export default async function JobDetailPage({ params }: Props) {
  const { jobId } = await params
  const supabase = await createClient()

  const { data: job } = await supabase
    .from('jobs')
    .select('*')
    .eq('job_id', jobId)
    .single()

  if (!job) notFound()

  const verdict = job.match_verdict as Verdict | null
  const verdictStyle = verdict ? VERDICT_STYLES[verdict] : null
  const city = normalizeLocation(job.location)

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-4xl px-4 py-8">
        {/* Back link */}
        <Link
          href={`/runs/${job.first_seen_date}`}
          className="mb-6 inline-flex items-center gap-1.5 text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
        >
          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          {job.first_seen_date}
        </Link>

        {/* Job header card */}
        <div
          className={`mb-6 rounded-xl border p-6 ${
            verdictStyle ? `${verdictStyle.bg} ${verdictStyle.border}` : 'bg-[#111] border-[#1f1f1f]'
          }`}
        >
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                {verdict && <VerdictBadge verdict={verdict} score={job.match_score} />}
                {job.tier && (
                  <span className="rounded border border-[#333] px-1.5 py-0.5 font-mono text-[10px] text-zinc-500">
                    {job.tier}
                  </span>
                )}
              </div>
              <h1
                className="text-xl font-bold text-white"
                style={{ fontFamily: 'Syne, sans-serif' }}
              >
                {job.title}
              </h1>
              <p className="mt-1 text-base text-zinc-400">{job.company}</p>
            </div>

            <a
              href={job.url}
              target="_blank"
              rel="noopener noreferrer"
              className="shrink-0 rounded-lg border border-[#333] bg-[#1f1f1f] px-4 py-2 text-xs font-medium text-zinc-300 hover:bg-[#2a2a2a] transition-colors"
            >
              View Posting ↗
            </a>
          </div>

          {/* Meta row */}
          <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm text-zinc-500 border-t border-[#ffffff08] pt-4">
            <span className="flex items-center gap-1.5">
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
              {city}
            </span>
            {job.salary && (
              <span className="text-emerald-500 font-medium">{job.salary}</span>
            )}
            {job.date_posted && (
              <span>Posted {job.date_posted}</span>
            )}
            <span className="ml-auto font-mono text-xs text-zinc-700">
              First seen {formatDate(job.first_seen_date)}
            </span>
          </div>

          {/* Job summary */}
          {job.job_summary && (
            <p className="mt-4 text-sm leading-relaxed text-zinc-400">{job.job_summary}</p>
          )}
        </div>

        {/* Evaluation content */}
        {job.full_evaluation ? (
          <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-6">
            <EvaluationRenderer content={job.full_evaluation} />
          </div>
        ) : (
          <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-8 text-center text-sm text-zinc-600">
            No evaluation available for this job.
          </div>
        )}

        {/* Deep evaluation */}
        {job.deep_evaluation && (
          <div className="mt-4 rounded-xl border border-purple-900/40 bg-purple-950/20 p-6">
            <div className="mb-4 flex items-center gap-2">
              <span className="rounded-full border border-purple-800 bg-purple-950/60 px-2.5 py-1 font-mono text-[11px] font-semibold text-purple-400">
                DEEP EVAL
              </span>
              <span className="text-xs text-zinc-600">Application prep package</span>
            </div>
            <EvaluationRenderer content={job.deep_evaluation} />
          </div>
        )}
      </main>
    </div>
  )
}
