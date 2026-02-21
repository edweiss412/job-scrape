import { createClient, createServiceClient } from '@/lib/supabase/server'
import { Verdict } from '@/lib/types'
import Link from 'next/link'

const DONUT_SIZE = 88
const DONUT_STROKE = 7
const DONUT_RADIUS = (DONUT_SIZE - DONUT_STROKE) / 2
const DONUT_CIRCUMFERENCE = 2 * Math.PI * DONUT_RADIUS

function DonutChart({ segments }: { segments: { value: number; color: string }[] }) {
  const total = segments.reduce((s, seg) => s + seg.value, 0)
  if (total === 0) return null

  let accumulated = 0

  return (
    <svg width={DONUT_SIZE} height={DONUT_SIZE} viewBox={`0 0 ${DONUT_SIZE} ${DONUT_SIZE}`}>
      <circle
        cx={DONUT_SIZE / 2}
        cy={DONUT_SIZE / 2}
        r={DONUT_RADIUS}
        fill="none"
        stroke="#1a1a1a"
        strokeWidth={DONUT_STROKE}
      />
      {segments.filter(s => s.value > 0).map((seg, i) => {
        const pct = seg.value / total
        const offset = DONUT_CIRCUMFERENCE * (1 - pct)
        const rotation = (accumulated / total) * 360 - 90
        accumulated += seg.value

        return (
          <circle
            key={i}
            cx={DONUT_SIZE / 2}
            cy={DONUT_SIZE / 2}
            r={DONUT_RADIUS}
            fill="none"
            stroke={seg.color}
            strokeWidth={DONUT_STROKE}
            strokeDasharray={DONUT_CIRCUMFERENCE}
            strokeDashoffset={offset}
            transform={`rotate(${rotation} ${DONUT_SIZE / 2} ${DONUT_SIZE / 2})`}
          />
        )
      })}
    </svg>
  )
}

function MetricRow({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-zinc-600">{label}</span>
      <span className={`font-mono text-xs font-medium tabular-nums ${color}`}>{count}</span>
    </div>
  )
}

