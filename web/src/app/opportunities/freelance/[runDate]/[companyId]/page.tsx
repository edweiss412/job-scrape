import { createClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { EvaluationRenderer } from '@/components/jobs/EvaluationRenderer'
import { TierBadge } from '@/components/ui/badge'
import { CompanyLogo } from '@/components/freelance/CompanyLogo'
import { FitTier } from '@/lib/types'
import { DimensionalScores } from '@/components/freelance/DimensionalScores'
import Link from 'next/link'
import { notFound } from 'next/navigation'

interface Props {
  params: Promise<{ runDate: string; companyId: string }>
}

export default async function CompanyDetailPage({ params }: Props) {
  const { companyId } = await params
  const supabase = await createClient()

  const { data: { user } } = await supabase.auth.getUser()

  const { data: company } = await supabase
    .from('freelance_companies')
    .select('*')
    .eq('company_id', companyId)
    .single()

  if (!company) notFound()

  // Fetch per-user evaluation if logged in
  let userEval = null
  if (user) {
    const { data } = await supabase
      .from('user_freelance_evaluations')
      .select('*')
      .eq('user_id', user.id)
      .eq('company_id', companyId)
      .single()
    userEval = data
  }

  // Prefer user eval data, fall back to legacy fields
  const fitTier = userEval?.fit_tier ?? company.fit_tier
  const fitScore = userEval?.fit_score ?? company.fit_score
  const fitReasoning = userEval?.fit_reasoning ?? company.fit_reasoning
  const fullEvaluation = userEval?.full_evaluation ?? company.full_evaluation
  const outreachDraft = userEval?.outreach_draft ?? company.outreach_draft
  const outreachSubject = userEval?.outreach_subject ?? company.outreach_subject
  const relationship = userEval?.relationship ?? company.relationship
  const relationshipNotes = userEval?.relationship_notes ?? company.relationship_notes

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-4xl px-4 py-8">
        <Link
          href="/opportunities/freelance"
          className="mb-6 inline-flex items-center gap-1.5 text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
        >
          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          All companies
        </Link>

        <div className="mb-6 rounded-xl border border-[#1f1f1f] bg-[#111] p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                {fitTier && <TierBadge tier={fitTier as FitTier} />}
                {fitScore != null && (
                  <span className="font-mono text-xs text-zinc-600">{fitScore}/100</span>
                )}
                {relationship && relationship !== 'new_prospect' && (
                  <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                    relationship === 'known_client'
                      ? 'border-blue-900 bg-blue-950/40 text-blue-400'
                      : 'border-purple-900 bg-purple-950/40 text-purple-400'
                  }`}>
                    {relationship === 'known_client' ? 'Client' : 'Partner'}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <CompanyLogo
                  logoUrl={company.logo_url}
                  website={company.website}
                  name={company.name}
                  size={48}
                />
                <div className="min-w-0">
                  <h1
                    className="text-xl font-bold text-white"
                    style={{ fontFamily: 'Syne, sans-serif' }}
                  >
                    {company.name}
                  </h1>
                  <p className="mt-1 text-sm text-zinc-400">
                    {company.city}{company.state ? `, ${company.state}` : ''}
                  </p>
                </div>
              </div>
            </div>

            {company.website && (
              <a
                href={company.website}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 rounded-lg border border-[#333] bg-[#1f1f1f] px-4 py-2 text-xs font-medium text-zinc-300 hover:bg-[#2a2a2a] transition-colors"
              >
                Website ↗
              </a>
            )}
          </div>

          {relationshipNotes && (
            <p className="mt-4 rounded-lg border border-blue-900/30 bg-blue-950/20 p-3 text-xs text-blue-300">
              {relationshipNotes}
            </p>
          )}
        </div>

        {userEval && (
          <DimensionalScores
            geographic_fit={userEval.geographic_fit}
            scale_gear={userEval.scale_gear}
            work_type={userEval.work_type}
            relationship_potential={userEval.relationship_potential}
            credibility={userEval.credibility}
            full_evaluation={fullEvaluation}
          />
        )}

        {(company.recent_activity || company.scale_signals || company.notable_clients || company.gear_mentioned) && (
          <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {company.gear_mentioned && (
              <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-4">
                <h3 className="mb-1.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Gear Mentioned</h3>
                <p className="text-xs leading-relaxed text-zinc-300">{company.gear_mentioned}</p>
              </div>
            )}
            {company.notable_clients && (
              <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-4">
                <h3 className="mb-1.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Notable Clients</h3>
                <p className="text-xs leading-relaxed text-zinc-300">{company.notable_clients}</p>
              </div>
            )}
            {company.scale_signals && (
              <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-4">
                <h3 className="mb-1.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Scale Signals</h3>
                <p className="text-xs leading-relaxed text-zinc-300">{company.scale_signals}</p>
              </div>
            )}
            {company.recent_activity && (
              <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-4">
                <h3 className="mb-1.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Recent Activity</h3>
                <p className="text-xs leading-relaxed text-zinc-300">{company.recent_activity}</p>
              </div>
            )}
          </div>
        )}

        {company.website_about && (
          <details className="mb-4 rounded-xl border border-[#1f1f1f] bg-[#111]">
            <summary className="cursor-pointer p-4 font-mono text-[10px] font-semibold uppercase tracking-wider text-zinc-500 hover:text-zinc-400 transition-colors">
              Website Content
            </summary>
            <div className="border-t border-[#1f1f1f] px-4 pb-4 pt-3">
              <p className="whitespace-pre-wrap text-xs leading-relaxed text-zinc-400">{company.website_about}</p>
            </div>
          </details>
        )}

        {fullEvaluation && (
          <div className="mb-4 rounded-xl border border-[#1f1f1f] bg-[#111] p-6">
            <EvaluationRenderer content={fullEvaluation} />
          </div>
        )}

        {outreachDraft && (
          <div className="rounded-xl border border-amber-900/30 bg-amber-950/10 p-6">
            <div className="mb-4 flex items-center gap-2">
              <span className="rounded-full border border-amber-800 bg-amber-950/60 px-2.5 py-1 font-mono text-[11px] font-semibold text-amber-400">
                OUTREACH DRAFT
              </span>
              {outreachSubject && (
                <span className="text-xs text-zinc-600 truncate">
                  Subject: {outreachSubject}
                </span>
              )}
            </div>
            <pre className="whitespace-pre-wrap text-xs leading-relaxed text-zinc-300 font-mono">
              {outreachDraft}
            </pre>
          </div>
        )}
      </main>
    </div>
  )
}
