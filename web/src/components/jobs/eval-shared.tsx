'use client'

import { useState, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'

// ─── Section metadata ─────────────────────────────────────────────────────────

export const SECTION_META: Record<string, { color: string; dimColor: string; icon: string; label: string }> = {
  'ROLE SUMMARY':                { color: '#94a3b8', dimColor: '#94a3b820', icon: '◈', label: 'Role' },
  'MATCH SCORE':                 { color: '#34d399', dimColor: '#34d39920', icon: '◎', label: 'Match' },
  'REQUIREMENTS ALREADY MET':    { color: '#34d399', dimColor: '#34d39918', icon: '✓', label: 'Strengths' },
  'REQUIREMENTS WITH EXPERIENCE':{ color: '#60a5fa', dimColor: '#60a5fa18', icon: '◑', label: 'Latent' },
  'TRUE GAPS':                   { color: '#fbbf24', dimColor: '#fbbf2418', icon: '△', label: 'Gaps' },
  'RED FLAGS':                   { color: '#f87171', dimColor: '#f8717118', icon: '⚑', label: 'Flags' },
  'LOGISTICS':                   { color: '#a78bfa', dimColor: '#a78bfa18', icon: '⊙', label: 'Logistics' },
  'VERDICT':                     { color: '#c084fc', dimColor: '#c084fc18', icon: '◆', label: 'Verdict' },
  'RESUME TAILORING':            { color: '#fb923c', dimColor: '#fb923c18', icon: '✎', label: 'Resume' },
  'COVER LETTER':                { color: '#38bdf8', dimColor: '#38bdf818', icon: '✉', label: 'Cover' },
  'INTERVIEW PREP':              { color: '#e879f9', dimColor: '#e879f918', icon: '◉', label: 'Interview' },
}

export function getSectionMeta(title: string) {
  const upper = title.toUpperCase()
  for (const [key, meta] of Object.entries(SECTION_META)) {
    if (upper.includes(key)) return meta
  }
  return { color: '#6b7280', dimColor: '#6b728018', icon: '·', label: title.split(' ')[0] }
}

// ─── Section parser ───────────────────────────────────────────────────────────

export interface Section {
  num: number
  title: string
  slug: string
  content: string
}

export function parseSections(content: string, prefix = 'sec'): Section[] {
  const sections: Section[] = []
  const lines = content.split('\n')
  let current: { num: number; title: string; slug: string; lines: string[] } | null = null

  for (const line of lines) {
    if (line.startsWith('### ')) {
      if (current) sections.push({ ...current, content: current.lines.join('\n').trim() })
      const header = line.replace('### ', '').trim()
      const m = header.match(/^(\d+)\.\s*(.+)/)
      const num = m ? parseInt(m[1]) : 0
      const title = m ? m[2].trim() : header
      current = { num, title, slug: `${prefix}-${num || title.toLowerCase().replace(/\W+/g, '-')}`, lines: [] }
    } else if (current) {
      current.lines.push(line)
    }
  }
  if (current) sections.push({ ...current, content: current.lines.join('\n').trim() })
  return sections
}

// ─── Requirements helpers ─────────────────────────────────────────────────────

export function isReqSection(title: string) {
  const u = title.toUpperCase()
  return u.includes('REQUIREMENTS') || u.includes('TRUE GAPS')
}

export function expandSections(sections: Section[]): Section[] {
  return sections.flatMap(sec => {
    const upper = sec.title.toUpperCase()
    if (upper.includes('RED FLAGS') && (upper.includes('LOGISTICS') || upper.includes('&'))) {
      const compStart = sec.content.search(/^####\s/m)
      if (compStart > -1) {
        const flagsContent = sec.content.slice(0, compStart).trim()
        const logisticsContent = sec.content.slice(compStart).replace(/^####\s+[^\n]+\n?/, '').trim()
        return [
          { ...sec, title: 'Red Flags', content: flagsContent },
          { ...sec, slug: sec.slug + '-logistics', title: 'Logistics', content: logisticsContent },
        ]
      }
    }
    return [sec]
  })
}

// ─── Match verdict helper ─────────────────────────────────────────────────────

export function detectMatchVerdict(content: string): { label: string; color: string; pct: number } | null {
  const upper = content.toUpperCase()
  if (upper.includes('STRONG MATCH') || upper.includes('STRONG-STRONG')) return { label: 'STRONG',          color: '#34d399', pct: 85 }
  if (upper.includes('MODERATE-STRONG'))                                   return { label: 'MOD-STRONG',     color: '#86efac', pct: 70 }
  if (upper.includes('MODERATE MATCH'))                                    return { label: 'MODERATE',       color: '#fbbf24', pct: 70 }
  if (upper.includes('STRETCH'))                                           return { label: 'STRETCH',        color: '#fb923c', pct: 50 }
  if (upper.includes('WEAK MATCH'))                                        return { label: 'WEAK',           color: '#f87171', pct: 25 }
  return null
}

export function extractPct(content: string): number | null {
  const m = content.match(/(\d{2,3})%/)
  return m ? parseInt(m[1]) : null
}

// ─── Shared prose components ──────────────────────────────────────────────────

export function proseComponents(accentColor: string): Components {
  return {
    h4({ children }) {
      return (
        <h4 style={{
          color: accentColor, fontFamily: 'Syne, sans-serif', fontSize: '0.65rem',
          fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
          marginTop: '1.25rem', marginBottom: '0.4rem', opacity: 0.85,
        }}>
          {children}
        </h4>
      )
    },
    p({ children }) {
      return <p style={{ color: '#b4b4b4', fontSize: '0.875rem', lineHeight: 1.75, marginBottom: '0.6rem' }}>{children}</p>
    },
    ul({ children }) {
      return <ul style={{ paddingLeft: '1.1rem', marginBottom: '0.5rem', listStyleType: 'none' }}>{children}</ul>
    },
    ol({ children }) {
      return <ol style={{ paddingLeft: '1.1rem', marginBottom: '0.5rem' }}>{children}</ol>
    },
    li({ children }) {
      return (
        <li style={{ color: '#b4b4b4', fontSize: '0.875rem', lineHeight: 1.7, marginBottom: '0.4rem', position: 'relative', paddingLeft: '0.9rem' }}>
          <span style={{ position: 'absolute', left: 0, top: '0.55em', width: '4px', height: '4px', borderRadius: '50%', background: accentColor, opacity: 0.6, display: 'block' }} />
          {children}
        </li>
      )
    },
    strong({ children }) {
      return <strong style={{ color: '#f0f0f0', fontWeight: 600 }}>{children}</strong>
    },
    em({ children }) {
      return <em style={{ color: '#6b7280', fontStyle: 'italic' }}>{children}</em>
    },
    blockquote({ children }) {
      return (
        <blockquote style={{ borderLeft: `2px solid ${accentColor}40`, paddingLeft: '0.875rem', margin: '0.5rem 0', color: '#6b7280', fontStyle: 'italic' }}>
          {children}
        </blockquote>
      )
    },
  }
}

// ─── Match Score card ─────────────────────────────────────────────────────────

export function MatchScoreSection({ content, matchScore, matchVerdict }: { content: string; matchScore?: number | null; matchVerdict?: string | null }) {
  const VERDICT_MAP: Record<string, { label: string; color: string; pct: number }> = {
    STRONG:   { label: 'STRONG',   color: '#34d399', pct: 85 },
    MODERATE: { label: 'MODERATE', color: '#fbbf24', pct: 70 },
    STRETCH:  { label: 'STRETCH',  color: '#fb923c', pct: 50 },
    WEAK:     { label: 'WEAK',     color: '#f87171', pct: 25 },
  }
  const dbVerdict = matchVerdict ? VERDICT_MAP[matchVerdict.toUpperCase()] ?? null : null
  const verdict = dbVerdict ?? detectMatchVerdict(content)
  const pct = matchScore ?? extractPct(content) ?? verdict?.pct ?? 0
  const radius = 42
  const circ = 2 * Math.PI * radius
  const dashOffset = circ - (pct / 100) * circ
  const prose = content.replace(/\*\*[^*]*MATCH[^*]*\*\*/gi, '').replace(/^🟢\s*/gm, '').trim()

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start sm:gap-6">
      <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.4rem' }}>
        <div style={{ position: 'relative', width: 100, height: 100 }}>
          <svg width="100" height="100" viewBox="0 0 100 100" style={{ transform: 'rotate(-90deg)' }}>
            <circle cx="50" cy="50" r={radius} fill="none" stroke="#1f1f1f" strokeWidth="8" />
            <circle cx="50" cy="50" r={radius} fill="none" stroke={verdict?.color ?? '#6b7280'} strokeWidth="8"
              strokeDasharray={circ} strokeDashoffset={dashOffset} strokeLinecap="round"
              style={{ transition: 'stroke-dashoffset 1s ease' }}
            />
          </svg>
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ fontFamily: 'Syne, sans-serif', fontWeight: 800, fontSize: '1.4rem', color: verdict?.color ?? '#f0f0f0', lineHeight: 1 }}>{pct}%</span>
          </div>
        </div>
        {verdict && (
          <span style={{
            fontSize: '0.6rem', fontFamily: 'JetBrains Mono, monospace', fontWeight: 700,
            letterSpacing: '0.08em', textTransform: 'uppercase', color: verdict.color,
            background: `${verdict.color}15`, border: `1px solid ${verdict.color}30`,
            borderRadius: '3px', padding: '2px 7px',
          }}>
            {verdict.label}
          </span>
        )}
      </div>
      <div style={{ flex: 1, paddingTop: '0.25rem' }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={proseComponents(verdict?.color ?? '#6b7280')}>
          {prose}
        </ReactMarkdown>
      </div>
    </div>
  )
}

// ─── Verdict card ─────────────────────────────────────────────────────────────

export function VerdictSection({ content, accentColor }: { content: string; accentColor: string }) {
  const items = content.split('\n').filter(l => l.trim()).map(line => {
    const m = line.match(/^\d+\.\s+\*\*([^*]+)\*\*(.+)/)
    return m ? { label: m[1], text: m[2].trim() } : null
  }).filter(Boolean) as { label: string; text: string }[]

  if (items.length === 0) {
    return (
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={proseComponents(accentColor)}>
        {content}
      </ReactMarkdown>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
      {items.map((item, i) => (
        <div key={i} style={{
          display: 'flex', gap: '0.75rem', padding: '0.75rem 1rem',
          background: '#0f0f0f', border: '1px solid #1a1a1a', borderRadius: '8px',
        }}>
          <span style={{ flexShrink: 0, fontFamily: 'JetBrains Mono, monospace', fontSize: '0.65rem', color: accentColor, opacity: 0.7, paddingTop: '0.15rem' }}>
            {String(i + 1).padStart(2, '0')}
          </span>
          <div>
            <div style={{ fontSize: '0.7rem', fontFamily: 'Syne, sans-serif', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: accentColor, marginBottom: '0.25rem' }}>
              {item.label}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#c0c0c0', lineHeight: 1.6 }}>{item.text}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Section card shell ───────────────────────────────────────────────────────

interface SectionCardProps {
  section: Section
  isCollapsed: boolean
  onToggle: () => void
  children: React.ReactNode
}

export function SectionCard({ section, isCollapsed, onToggle, children }: SectionCardProps) {
  const meta = getSectionMeta(section.title)
  return (
    <div
      id={section.slug}
      style={{
        borderRadius: '10px',
        border: '1px solid #1f1f1f',
        borderLeft: `3px solid ${meta.color}40`,
        background: '#0d0d0d',
        position: 'relative',
      }}
    >
      <button
        onClick={onToggle}
        style={{
          all: 'unset', cursor: 'pointer', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', width: '100%', padding: '0.75rem 1rem',
          background: isCollapsed ? '#0a0a0a' : meta.dimColor,
          borderRadius: isCollapsed ? '9px' : '9px 9px 0 0',
          borderBottom: isCollapsed ? 'none' : `1px solid ${meta.color}15`,
          transition: 'background 0.2s', boxSizing: 'border-box',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <span style={{ fontSize: '0.8rem', color: meta.color, opacity: 0.8 }}>{meta.icon}</span>
          <span style={{
            fontSize: '0.6rem', fontFamily: 'JetBrains Mono, monospace', fontWeight: 700,
            letterSpacing: '0.12em', textTransform: 'uppercase', color: meta.color,
          }}>
            {section.title}
          </span>
        </div>
        <span style={{ fontSize: '0.7rem', color: '#374151', transition: 'transform 0.2s', transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)' }}>
          ▾
        </span>
      </button>
      {!isCollapsed && (
        <div style={{ padding: '1rem 1.1rem' }}>
          {children}
        </div>
      )}
    </div>
  )
}

// ─── Requirements / Gaps section with tooltip items ──────────────────────────

type CriticalityLevel = 'dealbreaker' | 'moderate' | 'minor' | 'unknown'

const CRITICALITY_META: Record<CriticalityLevel, { icon: string; color: string; label: string }> = {
  dealbreaker: { icon: '▲', color: '#f87171', label: 'Dealbreaker' },
  moderate:    { icon: '◑', color: '#fbbf24', label: 'Addressable' },
  minor:       { icon: '○', color: '#34d399', label: 'Nice-to-have' },
  unknown:     { icon: '',  color: '#374151', label: '' },
}

function detectCriticality(text: string): CriticalityLevel {
  const t = text.toLowerCase()
  if (t.includes('dealbreaker') || t.includes('deal-breaker') || t.includes('disqualif') || t.includes('must have') || t.includes('essential') || t.includes('hard requirement')) return 'dealbreaker'
  if (t.includes('nice-to-have') || t.includes('nice to have') || t.includes('preferred') || t.includes('optional') || t.includes('not required') || t.includes('not essential') || t.includes('not critical') || t.includes('minor gap')) return 'minor'
  if (t.includes('learnable') || t.includes('addressable') || t.includes('cover letter') || t.includes('quickly') || t.includes('can be developed') || t.includes('can learn') || t.includes('mitigat') || t.includes('can be addressed')) return 'moderate'
  return 'unknown'
}

function BulletTooltipItem({ label, detail, accentColor }: { label: string; detail: string; accentColor: string }) {
  const [open, setOpen] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const hasDetail = detail.trim().length > 0

  const scheduleOpen = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setOpen(true)
  }
  const scheduleClose = () => {
    timerRef.current = setTimeout(() => setOpen(false), 130)
  }
  const cancelClose = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
  }

  return (
    <li style={{
      color: '#b4b4b4', fontSize: '0.875rem', lineHeight: 1.7,
      marginBottom: '0.4rem', position: 'relative', paddingLeft: '0.9rem',
      listStyleType: 'none',
    }}>
      <span style={{
        position: 'absolute', left: 0, top: '0.55em',
        width: '4px', height: '4px', borderRadius: '50%',
        background: accentColor, opacity: 0.6, display: 'block',
      }} />
      <span
        onMouseEnter={hasDetail ? scheduleOpen : undefined}
        onMouseLeave={hasDetail ? scheduleClose : undefined}
        onClick={hasDetail ? () => { cancelClose(); setOpen(v => !v) } : undefined}
        style={{ cursor: hasDetail ? 'pointer' : 'default', display: 'inline' }}
      >
        <strong style={{ color: '#f0f0f0', fontWeight: 600 }}>
          {label}
        </strong>
      </span>
      {open && hasDetail && (
        <div
          onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}
          style={{
            position: 'absolute',
            top: 'calc(100% + 5px)',
            left: 0,
            zIndex: 50,
            minWidth: 200,
            maxWidth: 'min(320px, calc(100vw - 3rem))',
            background: '#141414',
            border: '1px solid #2a2a2a',
            borderRadius: '8px',
            padding: '0.6rem 0.875rem',
            fontSize: '0.8rem',
            color: '#9ca3af',
            lineHeight: 1.6,
            boxShadow: '0 10px 28px rgba(0,0,0,0.65)',
          }}
        >
          {detail}
        </div>
      )}
    </li>
  )
}

function GapBulletItem({ label, criticallyText, accentColor }: { label: string; criticallyText: string; accentColor: string }) {
  const [critOpen, setCritOpen] = useState(false)
  const critTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const criticality = detectCriticality(criticallyText)
  const critMeta = CRITICALITY_META[criticality]

  const openCrit = () => { if (critTimer.current) clearTimeout(critTimer.current); setCritOpen(true) }
  const closeCrit = () => { critTimer.current = setTimeout(() => setCritOpen(false), 130) }
  const cancelCloseCrit = () => { if (critTimer.current) clearTimeout(critTimer.current) }

  return (
    <li style={{
      color: '#b4b4b4', fontSize: '0.875rem', lineHeight: 1.7,
      marginBottom: '0.15rem', position: 'relative',
      paddingLeft: critMeta.icon ? '1.3rem' : '0.9rem',
      listStyleType: 'none',
    }}>
      {critMeta.icon ? (
        <span
          onMouseEnter={criticallyText ? openCrit : undefined}
          onMouseLeave={criticallyText ? closeCrit : undefined}
          onClick={criticallyText ? () => { cancelCloseCrit(); setCritOpen(v => !v) } : undefined}
          style={{
            position: 'absolute', left: 0, top: '0.3em',
            fontSize: '0.6rem', color: critMeta.color,
            cursor: criticallyText ? 'pointer' : 'default',
            lineHeight: 1, userSelect: 'none',
          }}
        >
          {critMeta.icon}
          {critOpen && criticallyText && (
            <div
              onMouseEnter={cancelCloseCrit}
              onMouseLeave={closeCrit}
              style={{
                position: 'absolute',
                bottom: 'calc(100% + 5px)',
                left: 0,
                zIndex: 60,
                minWidth: 180,
                maxWidth: 'min(280px, calc(100vw - 3rem))',
                background: '#141414',
                border: `1px solid ${critMeta.color}40`,
                borderRadius: '7px',
                padding: '0.5rem 0.7rem',
                boxShadow: '0 4px 20px rgba(0,0,0,0.7)',
                pointerEvents: 'auto',
              }}
            >
              {critMeta.label && (
                <div style={{
                  fontSize: '0.55rem', fontFamily: 'JetBrains Mono, monospace',
                  fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
                  color: critMeta.color, marginBottom: '0.3rem',
                }}>
                  {critMeta.label}
                </div>
              )}
              <div style={{ fontSize: '0.75rem', color: '#9ca3af', lineHeight: 1.55 }}>
                {criticallyText}
              </div>
            </div>
          )}
        </span>
      ) : (
        <span style={{
          position: 'absolute', left: 0, top: '0.55em',
          width: '4px', height: '4px', borderRadius: '50%',
          background: accentColor, opacity: 0.6, display: 'block',
        }} />
      )}
      <strong style={{ color: '#f0f0f0', fontWeight: 600 }}>{label}</strong>
    </li>
  )
}

export function RequirementsGapsSection({ content, accentColor, showCriticality = false }: { content: string; accentColor: string; showCriticality?: boolean }) {
  // ── Gaps mode: separate "Critically:" from eval sub-lines ──────────────────
  if (showCriticality) {
    type GapEntry = { label: string; evalText: string; criticallyText: string; evalLines: string[] }
    const entries: GapEntry[] = []
    let cur: GapEntry | null = null

    for (const line of content.split('\n')) {
      const m = line.match(/^[-*]\s+\*\*([^*]+)\*\*(.*)$/)
      if (m) {
        if (cur) entries.push(cur)
        // evalText = inline text after the bold label (eval relative to resume)
        // criticallyText = from the *Critically:* sub-line (goes to icon tooltip)
        cur = { label: m[1].trim(), evalText: m[2].replace(/^[\s:—–\-]+/, '').trim(), criticallyText: '', evalLines: [] }
      } else if (line.trim() && cur) {
        const clean = line.trim()
          .replace(/^[-*]\s+/, '')
          .replace(/\*\*([^*]+)\*\*/g, '$1')
          .replace(/\*([^*]+)\*/g, '$1')
        if (/^Critically:/i.test(clean)) {
          cur.criticallyText = clean.replace(/^Critically:\s*/i, '')
        } else {
          cur.evalLines.push(clean)
        }
      }
    }
    if (cur) entries.push(cur)

    // Sort dealbreakers first, then moderate, then minor, then unknown
    const CRIT_ORDER: Record<CriticalityLevel, number> = { dealbreaker: 0, moderate: 1, minor: 2, unknown: 3 }
    entries.sort((a, b) =>
      CRIT_ORDER[detectCriticality(a.criticallyText || a.evalText)] -
      CRIT_ORDER[detectCriticality(b.criticallyText || b.evalText)]
    )

    if (entries.length === 0) {
      return (
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={proseComponents(accentColor)}>
          {content}
        </ReactMarkdown>
      )
    }

    return (
      <ul style={{ paddingLeft: 0, margin: 0, listStyleType: 'none' }}>
        {entries.flatMap((entry, i) => [
          // Icon uses criticallyText for detection; falls back to evalText if no explicit Critically line
          <GapBulletItem key={`g-${i}`} label={entry.label} criticallyText={entry.criticallyText || entry.evalText} accentColor={accentColor} />,
          // Inline eval text (resume evaluation) shown as visible sub-line
          ...(entry.evalText ? [
            <li key={`ev-${i}`} style={{
              color: '#6b7280', fontSize: '0.72rem', lineHeight: 1.55,
              marginBottom: '0.3rem', paddingLeft: '1.3rem', listStyleType: 'none',
            }}>
              {entry.evalText}
            </li>
          ] : []),
          // Other sub-lines (Mitigation, etc.)
          ...entry.evalLines.map((line, j) => (
            <li key={`e-${i}-${j}`} style={{
              color: '#6b7280', fontSize: '0.72rem', lineHeight: 1.55,
              marginBottom: '0.4rem', paddingLeft: '1.3rem', listStyleType: 'none',
            }}>
              {line}
            </li>
          )),
        ])}
      </ul>
    )
  }

  // ── Requirements mode: BulletTooltipItem ───────────────────────────────────
  type ParsedItem =
    | { type: 'bullet'; label: string; detail: string }
    | { type: 'other'; line: string }

  const parsed: ParsedItem[] = []
  for (const line of content.split('\n')) {
    const m = line.match(/^[-*]\s+\*\*([^*]+)\*\*(.*)$/)
    if (m) {
      parsed.push({ type: 'bullet', label: m[1].trim(), detail: m[2].replace(/^[\s:—–\-]+/, '').trim() })
    } else if (line.trim()) {
      parsed.push({ type: 'other', line: line.trim() })
    }
  }

  const hasBullets = parsed.some(p => p.type === 'bullet')
  if (!hasBullets) {
    return (
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={proseComponents(accentColor)}>
        {content}
      </ReactMarkdown>
    )
  }

  return (
    <ul style={{ paddingLeft: 0, margin: 0, listStyleType: 'none' }}>
      {parsed.map((item, i) => {
        if (item.type === 'other') {
          const clean = item.line
            .replace(/^[-*]\s+/, '')
            .replace(/\*\*([^*]+)\*\*/g, '$1')
            .replace(/\*([^*]+)\*/g, '$1')
          return (
            <li key={i} style={{
              color: '#6b7280', fontSize: '0.72rem', lineHeight: 1.55,
              marginBottom: '0.4rem', paddingLeft: '0.9rem', listStyleType: 'none',
            }}>
              {clean}
            </li>
          )
        }
        return <BulletTooltipItem key={i} label={item.label} detail={item.detail} accentColor={accentColor} />
      })}
    </ul>
  )
}

// ─── Match Score Hero Widget ──────────────────────────────────────────────────

export function MatchScoreHeroWidget({ fullEvaluation, compact = false, matchScore, matchVerdict }: { fullEvaluation: string | null; compact?: boolean; matchScore?: number | null; matchVerdict?: string | null }) {
  const [visible, setVisible] = useState(false)

  const sections = fullEvaluation ? parseSections(fullEvaluation, 'hero') : []
  const matchSec = sections.find(s => s.title.toUpperCase().includes('MATCH SCORE'))

  if (!matchSec) return null

  const content = matchSec.content

  // Use DB values when available; fall back to text parsing
  const VERDICT_MAP: Record<string, { label: string; color: string; pct: number }> = {
    STRONG:   { label: 'STRONG',   color: '#34d399', pct: 85 },
    MODERATE: { label: 'MODERATE', color: '#fbbf24', pct: 70 },
    STRETCH:  { label: 'STRETCH',  color: '#fb923c', pct: 50 },
    WEAK:     { label: 'WEAK',     color: '#f87171', pct: 25 },
  }
  const dbVerdict = matchVerdict ? VERDICT_MAP[matchVerdict.toUpperCase()] ?? null : null
  const verdict = dbVerdict ?? detectMatchVerdict(content)
  const pct = matchScore ?? extractPct(content) ?? verdict?.pct ?? 0
  const prose = content
    .replace(/\*\*[^*]*MATCH[^*]*\*\*/gi, '')
    .replace(/^🟢\s*/gm, '')
    .trim()

  const radius = 30
  const circ = 2 * Math.PI * radius
  const dashOffset = circ - (pct / 100) * circ

  return (
    <div style={{ position: 'relative', display: 'inline-flex', flexDirection: 'column', alignItems: 'center' }}>
      <button
        onClick={() => setVisible(v => !v)}
        onMouseEnter={() => setVisible(true)}
        onMouseLeave={() => setVisible(false)}
        style={{ all: 'unset', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.35rem' }}
      >
        <div style={{ position: 'relative', width: 68, height: 68 }}>
          <svg width="68" height="68" viewBox="0 0 68 68" style={{ transform: 'rotate(-90deg)' }}>
            <circle cx="34" cy="34" r={radius} fill="none" stroke="#1f1f1f" strokeWidth="5.5" />
            <circle
              cx="34" cy="34" r={radius} fill="none"
              stroke={verdict?.color ?? '#6b7280'} strokeWidth="5.5"
              strokeDasharray={circ} strokeDashoffset={dashOffset}
              strokeLinecap="round"
              style={{ transition: 'stroke-dashoffset 1s ease' }}
            />
          </svg>
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ display: 'flex', alignItems: 'baseline', gap: '1px', fontFamily: 'Syne, sans-serif', color: verdict?.color ?? '#f0f0f0', lineHeight: 1, fontVariantNumeric: 'lining-nums tabular-nums' }}>
              <span style={{ fontWeight: 800, fontSize: '1.1rem' }}>{pct}</span>
              <span style={{ fontWeight: 700, fontSize: '0.5rem', opacity: 0.8 }}>%</span>
            </span>
          </div>
        </div>
        {!compact && verdict && (
          <span style={{
            fontSize: '0.5rem', fontFamily: 'JetBrains Mono, monospace', fontWeight: 700,
            letterSpacing: '0.08em', textTransform: 'uppercase',
            color: verdict.color, background: `${verdict.color}15`,
            border: `1px solid ${verdict.color}30`, borderRadius: '3px', padding: '2px 6px',
          }}>
            {verdict.label}
          </span>
        )}
      </button>

      {visible && prose && (
        <div
          onMouseEnter={() => setVisible(true)}
          onMouseLeave={() => setVisible(false)}
          style={{
            position: 'absolute', top: '100%', right: 0, marginTop: '0.5rem',
            width: 'min(280px, calc(100vw - 2rem))', background: '#141414', border: '1px solid #2a2a2a',
            borderRadius: '10px', padding: '0.875rem 1rem', zIndex: 100,
            boxShadow: '0 8px 32px rgba(0,0,0,0.7)',
          }}
        >
          <div style={{ marginBottom: '0.5rem', fontSize: '0.5rem', fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: verdict?.color ?? '#6b7280', opacity: 0.8 }}>
            Match Assessment
          </div>
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={proseComponents(verdict?.color ?? '#6b7280')}>
            {prose}
          </ReactMarkdown>
        </div>
      )}
    </div>
  )
}

// ─── Requirements group row (3-column, whole card collapsible) ────────────────

export function RequirementsGroupRow({
  sections,
  isCollapsed,
  onToggle,
}: {
  sections: Section[]
  isCollapsed: boolean
  onToggle: () => void
}) {
  return (
    <div style={{
      borderRadius: '10px',
      border: '1px solid #1f1f1f',
      background: '#0d0d0d',
      position: 'relative',
    }}>
      <button
        onClick={onToggle}
        style={{
          all: 'unset', cursor: 'pointer', width: '100%', boxSizing: 'border-box',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0.35rem 1rem',
          background: '#090909',
          borderBottom: isCollapsed ? 'none' : '1px solid #1a1a1a',
          borderRadius: isCollapsed ? '10px' : '10px 10px 0 0',
          transition: 'background 0.2s',
        }}
      >
        <span style={{
          fontSize: '0.5rem', fontFamily: 'JetBrains Mono, monospace',
          fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase', color: '#374151',
        }}>
          Role Requirements
        </span>
        <span style={{
          fontSize: '0.65rem', color: '#374151', transition: 'transform 0.2s',
          transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
        }}>▾</span>
      </button>

      {!isCollapsed && (
        <div className="grid grid-cols-1 sm:grid-cols-3">
          {sections.map((sec, i) => {
            const meta = getSectionMeta(sec.title)
            return (
              <div
                key={sec.slug}
                id={sec.slug}
                className={i > 0 ? 'border-t sm:border-t-0 sm:border-l border-[#1a1a1a]' : ''}
                style={{ display: 'flex', flexDirection: 'column' }}
              >
                <div style={{
                  display: 'flex', alignItems: 'center', gap: '0.4rem',
                  padding: '0.55rem 0.875rem',
                  background: meta.dimColor,
                  borderBottom: `1px solid ${meta.color}15`,
                }}>
                  <span style={{ fontSize: '0.75rem', color: meta.color, opacity: 0.8 }}>{meta.icon}</span>
                  <span style={{
                    fontSize: '0.55rem', fontFamily: 'JetBrains Mono, monospace',
                    fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: meta.color,
                  }}>
                    {meta.label}
                  </span>
                </div>
                <div style={{ padding: '0.875rem' }}>
                  <RequirementsGapsSection
                    content={sec.content}
                    accentColor={meta.color}
                    showCriticality={sec.title.toUpperCase().includes('TRUE GAPS')}
                  />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─── Nav pills ────────────────────────────────────────────────────────────────

interface NavPillsProps {
  sections: Section[]
  collapsed: Set<string>
  onScrollTo: (slug: string) => void
}

export function NavPills({ sections, collapsed, onScrollTo }: NavPillsProps) {
  return (
    <div style={{
      display: 'flex', flexWrap: 'wrap', gap: '0.375rem',
      marginBottom: '1.5rem', paddingBottom: '1.25rem', borderBottom: '1px solid #1a1a1a',
    }}>
      {sections.map(sec => {
        const meta = getSectionMeta(sec.title)
        const isCollapsed = collapsed.has(sec.slug)
        return (
          <button
            key={sec.slug}
            onClick={() => onScrollTo(sec.slug)}
            style={{
              all: 'unset', cursor: 'pointer', display: 'flex', alignItems: 'center',
              gap: '0.35rem', padding: '0.3rem 0.65rem', borderRadius: '4px',
              background: '#111', border: `1px solid ${meta.color}25`,
              fontSize: '0.65rem', fontFamily: 'JetBrains Mono, monospace', fontWeight: 600,
              letterSpacing: '0.05em', color: isCollapsed ? '#4b5563' : meta.color,
              opacity: isCollapsed ? 0.5 : 1, transition: 'all 0.15s',
            }}
          >
            <span style={{ opacity: 0.8, fontSize: '0.7rem' }}>{meta.icon}</span>
            {meta.label}
          </button>
        )
      })}
    </div>
  )
}
