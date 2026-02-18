import { Verdict, FitTier } from '@/lib/types'
import { VERDICT_STYLES, TIER_STYLES, cn } from '@/lib/utils'

interface VerdictBadgeProps {
  verdict: Verdict
  score?: number | null
  size?: 'sm' | 'md'
  className?: string
}

export function VerdictBadge({ verdict, score, size = 'md', className }: VerdictBadgeProps) {
  const s = VERDICT_STYLES[verdict]
  const textSize = size === 'sm' ? 'text-[10px]' : 'text-[11px]'
  const padding = size === 'sm' ? 'px-2 py-0.5' : 'px-2.5 py-1'

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full font-mono font-semibold uppercase tracking-wider border',
        s.bg, s.border, s.text, textSize, padding,
        className,
      )}
    >
      <span className={cn('h-1.5 w-1.5 rounded-full shrink-0', s.dot)} />
      {verdict}
      {score != null && <span className="opacity-60">· {score}</span>}
    </span>
  )
}

interface TierBadgeProps {
  tier: FitTier
  className?: string
}

export function TierBadge({ tier, className }: TierBadgeProps) {
  const s = TIER_STYLES[tier]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-mono font-semibold uppercase tracking-wider border',
        s.bg, s.border, s.text,
        className,
      )}
    >
      {tier}
    </span>
  )
}

export function NewBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-mono font-bold uppercase tracking-wider',
        'bg-blue-500/15 text-blue-400 border border-blue-500/20',
        className,
      )}
    >
      NEW
    </span>
  )
}
