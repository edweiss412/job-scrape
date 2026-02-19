import { createClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { EvaluationRenderer } from '@/components/jobs/EvaluationRenderer'
import { TierBadge } from '@/components/ui/badge'
import { FitTier } from '@/lib/types'
import Link from 'next/link'
import { notFound } from 'next/navigation'

interface Props {
  params: Promise<{ runDate: string; companyId: string }>
}

export default async function CompanyDetailPage({ params }: Props) {
  const { companyId } = await params
  const supabase = await createClient()

  const { data: company } = await supabase
    .from('freelance_companies')
    .select('*')
    .eq('company_id', companyId)
    .single()

  if (!company) notFound()

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
                {company.fit_tier && <TierBadge tier={company.fit_tier as FitTier} />}
                {company.fit_score != null && (
                  <span className="font-mono text-xs text-zinc-600">{company.fit_score}/100</span>
                )}
                {company.relationship && company.relationship !== 'new_prospect' && (
                  <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                    company.relationship === 'known_client'
                      ? 'border-blue-900 bg-blue-950/40 text-blue-400'
                      : 'border-purple-900 bg-purple-950/40 text-purple-400'
                  }`}>
                    {company.relationship === 'known_client' ? 'Client' : 'Partner'}
                  </span>
                )}
              </div>
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

          {company.relationship_notes && (
            <p className="mt-4 rounded-lg border border-blue-900/30 bg-blue-950/20 p-3 text-xs text-blue-300">
              {company.relationship_notes}
            </p>
          )}
        </div>

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

        {company.full_evaluation && (
          <div className="mb-4 rounded-xl border border-[#1f1f1f] bg-[#111] p-6">
            <EvaluationRenderer content={company.full_evaluation} />
          </div>
        )}

        {company.outreach_draft && (
          <div className="rounded-xl border border-amber-900/30 bg-amber-950/10 p-6">
            <div className="mb-4 flex items-center gap-2">
              <span className="rounded-full border border-amber-800 bg-amber-950/60 px-2.5 py-1 font-mono text-[11px] font-semibold text-amber-400">
                OUTREACH DRAFT
              </span>
              {company.outreach_subject && (
                <span className="text-xs text-zinc-600 truncate">
                  Subject: {company.outreach_subject}
                </span>
              )}
            </div>
            <pre className="whitespace-pre-wrap text-xs leading-relaxed text-zinc-300 font-mono">
              {company.outreach_draft}
            </pre>
          </div>
        )}
      </main>
    </div>
  )
}
