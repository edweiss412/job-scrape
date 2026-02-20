'use client'

import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'

const ACCENT = '#94a3b8'
const DIM = '#94a3b818'

function isHtml(text: string): boolean {
  return /<\/?(?:p|div|ul|ol|li|h[1-6]|br|table|span|a)\b/i.test(text)
}

function sanitizeHtml(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
    .replace(/<object[\s\S]*?<\/object>/gi, '')
    .replace(/<embed[\s\S]*?>/gi, '')
    .replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
    .replace(/\son\w+\s*=\s*'[^']*'/gi, '')
    .replace(/javascript\s*:/gi, '')
}

const mdComponents: Components = {
  h1({ children }) {
    return <h1 style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700, color: '#e0e0e0', fontSize: '1.05rem', margin: '1.25rem 0 0.4rem', lineHeight: 1.3 }}>{children}</h1>
  },
  h2({ children }) {
    return <h2 style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700, color: '#e0e0e0', fontSize: '0.95rem', margin: '1.25rem 0 0.4rem', lineHeight: 1.3 }}>{children}</h2>
  },
  h3({ children }) {
    return <h3 style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700, color: '#e0e0e0', fontSize: '0.875rem', margin: '1.1rem 0 0.35rem', lineHeight: 1.3 }}>{children}</h3>
  },
  h4({ children }) {
    return <h4 style={{ fontSize: '0.65rem', fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: ACCENT, opacity: 0.85, margin: '1.1rem 0 0.35rem' }}>{children}</h4>
  },
  p({ children }) {
    return <p style={{ color: '#b4b4b4', fontSize: '0.875rem', lineHeight: 1.75, marginBottom: '0.6rem' }}>{children}</p>
  },
  ul({ children }) {
    return <ul style={{ paddingLeft: '1.1rem', margin: '0.3rem 0 0.7rem', listStyleType: 'disc' }}>{children}</ul>
  },
  ol({ children }) {
    return <ol style={{ paddingLeft: '1.1rem', margin: '0.3rem 0 0.7rem' }}>{children}</ol>
  },
  li({ children }) {
    return (
      <li style={{ color: '#b4b4b4', fontSize: '0.875rem', lineHeight: 1.7, marginBottom: '0.25rem', paddingLeft: '0.2rem' }}>
        {children}
      </li>
    )
  },
  strong({ children }) {
    return <strong style={{ color: '#f0f0f0', fontWeight: 600 }}>{children}</strong>
  },
  em({ children }) {
    return <em style={{ color: '#9ca3af', fontStyle: 'italic' }}>{children}</em>
  },
  a({ children, href }) {
    return <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: '#60a5fa', textDecoration: 'none', borderBottom: '1px solid #60a5fa30' }}>{children}</a>
  },
  blockquote({ children }) {
    return <blockquote style={{ borderLeft: `2px solid ${ACCENT}40`, paddingLeft: '0.875rem', margin: '0.5rem 0', color: '#6b7280', fontStyle: 'italic' }}>{children}</blockquote>
  },
  hr() {
    return <hr style={{ border: 'none', borderTop: '1px solid #1f1f1f', margin: '1rem 0' }} />
  },
  table({ children }) {
    return <table style={{ width: '100%', borderCollapse: 'collapse', margin: '0.5rem 0 0.75rem', fontSize: '0.8rem' }}>{children}</table>
  },
  th({ children }) {
    return <th style={{ border: '1px solid #1f1f1f', padding: '0.35rem 0.6rem', textAlign: 'left', background: '#111', color: '#9ca3af', fontWeight: 600, fontSize: '0.75rem' }}>{children}</th>
  },
  td({ children }) {
    return <td style={{ border: '1px solid #1f1f1f', padding: '0.35rem 0.6rem', textAlign: 'left', color: '#b4b4b4' }}>{children}</td>
  },
  img() {
    return null
  },
}

