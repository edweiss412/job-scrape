import { createClient } from '@/lib/supabase/server'
import { Nav } from '@/components/layout/nav'
import { CompanyCard } from '@/components/freelance/CompanyCard'
import { FreelanceCompany } from '@/lib/types'
import { formatRunDate, isJunkFreelanceCompany } from '@/lib/utils'
import Link from 'next/link'
import { notFound } from 'next/navigation'

interface Props {
  params: Promise<{ runDate: string }>
}

export default async function FreelanceRunPage({ params }: Props) {
  const { runDate } = await params
  const supabase = await createClient()

  const { data: companies, error } = await supabase
    .from('freelance_companies')
    .select('*')
    .eq('first_seen_date', runDate)
    .in('fit_tier', ['HOT', 'WARM', 'COLD'])
    .order('fit_score', { ascending: false })

  if (error) {
    return (
      <div className="flex min-h-screen flex-col">
        <Nav />
        <main className="flex flex-1 items-center justify-center">
          <p className="text-sm text-red-400">{error.message}</p>
        </main>
      </div>
    )
  }

  if (!companies?.length) notFound()

  const real = companies.filter((c: FreelanceCompany) => !isJunkFreelanceCompany(c.name))
  const hot = real.filter((c: FreelanceCompany) => c.fit_tier === 'HOT')
  const warm = real.filter((c: FreelanceCompany) => c.fit_tier === 'WARM')
  const cold = real.filter((c: FreelanceCompany) => c.fit_tier === 'COLD')

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-7xl px-4 py-8">
        <div className="mb-6 flex items-center gap-3">
          <Link href="/opportunities/freelance" className="text-zinc-600 hover:text-zinc-400 transition-colors">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </Link>
          <div>
            <h1
              className="text-lg font-bold text-white"
              style={{ fontFamily: 'Syne, sans-serif' }}
            >
              {formatRunDate(runDate)}
            </h1>
            <div className="mt-0.5 flex gap-3 font-mono text-[11px]">
              {hot.length > 0   && <span className="text-emerald-500">{hot.length} HOT</span>}
              {warm.length > 0  && <span className="text-amber-500">{warm.length} WARM</span>}
              {cold.length > 0  && <span className="text-zinc-600">{cold.length} COLD</span>}
            </div>
          </div>
        </div>

        {[{ label: 'HOT', items: hot }, { label: 'WARM', items: warm }, { label: 'COLD', items: cold }]
          .filter(({ items }) => items.length > 0)
          .map(({ label, items }) => (
            <section key={label} className="mb-8">
              <h2 className={`mb-3 font-mono text-xs font-semibold uppercase tracking-wider ${
                label === 'HOT' ? 'text-emerald-500' : label === 'WARM' ? 'text-amber-500' : 'text-zinc-600'
              }`}>
                {label} · {items.length}
              </h2>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((company: FreelanceCompany) => (
                  <CompanyCard key={company.company_id} company={company} runDate={runDate} basePath="/opportunities/freelance" />
                ))}
              </div>
            </section>
          ))}
      </main>
    </div>
  )
}
