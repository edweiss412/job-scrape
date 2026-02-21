import { createClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { EvaluationRenderer } from '@/components/jobs/EvaluationRenderer'
import { TierBadge } from '@/components/ui/badge'
import { CompanyLogo } from '@/components/freelance/CompanyLogo'
import { FitTier } from '@/lib/types'
import { DimensionalScores } from '@/components/freelance/DimensionalScores'
import Link from 'next/link'
import { notFound } from 'next/navigation'

/* ── Helpers for cleaning scraped/LLM text ── */

/** Strip LLM metadata preamble (GEOGRAPHIC_FIT: 5 SCALE_GEAR: 3 …) before actual content */
function stripEvalPreamble(text: string): string {
  const idx = text.search(/^#{2,4}\s/m)
  if (idx > 0) return text.slice(idx).trim()
  return text
}

/** Remove common scraped CTA / nav artifacts */
function cleanInfoText(text: string): string {
  return text
    .replace(/\b(LEARN MORE|VIEW CASE STUDY|READ MORE|VIEW ALL|CLICK HERE|SEE MORE|SHOW MORE|CONTACT US|APPLY NOW|GET IN TOUCH|SIGN UP|SUBSCRIBE|DOWNLOAD)\b/gi, '')
    .replace(/\s{2,}/g, ' ')
    .replace(/^[|,;\s]+|[|,;\s]+$/g, '')
    .trim()
}

/** Try to split text into discrete items via delimiters, deduplicating */
function extractItems(text: string): string[] | null {
  const cleaned = cleanInfoText(text)
  let items: string[] = []

  if (cleaned.includes('|')) {
    items = cleaned.split('|').map(s => s.trim()).filter(Boolean)
  } else if (cleaned.includes('\n')) {
    items = cleaned.split('\n').map(s => s.trim()).filter(Boolean)
  } else if (cleaned.split(',').length >= 3) {
    items = cleaned.split(',').map(s => s.trim()).filter(Boolean)
  }

  if (items.length < 2) return null

  const seen = new Set<string>()
  return items.filter(item => {
    const norm = item.toLowerCase().replace(/\s+/g, ' ')
    if (seen.has(norm)) return false
    seen.add(norm)
    return true
  })
}

/** Info card with smart formatting: tags for list-like data, clamped prose otherwise */
function InfoCard({ title, content }: { title: string; content: string }) {
  const items = extractItems(content)

  if (items) {
    return (
      <div className="rounded-xl border border-border bg-[#111] p-4">
        <h3 className="mb-2 font-mono text-[10px] font-semibold uppercase tracking-wider text-zinc-500">{title}</h3>
        <div className="flex flex-wrap gap-1.5">
          {items.slice(0, 10).map((item, i) => (
            <span key={i} className="rounded-md border border-zinc-800 bg-zinc-900/50 px-2 py-0.5 text-[11px] leading-relaxed text-zinc-400">
              {item.length > 60 ? item.slice(0, 57) + '…' : item}
            </span>
          ))}
          {items.length > 10 && (
            <span className="self-center text-[11px] text-zinc-600">+{items.length - 10} more</span>
          )}
        </div>
      </div>
    )
  }

  const cleaned = cleanInfoText(content)

  return (
    <div className="rounded-xl border border-border bg-[#111] p-4">
      <h3 className="mb-1.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-zinc-500">{title}</h3>
      <p className="line-clamp-4 text-xs leading-relaxed text-zinc-300">{cleaned}</p>
    </div>
  )
}

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
    .is('archived_at', null)
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

        <div className="mb-6 rounded-xl border border-border bg-[#111] p-6">
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
                className="shrink-0 rounded-lg border border-[#333] bg-border px-4 py-2 text-xs font-medium text-zinc-300 hover:bg-[#2a2a2a] transition-colors"
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
            fit_score={fitScore}
            fit_tier={fitTier}
            geographic_fit={userEval.geographic_fit}
            scale_gear={userEval.scale_gear}
            work_type={userEval.work_type}
            relationship_potential={userEval.relationship_potential}
            credibility={userEval.credibility}
            geographic_fit_rationale={userEval.geographic_fit_rationale}
            scale_gear_rationale={userEval.scale_gear_rationale}
            work_type_rationale={userEval.work_type_rationale}
            relationship_potential_rationale={userEval.relationship_potential_rationale}
            credibility_rationale={userEval.credibility_rationale}
            full_evaluation={fullEvaluation}
          />
        )}

        {(company.recent_activity || company.scale_signals || company.notable_clients || company.gear_mentioned) && (
          <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {company.gear_mentioned && <InfoCard title="Gear Mentioned" content={company.gear_mentioned} />}
            {company.notable_clients && <InfoCard title="Notable Clients" content={company.notable_clients} />}
            {company.scale_signals && <InfoCard title="Scale Signals" content={company.scale_signals} />}
            {company.recent_activity && <InfoCard title="Recent Activity" content={company.recent_activity} />}
          </div>
        )}

        {company.website_about && (
          <details className="mb-4 rounded-xl border border-border bg-[#111]">
            <summary className="cursor-pointer p-4 font-mono text-[10px] font-semibold uppercase tracking-wider text-zinc-500 hover:text-zinc-400 transition-colors">
              Website Content
            </summary>
            <div className="border-t border-border px-4 pb-4 pt-3">
              <p className="whitespace-pre-wrap text-xs leading-relaxed text-zinc-400">{company.website_about}</p>
            </div>
          </details>
        )}

        {fullEvaluation && (
          <div className="mb-4 rounded-xl border border-border bg-[#111] p-6">
            <EvaluationRenderer content={stripEvalPreamble(fullEvaluation)} />
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