export function JobDescription({ html }: { html: string }) {
  const [expanded, setExpanded] = useState(false)

  const useHtml = isHtml(html)

  return (
    <div
      style={{
        borderRadius: '10px',
        border: '1px solid #1f1f1f',
        borderLeft: `3px solid ${ACCENT}40`,
        background: '#0d0d0d',
        position: 'relative',
      }}
    >
      <button
        onClick={() => setExpanded(v => !v)}
        style={{
          all: 'unset',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          width: '100%',
          padding: '0.75rem 1rem',
          background: expanded ? DIM : '#0a0a0a',
          borderRadius: expanded ? '9px 9px 0 0' : '9px',
          borderBottom: expanded ? `1px solid ${ACCENT}15` : 'none',
          transition: 'background 0.2s',
          boxSizing: 'border-box',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <span style={{ fontSize: '0.8rem', color: ACCENT, opacity: 0.8 }}>≡</span>
          <span
            style={{
              fontSize: '0.6rem',
              fontFamily: 'JetBrains Mono, monospace',
              fontWeight: 700,
              letterSpacing: '0.12em',
              textTransform: 'uppercase' as const,
              color: ACCENT,
            }}
          >
            Job Description
          </span>
        </div>
        <span
          style={{
            fontSize: '0.7rem',
            color: '#374151',
            transition: 'transform 0.2s',
            transform: expanded ? 'rotate(0deg)' : 'rotate(-90deg)',
          }}
        >
          ▾
        </span>
      </button>

      {expanded && (
        useHtml ? (
          <div
            className="jd-prose"
            style={{ padding: '1rem 1.1rem' }}
            dangerouslySetInnerHTML={{ __html: sanitizeHtml(html) }}
          />
        ) : (
          <div style={{ padding: '1rem 1.1rem', overflowWrap: 'break-word', wordBreak: 'break-word' }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
              {html}
            </ReactMarkdown>
          </div>
        )
      )}

      {/* Styles only needed for HTML rendering path */}
      <style>{`
        .jd-prose {
          font-size: 0.875rem;
          line-height: 1.75;
          color: #b4b4b4;
          overflow-wrap: break-word;
          word-break: break-word;
        }
        .jd-prose > *:first-child { margin-top: 0; }
        .jd-prose > *:last-child { margin-bottom: 0; }
        .jd-prose h1, .jd-prose h2, .jd-prose h3 {
          font-family: Syne, sans-serif;
          font-weight: 700;
          color: #e0e0e0;
          margin: 1.25rem 0 0.4rem;
          line-height: 1.3;
        }
        .jd-prose h1 { font-size: 1.05rem; }
        .jd-prose h2 { font-size: 0.95rem; }
        .jd-prose h3 { font-size: 0.875rem; }
        .jd-prose h4, .jd-prose h5, .jd-prose h6 {
          font-size: 0.65rem;
          font-family: 'JetBrains Mono', monospace;
          font-weight: 700;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          color: ${ACCENT};
          opacity: 0.85;
          margin: 1.1rem 0 0.35rem;
        }
        .jd-prose p { margin: 0 0 0.6rem; }
        .jd-prose ul, .jd-prose ol {
          padding-left: 1.1rem;
          margin: 0.3rem 0 0.7rem;
        }
        .jd-prose li {
          margin-bottom: 0.25rem;
          padding-left: 0.2rem;
        }
        .jd-prose ul > li { list-style: disc; }
        .jd-prose ul > li::marker { color: #374151; }
        .jd-prose ol > li { list-style: decimal; }
        .jd-prose ol > li::marker { color: #4b5563; font-size: 0.8em; }
        .jd-prose strong, .jd-prose b { color: #f0f0f0; font-weight: 600; }
        .jd-prose em, .jd-prose i { color: #9ca3af; font-style: italic; }
        .jd-prose a {
          color: #60a5fa;
          text-decoration: none;
          border-bottom: 1px solid #60a5fa30;
        }
        .jd-prose a:hover { border-bottom-color: #60a5fa; }
        .jd-prose table {
          width: 100%;
          border-collapse: collapse;
          margin: 0.5rem 0 0.75rem;
          font-size: 0.8rem;
        }
        .jd-prose th, .jd-prose td {
          border: 1px solid #1f1f1f;
          padding: 0.35rem 0.6rem;
          text-align: left;
        }
        .jd-prose th { background: #111; color: #9ca3af; font-weight: 600; font-size: 0.75rem; }
        .jd-prose hr { border: none; border-top: 1px solid #1f1f1f; margin: 1rem 0; }
        .jd-prose blockquote {
          border-left: 2px solid ${ACCENT}40;
          padding-left: 0.875rem;
          margin: 0.5rem 0;
          color: #6b7280;
          font-style: italic;
        }
        .jd-prose img { display: none; }
        .jd-prose br + br { display: none; }
      `}</style>
    </div>
  )
}