export async function DashboardCards({ userId }: { userId: string | null }) {
  const supabase = await createClient()
  const svc = createServiceClient()

  const [evalDataResult, freelanceDataResult, resumeResult, unevaluatedResult, profileResult] = await Promise.all([
    supabase
      .from('user_evaluations')
      .select('match_verdict')
      .not('match_verdict', 'is', null),
    supabase
      .from('freelance_companies')
      .select('fit_tier')
      .is('archived_at', null)
      .in('fit_tier', ['HOT', 'WARM', 'COLD']),
    userId
      ? svc.from('resumes')
          .select('id')
          .eq('user_id', userId)
          .eq('is_primary', true)
          .maybeSingle()
      : Promise.resolve({ data: null }),
    userId
      ? svc.rpc('count_unevaluated_jobs', { p_user_id: userId })
      : Promise.resolve({ data: null }),
    userId
      ? svc.from('user_profiles')
          .select('eval_completed_at')
          .eq('user_id', userId)
          .maybeSingle()
      : Promise.resolve({ data: null }),
  ])

  const hasResume = !!resumeResult.data

  // Verdict counts
  const verdicts: Record<Verdict, number> = { STRONG: 0, MODERATE: 0, STRETCH: 0, WEAK: 0 }
  for (const row of (evalDataResult.data ?? [])) {
    if (row.match_verdict && row.match_verdict in verdicts) {
      verdicts[row.match_verdict as Verdict]++
    }
  }
  const totalEvals = Object.values(verdicts).reduce((a, b) => a + b, 0)

  // Freelance tier counts
  const tiers = { HOT: 0, WARM: 0, COLD: 0 }
  for (const row of (freelanceDataResult.data ?? [])) {
    if (row.fit_tier && row.fit_tier in tiers) {
      tiers[row.fit_tier as keyof typeof tiers]++
    }
  }
  const totalFreelance = Object.values(tiers).reduce((a, b) => a + b, 0)

  // Unevaluated count
  const unevaluated = (unevaluatedResult?.data as { count: number } | null)?.count ?? 0

  // Last evaluation date
  const lastEvalLabel = profileResult.data?.eval_completed_at
    ? new Date(profileResult.data.eval_completed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : null

  return (
    <>
      {/* Setup prompt (no resume) */}
      {!hasResume && totalEvals === 0 && (
        <div className="mb-10 rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30 p-8 sm:p-12">
          <div className="max-w-lg">
            <h2
              className="mb-2 text-lg font-bold text-white"
              style={{ fontFamily: 'Syne, sans-serif' }}
            >
              Get started
            </h2>
            <p className="mb-6 text-sm leading-relaxed text-zinc-500">
              Upload your resume and we&apos;ll evaluate job listings against your experience.
              AI-powered match scoring across 5+ sources, updated automatically.
            </p>
            <Link
              href="/profile"
              className="inline-flex items-center gap-2 rounded-lg border border-emerald-800/40 bg-emerald-950/20 px-5 py-2.5 text-sm font-medium text-emerald-400 transition-all hover:border-emerald-700/40 hover:bg-emerald-950/40"
            >
              Upload Resume
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
            </Link>
          </div>
        </div>
      )}

      {/* Channel Cards */}
      <div className="grid gap-4 sm:grid-cols-3 sm:gap-5">

        {/* Full Time */}
        <Link
          href="/opportunities/fulltime"
          className="group relative overflow-hidden rounded-xl border border-border bg-[#111] p-6 transition-all hover:border-[#2a2a2a] hover:bg-surface-2"
        >
          <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-emerald-500/80 to-emerald-500/0" />

          <div className="mb-5 flex items-center justify-between">
            <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.15em] text-zinc-500">
              Full Time
            </span>
            <svg className="h-4 w-4 text-zinc-700 transition-transform group-hover:translate-x-0.5 group-hover:text-zinc-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </div>

          {totalEvals > 0 ? (
            <>
              <div className="flex items-center gap-5">
                <div className="relative shrink-0">
                  <DonutChart
                    segments={[
                      { value: verdicts.STRONG, color: '#34d399' },
                      { value: verdicts.MODERATE, color: '#fbbf24' },
                      { value: verdicts.STRETCH, color: '#fb923c' },
                      { value: verdicts.WEAK, color: '#f87171' },
                    ]}
                  />
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className="text-xl font-bold tabular-nums text-white">{verdicts.STRONG}</span>
                    <span className="text-[9px] font-medium text-emerald-400/80">strong</span>
                  </div>
                </div>
                <div className="flex-1 space-y-1.5">
                  <MetricRow label="Moderate" count={verdicts.MODERATE} color="text-amber-400/70" />
                  <MetricRow label="Stretch" count={verdicts.STRETCH} color="text-orange-400/60" />
                  <MetricRow label="Weak" count={verdicts.WEAK} color="text-zinc-600" />
                </div>
              </div>
              {unevaluated > 0 && (
                <div className="mt-4 rounded-md border border-emerald-900/30 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-400/80">
                  {unevaluated} new job{unevaluated !== 1 ? 's' : ''} to evaluate
                </div>
              )}
              {lastEvalLabel && (
                <p className="mt-4 border-t border-zinc-800/50 pt-3 text-[11px] text-zinc-700">
                  Evaluated {lastEvalLabel}
                </p>
              )}
            </>
          ) : hasResume ? (
            <div className="py-4">
              <p className="mb-1 text-sm text-zinc-500">No evaluations yet</p>
              <p className="text-xs text-zinc-700">
                Trigger an evaluation to score jobs against your resume.
              </p>
            </div>
          ) : (
            <div className="py-4">
              <p className="mb-1 text-sm text-zinc-500">Upload a resume to start</p>
              <p className="text-xs text-zinc-700">
                AI-scored matches from 5+ job sources.
              </p>
            </div>
          )}
        </Link>

        {/* Freelance */}
        <Link
          href="/opportunities/freelance"
          className="group relative overflow-hidden rounded-xl border border-border bg-[#111] p-6 transition-all hover:border-[#2a2a2a] hover:bg-surface-2"
        >
          <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-amber-500/80 to-amber-500/0" />

          <div className="mb-5 flex items-center justify-between">
            <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.15em] text-zinc-500">
              Freelance
            </span>
            <svg className="h-4 w-4 text-zinc-700 transition-transform group-hover:translate-x-0.5 group-hover:text-zinc-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </div>

          {totalFreelance > 0 ? (
            <>
              <div className="flex items-center gap-5">
                <div className="relative shrink-0">
                  <DonutChart
                    segments={[
                      { value: tiers.HOT, color: '#34d399' },
                      { value: tiers.WARM, color: '#fbbf24' },
                      { value: tiers.COLD, color: '#71717a' },
                    ]}
                  />
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className="text-xl font-bold tabular-nums text-white">{tiers.HOT}</span>
                    <span className="text-[9px] font-medium text-amber-400/80">hot</span>
                  </div>
                </div>
                <div className="flex-1 space-y-1.5">
                  <MetricRow label="Warm" count={tiers.WARM} color="text-amber-400/60" />
                  <MetricRow label="Cold" count={tiers.COLD} color="text-zinc-600" />
                </div>
              </div>
            </>
          ) : (
            <div className="py-4">
              <p className="mb-1 text-sm text-zinc-500">No prospects yet</p>
              <p className="text-xs text-zinc-700">
                Companies discovered for cold outreach.
              </p>
            </div>
          )}
        </Link>

        {/* Social (coming soon) */}
        <div className="group relative overflow-hidden rounded-xl border border-dashed border-zinc-800 bg-[#0d0d0d] p-6">
          <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-blue-500/30 to-blue-500/0" />

          <div className="mb-5 flex items-center justify-between">
            <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.15em] text-zinc-600">
              Social
            </span>
            <span className="rounded-full border border-zinc-800 bg-zinc-900 px-2 py-0.5 font-mono text-[9px] text-zinc-600">
              Soon
            </span>
          </div>

          <div className="py-4">
            <p className="mb-1 text-sm text-zinc-600">Group monitoring</p>
            <p className="text-xs text-zinc-800">
              Automated gig alerts from AV community groups on Facebook.
            </p>
          </div>
        </div>
      </div>
    </>
  )
}
