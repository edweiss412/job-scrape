'use client'

import { useState, useEffect, useCallback, useRef, KeyboardEvent } from 'react'
import { Nav } from '@/components/layout/nav'
import { ResumeUploader } from '@/components/profile/ResumeUploader'
import { ResumeList } from '@/components/profile/ResumeList'
import { InterviewQASection } from '@/components/profile/InterviewQASection'
import { Resume, UserProfile } from '@/lib/types'
import { Spinner } from '@/components/ui/spinner'

// ── Tag chip input ────────────────────────────────────────────────────────────
function TagInput({
  tags,
  onChange,
  placeholder,
}: {
  tags: string[]
  onChange: (tags: string[]) => void
  placeholder?: string
}) {
  const [inputVal, setInputVal] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const add = (raw: string) => {
    const value = raw.trim()
    if (value && !tags.includes(value)) {
      onChange([...tags, value])
    }
    setInputVal('')
  }

  const remove = (tag: string) => onChange(tags.filter((t) => t !== tag))

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      add(inputVal)
    } else if (e.key === 'Backspace' && !inputVal && tags.length) {
      remove(tags[tags.length - 1])
    }
  }

  return (
    <div
      className="flex flex-wrap gap-1.5 rounded-lg border border-[#2a2a2a] bg-[#0a0a0a] px-3 py-2 cursor-text min-h-[42px]"
      onClick={() => inputRef.current?.focus()}
    >
      {tags.map((tag) => (
        <span
          key={tag}
          className="inline-flex items-center gap-1 rounded border border-emerald-900/40 bg-emerald-950/30 px-2 py-0.5 text-xs text-emerald-400"
        >
          {tag}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); remove(tag) }}
            className="ml-0.5 text-emerald-600 hover:text-emerald-300 transition-colors leading-none"
            aria-label={`Remove ${tag}`}
          >
            ×
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        value={inputVal}
        onChange={(e) => setInputVal(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => { if (inputVal.trim()) add(inputVal) }}
        placeholder={tags.length === 0 ? placeholder : ''}
        className="flex-1 min-w-[120px] bg-transparent text-xs text-white outline-none placeholder:text-zinc-700"
      />
    </div>
  )
}

