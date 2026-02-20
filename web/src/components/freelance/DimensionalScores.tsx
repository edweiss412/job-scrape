'use client'

import { useState } from 'react'

interface DimensionData {
  label: string
  score: number | null
  weight: string
  rationale: string | null
}

function DimensionBar({ dim }: { dim: DimensionData }) {
  const [hovered, setHovered] = useState(false)
  if (!dim.score) return null
  const pct = (dim.score / 5) * 100
  const colorClass = dim.score >= 4 ? 'bg-emerald-500' : dim.score >= 3 ? 'bg-amber-500' : 'bg-zinc-500'
  const textColorClass = dim.score >= 4 ? 'text-emerald-400' : dim.score >= 3 ? 'text-amber-400' : 'text-zinc-400'

  return (
    <div
      className="relative"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="flex items-center gap-2 text-xs py-1.5 cursor-default">
        <span className={`w-28 shrink-0 transition-colors ${hovered ? 'text-zinc-300' : 'text-zinc-500'}`}>
          {dim.label} <span className={`transition-colors ${hovered ? 'text-zinc-500' : 'text-zinc-700'}`}>({dim.weight})</span>
        </span>
        <div className="h-1.5 flex-1 rounded-full bg-zinc-800 relative">
          <div
            className={`h-1.5 rounded-full transition-all ${colorClass} ${hovered ? 'brightness-125 shadow-[0_0_6px_rgba(255,255,255,0.15)]' : ''}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className={`w-8 text-right font-mono transition-colors ${hovered ? textColorClass : 'text-zinc-600'}`}>
          {dim.score}/5
        </span>
      </div>
      {dim.rationale && (
        <div
          className={`absolute left-0 top-full z-10 max-w-md rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 text-[11px] leading-relaxed text-zinc-400 shadow-lg transition-all duration-150 pointer-events-none ${
            hovered ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-1'
          }`}
        >
          {dim.rationale}
        </div>
      )}
    </div>
  )
}

/** Extract a markdown section's content by heading name (fallback for older evals) */
function extractSection(fullEval: string, heading: string): string | null {
  const pattern = new RegExp(`## ${heading}\\s*\\n([\\s\\S]*?)(?=\\n## |$)`)
  const match = fullEval.match(pattern)
  if (!match) return null
  return match[1].trim().replace(/^- /gm, '').replace(/\n+/g, ' ').slice(0, 300)
}

interface Props {
  geographic_fit: number | null
  scale_gear: number | null
  work_type: number | null
  relationship_potential: number | null
  credibility: number | null
  geographic_fit_rationale?: string | null
  scale_gear_rationale?: string | null
  work_type_rationale?: string | null
  relationship_potential_rationale?: string | null
  credibility_rationale?: string | null
  full_evaluation: string | null
}

export function DimensionalScores(props: Props) {
  const eval_text = props.full_evaluation ?? ''

  const dimensions: DimensionData[] = [
    {
      label: 'Geographic Fit',
      score: props.geographic_fit,
      weight: '2x',
      rationale: props.geographic_fit_rationale || extractSection(eval_text, 'Geographic Fit'),
    },
    {
      label: 'Scale & Gear',
      score: props.scale_gear,
      weight: '2x',
      rationale: props.scale_gear_rationale || extractSection(eval_text, 'Gear Alignment'),
    },
    {
      label: 'Work Type',
      score: props.work_type,
      weight: '1x',
      rationale: props.work_type_rationale || extractSection(eval_text, 'Company Assessment'),
    },
    {
      label: 'Relationship',
      score: props.relationship_potential,
      weight: '1x',
      rationale: props.relationship_potential_rationale || extractSection(eval_text, 'Why They Would Want'),
    },
    {
      label: 'Credibility',
      score: props.credibility,
      weight: '1x',
      rationale: props.credibility_rationale || extractSection(eval_text, 'Potential Red Flags'),
    },
  ]

  const hasAny = dimensions.some(d => d.score)
  if (!hasAny) return null

  return (
    <div className="mb-4 rounded-xl border border-border bg-[#111] p-5">
      <h3 className="mb-3 font-mono text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Dimensional Scores</h3>
      <div className="space-y-0.5">
        {dimensions.map(dim => (
          <DimensionBar key={dim.label} dim={dim} />
        ))}
      </div>
    </div>
  )
}
