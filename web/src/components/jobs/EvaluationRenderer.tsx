'use client'

import { useState, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  parseSections, getSectionMeta, proseComponents,
  MatchScoreSection, VerdictSection, SectionCard, NavPills,
  RequirementsGroupRow, expandSections, isReqSection, type Section,
} from './eval-shared'

// ─── Main component ───────────────────────────────────────────────────────────

interface EvaluationRendererProps {
  content: string
}

export function EvaluationRenderer({ content }: EvaluationRendererProps) {
  const sections = expandSections(parseSections(content, 'ev'))
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const sectionRefs = useRef<Record<string, HTMLDivElement | null>>({})

  const toggle = (slug: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      next.has(slug) ? next.delete(slug) : next.add(slug)
      return next
    })
  }

  // Match score lives in the hero gauge; strip it from the section list
  const visibleSections = sections.filter(sec => !sec.title.toUpperCase().includes('MATCH SCORE'))

  // Fallback: no sections parsed — render raw markdown
  if (visibleSections.length === 0) {
    return (
      <div className="eval-prose">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
    )
  }

  const reqSections = visibleSections.filter(sec => isReqSection(sec.title))
  const reqSlugs = new Set(reqSections.map(s => s.slug))
  const groupSlug = reqSections[0]?.slug ?? ''

  // Propagate group collapse state to all req section pills in NavPills
  const navCollapsed = new Set(collapsed)
  if (collapsed.has(groupSlug)) reqSlugs.forEach(slug => navCollapsed.add(slug))

  const scrollTo = (slug: string) => {
    const targetSlug = reqSlugs.has(slug) ? groupSlug : slug
    sectionRefs.current[targetSlug]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setCollapsed(prev => { const next = new Set(prev); next.delete(targetSlug); return next })
  }

  return (
    <div>
      <NavPills sections={visibleSections} collapsed={navCollapsed} onScrollTo={scrollTo} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {visibleSections.map(sec => {
          // Requirement sections: render as a single grouped row at the first occurrence
          if (reqSlugs.has(sec.slug)) {
            if (sec.slug !== reqSections[0]?.slug) return null
            return (
              <div key="req-group" ref={el => { sectionRefs.current[sec.slug] = el }}>
                <RequirementsGroupRow
                  sections={reqSections}
                  isCollapsed={collapsed.has(groupSlug)}
                  onToggle={() => toggle(groupSlug)}
                />
              </div>
            )
          }

          const meta = getSectionMeta(sec.title)
          return (
            <div key={sec.slug} ref={el => { sectionRefs.current[sec.slug] = el }}>
              <SectionCard
                section={sec}
                isCollapsed={collapsed.has(sec.slug)}
                onToggle={() => toggle(sec.slug)}
              >
                {renderSection(sec.title, sec.content, meta.color)}
              </SectionCard>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function renderSection(title: string, content: string, accentColor: string) {
  const upper = title.toUpperCase()
  if (upper.includes('MATCH SCORE')) return <MatchScoreSection content={content} />
  if (upper.includes('VERDICT'))     return <VerdictSection content={content} accentColor={accentColor} />
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={proseComponents(accentColor)}>
      {content}
    </ReactMarkdown>
  )
}
