import { createClient, createServiceClient } from '@/lib/supabase/server'
import { EvaluationRenderer } from '@/components/jobs/EvaluationRenderer'
import { DeepEvalRenderer } from '@/components/jobs/DeepEvalRenderer'
import { ResumeTailorButton } from '@/components/jobs/ResumeTailorButton'
import { JobDescription } from '@/components/jobs/JobDescription'
import { MatchScoreHeroWidget } from '@/components/jobs/eval-shared'
import { JobDetailActions } from '@/components/jobs/JobDetailActions'
import { MatchFeedbackButtons } from '@/components/jobs/MatchFeedbackButtons'
import { normalizeLocation, formatDate, VERDICT_STYLES } from '@/lib/utils'
import { Verdict, MatchFeedback } from '@/lib/types'
import Link from 'next/link'
import { notFound } from 'next/navigation'

interface Props {
  params: Promise<{ jobId: string }>
}

export default async function JobDetailPage({ params }: Props) {
  const { jobId } = await params

  const svc = createServiceClient()
  const supabase = await createClient()

  // Fetch raw job catalog data with service role (no RLS), exclude archived
  const { data: job } = await svc
    .from('jobs')
    .select('job_id, title, company, location, url, salary, date_posted, first_seen_date, description')
    .eq('job_id', jobId)
    .is('archived_at', null)
    .single()

  if (!job) notFound()

  // Fetch this user's evaluation for the job (RLS auto-scopes to current user)
  const { data: evalRow } = await supabase
    .from('user_evaluations')
    .select('match_score, match_verdict, match_reasoning, job_summary, full_evaluation, deep_evaluation, match_feedback')
    .eq('job_id', jobId)
    .maybeSingle()

  const combined = { ...job, ...(evalRow ?? {}) }

  const verdict = combined.match_verdict as Verdict | null
  const verdictStyle = verdict ? VERDICT_STYLES[verdict] : null
  const city = normalizeLocation(combined.location)
  const datePosted = combined.date_posted && /^\d{4}-\d{2}-\d{2}/.test(combined.date_posted) ? combined.date_posted : null

  const evalText = combined.full_evaluation ?? ''
  const evalCompensation = evalText.match(/\*\*Compensation[^*]*\*\*:?\s*([^\n]+)/i)?.[1]?.trim() ?? null
  const evalIndustry = evalText.match(/\*\*Industry Vertical[^*]*\*\*:?\s*([^\n]+)/i)?.[1]?.trim() ?? null
  const compensation = evalCompensation ?? combined.salary ?? null

  const hasEval = !!combined.full_evaluation
  const hasDeepEval = !!combined.deep_evaluation
  const hasDescription = !!combined.description

  return (
      <main className="mx-auto w-full max-w-4xl px-4 py-5 sm:py-8">
        <Link
          href="/opportunities/fulltime"
          className="mb-6 inline-flex items-center gap-1.5 text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
        >
          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Full Time
        </Link>

        {/* Job header card */}
        <div
          className={`mb-4 rounded-xl border p-4 sm:p-5 ${
            verdictStyle ? `${verdictStyle.bg} ${verdictStyle.border}` : 'bg-[#111] border-border'
          }`}
        >
          {/* Title row: title + score ring */}
          <div className="flex items-start gap-4">
            <div className="min-w-0 flex-1">
              <h1
                className="text-lg font-bold text-white sm:text-xl"
                style={{ fontFamily: 'Syne, sans-serif' }}
              >
                {combined.title}
              </h1>
              <p className="mt-0.5 text-sm text-zinc-400">{combined.company}</p>

              {/* Metadata row — directly under title */}
              <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-zinc-500">
                <span className="flex items-center gap-1">
                  <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                  {city}
                </span>
                {compensation && (
                  <span className="text-emerald-500 font-medium">{compensation}</span>
                )}
                {evalIndustry && (
                  <span className="font-mono text-[10px] text-zinc-600">{evalIndustry}</span>
                )}
                {datePosted && (
                  <span>Posted {datePosted}</span>
                )}
                <span className="font-mono text-[10px] text-zinc-700">
                  Seen {formatDate(combined.first_seen_date)}
                </span>
              </div>
            </div>

            {/* Score ring — right of title, not mixed with buttons */}
            <MatchScoreHeroWidget fullEvaluation={combined.full_evaluation ?? null} matchScore={combined.match_score ?? null} matchVerdict={combined.match_verdict ?? null} compact />
          </div>

          {combined.job_summary && (
            <p className="mt-3 text-sm leading-relaxed text-zinc-400 border-t border-[#ffffff06] pt-3">{combined.job_summary}</p>
          )}

          {/* Actions row — own line at the bottom */}
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[#ffffff06] pt-3">
            <JobDetailActions jobId={jobId} />
            {verdict && ['STRONG', 'MODERATE', 'STRETCH'].includes(verdict) && (
              <ResumeTailorButton jobId={jobId} jobTitle={combined.title} company={combined.company} />
            )}
            <MatchFeedbackButtons jobId={jobId} initialFeedback={(evalRow?.match_feedback as MatchFeedback | null) ?? null} />
            <div className="flex-1" />
            <a
              href={combined.url}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-lg border border-[#333] bg-border px-3.5 py-1.5 text-xs font-medium text-zinc-300 hover:bg-[#2a2a2a] transition-colors"
            >
              View Posting ↗
            </a>
          </div>
        </div>

        {/* Section anchor links */}
        {(hasEval || hasDescription || hasDeepEval) && (
          <div className="mb-3 flex flex-wrap items-center gap-3 text-[11px] font-mono">
            {hasEval && (
              <a href="#evaluation" className="text-zinc-500 hover:text-zinc-300 transition-colors">Evaluation</a>
            )}
            {hasDescription && (
              <>
                {hasEval && <span className="text-zinc-800">|</span>}
                <a href="#description" className="text-zinc-500 hover:text-zinc-300 transition-colors">Job Description</a>
              </>
            )}
            {hasDeepEval && (
              <>
                <span className="text-zinc-800">|</span>
                <a href="#deep-eval" className="text-zinc-500 hover:text-zinc-300 transition-colors">Deep Eval</a>
              </>
            )}
          </div>
        )}

        {evalText && /No description available/i.test(evalText) && (
          <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-amber-800/40 bg-amber-950/30 px-4 py-3 text-sm text-amber-400/90">
            <span className="mt-px shrink-0">&#9888;</span>
            <span>This evaluation was generated without access to the full job description. Scores may be less accurate.</span>
          </div>
        )}

        {/* AI Evaluation — above job description (the app's differentiator) */}
        {combined.full_evaluation ? (
          <div id="evaluation" className="mb-3 rounded-xl border border-border bg-[#111] p-4 sm:p-5">
            <EvaluationRenderer content={combined.full_evaluation} matchScore={combined.match_score ?? null} matchVerdict={combined.match_verdict ?? null} />
          </div>
        ) : (
          <div className="mb-3 rounded-xl border border-border bg-[#111] p-6 text-center text-sm text-zinc-600">
            No evaluation available for this job.
          </div>
        )}

        {/* Job description — below evaluation */}
        {combined.description && (
          <div id="description" className="mb-3">
            <JobDescription html={combined.description} />
          </div>
        )}

        {/* Deep evaluation */}
        {combined.deep_evaluation && (
          <div id="deep-eval" className="mb-3 rounded-xl border border-border bg-background p-4 sm:p-5">
            <div className="mb-5 flex items-center gap-3">
              <span className="rounded border border-purple-800/60 bg-purple-950/40 px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-widest text-purple-400">
                Deep Eval
              </span>
              <span className="text-xs text-zinc-700">Application prep package</span>
            </div>
            <DeepEvalRenderer content={combined.deep_evaluation} />
          </div>
        )}
      </main>
  )
}
