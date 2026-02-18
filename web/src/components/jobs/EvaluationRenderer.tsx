'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'

interface EvaluationRendererProps {
  content: string
}

// Section heading → accent color mapping
const SECTION_COLORS: Record<string, string> = {
  'ROLE SUMMARY':        '#737373',
  'MATCH SCORE':         '#10b981',
  'REQUIREMENTS ALREADY MET':                    '#10b981',
  'REQUIREMENTS WITH EXPERIENCE':                '#60a5fa',
  'TRUE GAPS':           '#f59e0b',
  'RED FLAGS':           '#f87171',
  'VERDICT':             '#a78bfa',
}

function getSectionColor(heading: string): string {
  const upper = heading.toUpperCase()
  for (const [key, color] of Object.entries(SECTION_COLORS)) {
    if (upper.includes(key)) return color
  }
  return '#737373'
}

export function EvaluationRenderer({ content }: EvaluationRendererProps) {
  const components: Components = {
    h3({ children }) {
      const text = String(children)
      const color = getSectionColor(text)
      return (
        <h3
          style={{
            color,
            fontFamily: 'Syne, sans-serif',
            fontWeight: 700,
            fontSize: '0.7rem',
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            marginTop: '1.75rem',
            marginBottom: '0.5rem',
            paddingBottom: '0.4rem',
            borderBottom: `1px solid ${color}22`,
          }}
        >
          {children}
        </h3>
      )
    },
    // Keep everything else as default prose
  }

  return (
    <div className="eval-prose">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
