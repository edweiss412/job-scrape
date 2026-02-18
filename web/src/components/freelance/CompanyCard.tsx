import Link from 'next/link'
import { FreelanceCompany } from '@/lib/types'
import { TierBadge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

interface CompanyCardProps {
  company: FreelanceCompany
  runDate: string
}

const CATEGORY_LABELS: Record<string, string> = {
  av_rental: 'AV Rental',
  production_co: 'Production Co.',
  venue: 'Venue',
  touring: 'Touring',
  corporate_av: 'Corporate AV',
  university: 'University',
}

export function CompanyCard({ company, runDate }: CompanyCardProps) {
  if (!company.fit_tier || company.fit_tier === 'SKIP') return null

  return (
    <Link
      href={`/freelance/${runDate}/${company.company_id}`}
      className={cn(
        'group block rounded-xl border p-5 transition-all duration-150',
        'bg-[#111] border-border',
        'hover:border-[#2a2a2a] hover:bg-surface-2',
      )}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <TierBadge tier={company.fit_tier} />
            {company.fit_score != null && (
              <span className="font-mono text-[10px] text-zinc-600">{company.fit_score}/100</span>
            )}
          </div>
          <h3 className="truncate text-sm font-semibold text-white group-hover:text-zinc-100">
            {company.name}
          </h3>
          <p className="mt-0.5 text-xs text-zinc-500">
            {company.city}{company.state ? `, ${company.state}` : ''}
          </p>
        </div>

        {company.category && (
          <span className="shrink-0 rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-zinc-600">
            {CATEGORY_LABELS[company.category] ?? company.category}
          </span>
        )}
      </div>

      {company.fit_reasoning && (
        <p className="mb-3 text-xs leading-relaxed text-zinc-500 line-clamp-2">
          {company.fit_reasoning}
        </p>
      )}

      <div className="flex items-center gap-3 text-[11px] text-zinc-600">
        {company.relationship && company.relationship !== 'new_prospect' && (
          <span className={cn(
            'rounded px-1.5 py-0.5 font-mono text-[10px] border',
            company.relationship === 'known_client'
              ? 'border-blue-900 bg-blue-950/40 text-blue-400'
              : 'border-purple-900 bg-purple-950/40 text-purple-400',
          )}>
            {company.relationship === 'known_client' ? 'Client' : 'Partner'}
          </span>
        )}
        {company.outreach_subject && (
          <span className="ml-auto text-zinc-700 truncate max-w-[60%]" title={company.outreach_subject}>
            Draft ready
          </span>
        )}
      </div>
    </Link>
  )
}