// ── User settings section ─────────────────────────────────────────────────────
function UserSettingsSection() {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  // Editable fields
  const [candidateContext, setCandidateContext] = useState('')
  const [targetRoles, setTargetRoles] = useState<string[]>([])
  const [targetLocations, setTargetLocations] = useState<string[]>([])
  const [notifyEmail, setNotifyEmail] = useState('')

  useEffect(() => {
    fetch('/api/user-profile')
      .then((r) => r.json())
      .then((data: UserProfile) => {
        setProfile(data)
        setCandidateContext(data.candidate_context ?? '')
        setTargetRoles(data.target_roles ?? [])
        setTargetLocations(data.target_locations ?? [])
        setNotifyEmail(data.notify_email ?? '')
      })
      .finally(() => setLoading(false))
  }, [])

  const save = async () => {
    setSaving(true)
    setSaved(false)
    try {
      await fetch('/api/user-profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          candidate_context: candidateContext.trim() || null,
          target_roles: targetRoles,
          target_locations: targetLocations,
          notify_email: notifyEmail.trim() || null,
        }),
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } finally {
      setSaving(false)
    }
  }

  const isDirty = profile !== null && (
    candidateContext !== (profile.candidate_context ?? '') ||
    notifyEmail !== (profile.notify_email ?? '') ||
    JSON.stringify(targetRoles) !== JSON.stringify(profile.target_roles) ||
    JSON.stringify(targetLocations) !== JSON.stringify(profile.target_locations)
  )

  return (
    <div className="mt-6 rounded-xl border border-[#1f1f1f] bg-[#111]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#1a1a1a] px-6 py-4">
        <div>
          <h2 className="text-sm font-semibold text-white">Scan preferences</h2>
          <p className="mt-0.5 text-xs text-zinc-600">
            Personalise how the scraper evaluates jobs against your profile.
          </p>
        </div>
        {loading && <Spinner className="h-4 w-4 text-zinc-700" />}
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <Spinner className="h-5 w-5" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 p-6 lg:grid-cols-2">
          {/* Candidate context */}
          <div className="lg:col-span-2">
            <label className="mb-1 block text-xs font-medium text-zinc-400">
              Career context
            </label>
            <p className="mb-2.5 text-xs text-zinc-600 leading-relaxed">
              Sent verbatim to the AI evaluator before each job is scored. The more specific you are,
              the better it can surface matches and flag mismatches.
            </p>
            <textarea
              value={candidateContext}
              onChange={(e) => setCandidateContext(e.target.value)}
              rows={5}
              placeholder={[
                'Targeting $90k+ base. Open to relocation to NYC or LA — not Chicago suburbs.',
                'Prefer hybrid or in-office; fully remote only for senior IC roles.',
                'No interest in pure touring/road positions.',
                'Strong on Yamaha/DiGiCo consoles; less experienced with Avid S6L.',
                'Pursuing CTS certification; available Q3 2025.',
              ].join('\n')}
              className="w-full rounded-lg border border-[#2a2a2a] bg-[#0a0a0a] px-3 py-2.5 text-xs text-white placeholder:text-zinc-700 outline-none focus:border-zinc-700 transition-colors resize-none font-mono"
            />
            {/* Example chips */}
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="text-[10px] text-zinc-700 self-center mr-0.5">Add example:</span>
              {([
                ['Salary floor', 'Targeting $90k+ base salary.'],
                ['Relocation', 'Open to relocating to NYC or LA; not interested in suburban roles.'],
                ['Work style', 'Prefer hybrid or in-office; remote only for senior roles.'],
                ['Deal-breaker', 'No touring / road positions.'],
                ['Gear gap', 'Experienced on Yamaha & DiGiCo; still building Avid S6L hours.'],
                ['Timeline', 'Available to start Q3 2025.'],
              ] as [string, string][]).map(([label, text]) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => setCandidateContext((prev) =>
                    prev.trim() ? `${prev.trim()}\n${text}` : text
                  )}
                  className="rounded border border-zinc-800 bg-zinc-900/60 px-2 py-0.5 text-[10px] text-zinc-500 transition-colors hover:border-zinc-700 hover:text-zinc-300"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Target roles */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-zinc-400">
              Target roles
              <span className="ml-2 font-normal text-zinc-700">— press Enter or comma to add</span>
            </label>
            <TagInput
              tags={targetRoles}
              onChange={setTargetRoles}
              placeholder="audio engineer, av technician…"
            />
          </div>

          {/* Target locations */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-zinc-400">
              Target locations
              <span className="ml-2 font-normal text-zinc-700">— press Enter or comma to add</span>
            </label>
            <TagInput
              tags={targetLocations}
              onChange={setTargetLocations}
              placeholder="Chicago, IL, Remote…"
            />
          </div>

          {/* Notify email */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-zinc-400">
              Digest email
              <span className="ml-2 font-normal text-zinc-700">— receives scheduled scan results</span>
            </label>
            <input
              type="email"
              value={notifyEmail}
              onChange={(e) => setNotifyEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full rounded-lg border border-[#2a2a2a] bg-[#0a0a0a] px-3 py-2.5 text-xs text-white placeholder:text-zinc-700 outline-none focus:border-zinc-700 transition-colors"
            />
          </div>

          {/* Save button */}
          <div className="flex items-center gap-3 lg:col-span-2">
            <button
              onClick={save}
              disabled={saving || !isDirty}
              className="rounded-lg border border-emerald-900/50 bg-emerald-950/30 px-5 py-2 text-xs font-medium text-emerald-400 transition-all hover:bg-emerald-950/50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {saving ? 'Saving…' : 'Save preferences'}
            </button>
            {saved && (
              <span className="flex items-center gap-1.5 text-xs text-emerald-500">
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Saved
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function ProfilePage() {
  const [resumes, setResumes] = useState<Resume[]>([])
  const [loading, setLoading] = useState(true)

  const fetchResumes = useCallback(async () => {
    setLoading(true)
    const res = await fetch('/api/resumes')
    const data = await res.json()
    setResumes(Array.isArray(data) ? data : [])
    setLoading(false)
  }, [])

  useEffect(() => { fetchResumes() }, [fetchResumes])

  const primary = resumes.find((r) => r.is_primary)

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-7xl px-4 py-8">
        <div className="mb-8">
          <h1
            className="text-xl font-bold text-white"
            style={{ fontFamily: 'Syne, sans-serif' }}
          >
            Profile
          </h1>
          <p className="mt-1 text-sm text-zinc-600">
            Manage your resumes and scan preferences.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          {/* Left column: resume management */}
          <div className="flex flex-col gap-6">
            {/* Active resume callout */}
            {primary && (
              <div className="rounded-xl border border-emerald-900/40 bg-emerald-950/20 p-4">
                <div className="flex items-center gap-2 text-xs font-mono text-emerald-500 mb-1 uppercase tracking-wider">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  Active resume
                </div>
                <p className="text-sm font-medium text-white">{primary.name}</p>
                <p className="mt-0.5 text-xs text-zinc-600">{primary.file_name}</p>
              </div>
            )}

            {/* Upload section */}
            <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-6">
              <h2 className="mb-4 text-sm font-semibold text-white">Upload resume</h2>
              <ResumeUploader onSuccess={fetchResumes} />
            </div>

            {/* Resume list */}
            <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-6">
              <h2 className="mb-2 text-sm font-semibold text-white">
                Your resumes{' '}
                <span className="text-zinc-600 font-normal">({resumes.length})</span>
              </h2>
              {loading ? (
                <div className="flex justify-center py-8">
                  <Spinner className="h-5 w-5" />
                </div>
              ) : (
                <ResumeList resumes={resumes} onRefresh={fetchResumes} />
              )}
            </div>
          </div>

          {/* Right column: Interview Q&A */}
          <div className="rounded-xl border border-[#1f1f1f] bg-[#111] p-6">
            <InterviewQASection resumes={resumes} />
          </div>
        </div>

        {/* User settings — full width below the grid */}
        <UserSettingsSection />
      </main>
    </div>
  )
}
