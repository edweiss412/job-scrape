'use client'

import { useState, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  parseSections, getSectionMeta, proseComponents,
  MatchScoreSection, VerdictSection, SectionCard, NavPills,
  RequirementsGroupRow, expandSections, isReqSection, type Section,
} from './eval-shared'

// ─── Types ───────────────────────────────────────────────────────────────────

interface TailoringItem {
  sectionTitle: string
  before?: string
  after?: string
  add?: string
  addLabel?: string
  why?: string
  placement?: string
}

// ─── Tailoring parser ─────────────────────────────────────────────────────────

function parseTailoringItems(content: string): TailoringItem[] {
  const items: TailoringItem[] = []
  let current: TailoringItem = { sectionTitle: '' }
  let hasData = false

  for (const line of content.split('\n')) {
    const secMatch = line.match(/^\*\*(\d+\.\s+[^*]+)\*\*$/)
    if (secMatch) {
      if (hasData) { items.push(current); hasData = false }
      current = { sectionTitle: secMatch[1].trim() }
      continue
    }
    const before    = line.match(/\*\*BEFORE:\*\*\s*(.+)/)
    const after     = line.match(/\*\*AFTER:\*\*\s*(.+)/)
    const add       = line.match(/\*\*ADD(?:\s*\([^)]*\))?:\*\*\s*(.+)/)
    const addLabel  = line.match(/\*\*ADD \(([^)]+)\):\*\*/)
    const why       = line.match(/\*(?:WHY|Why):\*\s*(.+)/)
    const place     = line.match(/\*(?:PLACEMENT|Placement):\*\s*(.+)/)

    if (before)   { current.before    = before[1].replace(/^["']|["']$/g, '').trim(); hasData = true }
    if (after)    { current.after     = after[1].replace(/^["']|["']$/g, '').trim();  hasData = true }
    if (add)      { current.add       = add[1].replace(/^["']|["']$/g, '').trim();    hasData = true }
    if (addLabel) { current.addLabel  = addLabel[1] }
    if (why)      { current.why       = why[1].trim() }
    if (place)    { current.placement = place[1].trim() }
  }
  if (hasData) items.push(current)
  return items
}

// ─── Section-specific renderers ───────────────────────────────────────────────

function TailoringSection({ content }: { content: string }) {
  const items = parseTailoringItems(content)

  if (items.length === 0) {
    return (
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={proseComponents('#fb923c')}>
        {content}
      </ReactMarkdown>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {items.map((item, i) => (
        <div key={i} style={{ borderRadius: '8px', overflow: 'hidden', border: '1px solid #1f1f1f' }}>
          {item.sectionTitle && (
            <div style={{
              padding: '0.5rem 1rem', background: '#0f0f0f', borderBottom: '1px solid #1a1a1a',
              fontFamily: 'Syne, sans-serif', fontSize: '0.65rem', fontWeight: 700,
              letterSpacing: '0.1em', textTransform: 'uppercase', color: '#fb923c',
            }}>
              {item.sectionTitle}
            </div>
          )}
          {item.before && (
            <div style={{ padding: '0.75rem 1rem', background: '#1a0e0a', borderBottom: '1px solid #2a1a12' }}>
              <div style={{ fontSize: '0.6rem', fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, letterSpacing: '0.1em', color: '#f87171', marginBottom: '0.35rem', textTransform: 'uppercase' }}>Before</div>
              <div style={{ fontSize: '0.83rem', color: '#c0a090', lineHeight: 1.65 }}>{item.before}</div>
            </div>
          )}
          {item.after && (
            <div style={{ padding: '0.75rem 1rem', background: '#0a1a0f', borderBottom: item.why ? '1px solid #1a2a1a' : undefined }}>
              <div style={{ fontSize: '0.6rem', fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, letterSpacing: '0.1em', color: '#34d399', marginBottom: '0.35rem', textTransform: 'uppercase' }}>After</div>
              <div style={{ fontSize: '0.83rem', color: '#90c0a0', lineHeight: 1.65 }}>{item.after}</div>
            </div>
          )}
          {item.add && !item.before && (
            <div style={{ padding: '0.75rem 1rem', background: '#0a100f', borderBottom: item.why ? '1px solid #1a2020' : undefined }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
                <div style={{ fontSize: '0.6rem', fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, letterSpacing: '0.1em', color: '#60a5fa', textTransform: 'uppercase' }}>Add</div>
                {item.addLabel && <div style={{ fontSize: '0.6rem', color: '#374151', fontFamily: 'JetBrains Mono, monospace' }}>{item.addLabel}</div>}
              </div>
              <div style={{ fontSize: '0.83rem', color: '#90a8c0', lineHeight: 1.65 }}>{item.add}</div>
              {item.placement && <div style={{ marginTop: '0.4rem', fontSize: '0.72rem', color: '#374151', fontStyle: 'italic' }}>Placement: {item.placement}</div>}
            </div>
          )}
          {item.why && (
            <div style={{ padding: '0.6rem 1rem', background: '#111', display: 'flex', gap: '0.6rem', alignItems: 'flex-start' }}>
              <span style={{ fontSize: '0.6rem', fontFamily: 'JetBrains Mono, monospace', color: '#4b5563', flexShrink: 0, paddingTop: '0.15rem', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Why</span>
              <span style={{ fontSize: '0.8rem', color: '#6b7280', lineHeight: 1.6, fontStyle: 'italic' }}>{item.why}</span>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function CoverLetterSection({ content, accentColor }: { content: string; accentColor: string }) {
  const chunks = content.split(/(?=\*\*Core Message:\*\*)/g).filter(c => c.trim())

  if (chunks.length < 2) {
    return <ReactMarkdown remarkPlugins={[remarkGfm]} components={proseComponents(accentColor)}>{content}</ReactMarkdown>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {chunks.map((chunk, i) => {
        const coreMsg = chunk.match(/\*\*Core Message:\*\*\s*["']?([^"'\n]+)["']?/)
        const why     = chunk.match(/\*(?:Why it matters|Why):\*\s*(.+)/)
        const opening = chunk.match(/\*(?:Suggested opening|Phrasing):\*\s*["']?(.+?)["']?\s*$/)
        return (
          <div key={i} style={{
            padding: '1rem', background: '#0d0d0d', border: '1px solid #1f1f1f',
            borderLeft: `3px solid ${accentColor}50`, borderRadius: '0 8px 8px 0',
          }}>
            <div style={{ fontSize: '0.6rem', fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color: accentColor, letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: '0.4rem', opacity: 0.7 }}>
              Point {i + 1}
            </div>
            {coreMsg && <div style={{ fontSize: '0.9rem', color: '#e0e0e0', fontWeight: 600, lineHeight: 1.5, marginBottom: '0.5rem' }}>"{coreMsg[1].trim()}"</div>}
            {why     && <div style={{ fontSize: '0.8rem', color: '#6b7280', lineHeight: 1.6, marginBottom: '0.5rem' }}>{why[1].trim()}</div>}
            {opening && (
              <div style={{ marginTop: '0.5rem', padding: '0.5rem 0.75rem', background: `${accentColor}08`, border: `1px solid ${accentColor}15`, borderRadius: '5px', fontSize: '0.8rem', color: '#9ca3af', fontStyle: 'italic', lineHeight: 1.6 }}>
                {opening[1].trim()}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function InterviewPrepSection({ content, accentColor }: { content: string; accentColor: string }) {
  const [openIdx, setOpenIdx] = useState<number[]>([])
  const toggle = (i: number) => setOpenIdx(prev => prev.includes(i) ? prev.filter(x => x !== i) : [...prev, i])

  type Block = { type: 'category'; label: string } | { type: 'question'; text: string; idx: number }
  const blocks: Block[] = []
  let qIdx = 0

  for (const line of content.split('\n')) {
    const cat    = line.match(/^\*\*([^*]+)\*\*\s*$/)
    const q      = line.match(/^\d+\.\s+(.+)/)
    const bullet = line.match(/^[-*]\s+\*\*([^*]+):\*\*\s*(.+)/)

    if (cat && !q) { blocks.push({ type: 'category', label: cat[1] }) }
    else if (q)    { blocks.push({ type: 'question', text: q[1].replace(/^["']|["']$/g, ''), idx: qIdx++ }) }
    else if (bullet) { blocks.push({ type: 'question', text: `${bullet[1]}: ${bullet[2]}`, idx: qIdx++ }) }
  }

  if (blocks.length === 0) {
    return <ReactMarkdown remarkPlugins={[remarkGfm]} components={proseComponents(accentColor)}>{content}</ReactMarkdown>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
      {blocks.map((block, i) => {
        if (block.type === 'category') {
          return (
            <div key={i} style={{
              marginTop: i === 0 ? 0 : '0.75rem', marginBottom: '0.35rem',
              fontSize: '0.6rem', fontFamily: 'Syne, sans-serif', fontWeight: 700,
              letterSpacing: '0.12em', textTransform: 'uppercase', color: accentColor,
              opacity: 0.7, borderBottom: `1px solid ${accentColor}15`, paddingBottom: '0.3rem',
            }}>
              {block.label}
            </div>
          )
        }
        const isOpen = openIdx.includes(block.idx)
        return (
          <button
            key={i}
            onClick={() => toggle(block.idx)}
            style={{
              all: 'unset', display: 'flex', alignItems: 'flex-start', gap: '0.6rem',
              padding: '0.6rem 0.75rem', borderRadius: '6px',
              background: isOpen ? `${accentColor}08` : 'transparent',
              border: `1px solid ${isOpen ? accentColor + '25' : 'transparent'}`,
              cursor: 'pointer', textAlign: 'left', transition: 'all 0.15s', width: '100%',
            }}
          >
            <span style={{
              flexShrink: 0, width: '14px', height: '14px', borderRadius: '50%',
              border: `1.5px solid ${accentColor}50`, display: 'flex', alignItems: 'center',
              justifyContent: 'center', marginTop: '0.15rem', fontSize: '8px', color: accentColor,
              transition: 'all 0.15s', background: isOpen ? `${accentColor}20` : 'transparent',
            }}>
              {isOpen ? '−' : '+'}
            </span>
            <span style={{ fontSize: '0.85rem', color: isOpen ? '#e0e0e0' : '#9ca3af', lineHeight: 1.6 }}>
              {block.text}
            </span>
          </button>
        )
      })}
    </div>
  )
}

// ─── Section content dispatcher ───────────────────────────────────────────────

function renderSectionContent(sec: Section, accentColor: string) {
  const upper = sec.title.toUpperCase()
  if (upper.includes('MATCH SCORE'))     return <MatchScoreSection content={sec.content} />
  if (upper.includes('VERDICT'))         return <VerdictSection content={sec.content} accentColor={accentColor} />
  if (upper.includes('RESUME TAILORING'))return <TailoringSection content={sec.content} />
  if (upper.includes('COVER LETTER'))    return <CoverLetterSection content={sec.content} accentColor={accentColor} />
  if (upper.includes('INTERVIEW PREP'))  return <InterviewPrepSection content={sec.content} accentColor={accentColor} />
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={proseComponents(accentColor)}>
      {sec.content}
    </ReactMarkdown>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

interface DeepEvalRendererProps {
  content: string
}

export function DeepEvalRenderer({ content }: DeepEvalRendererProps) {
  const sections = expandSections(parseSections(content, 'ds'))
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const sectionRefs = useRef<Record<string, HTMLDivElement | null>>({})

  const toggle = (slug: string) => {
    setCollapsed(prev => { const next = new Set(prev); next.has(slug) ? next.delete(slug) : next.add(slug); return next })
  }

  // Match score lives in the hero gauge; strip it from the section list
  const visibleSections = sections.filter(sec => !sec.title.toUpperCase().includes('MATCH SCORE'))

  if (visibleSections.length === 0) return null

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
              <SectionCard section={sec} isCollapsed={collapsed.has(sec.slug)} onToggle={() => toggle(sec.slug)}>
                {renderSectionContent(sec, meta.color)}
              </SectionCard>
            </div>
          )
        })}
      </div>
    </div>
  )
}
