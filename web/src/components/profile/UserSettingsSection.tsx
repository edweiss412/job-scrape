'use client'

import { useState, useEffect } from 'react'
import { UserProfile } from '@/lib/types'
import { Spinner } from '@/components/ui/spinner'
import { TagInput } from '@/components/ui/TagInput'
import { EvaluateForUserButton } from '@/components/jobs/EvaluateForUserButton'
import { cn } from '@/lib/utils'

export function UserSettingsSection({ wrapper = true }: { wrapper?: boolean }) {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [evalFieldsChanged, setEvalFieldsChanged] = useState(false)
  const [contactOpen, setContactOpen] = useState(false)

  // Editable fields
  const [candidateContext, setCandidateContext] = useState('')
  const [targetRoles, setTargetRoles] = useState<string[]>([])
  const [targetLocations, setTargetLocations] = useState<string[]>([])
  const [homeCity, setHomeCity] = useState('')
  const [currentIncome, setCurrentIncome] = useState('')
  const [notifyEmail, setNotifyEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [phone, setPhone] = useState('')
  const [linkedinUrl, setLinkedinUrl] = useState('')
  const [professionalTitle, setProfessionalTitle] = useState('')

  useEffect(() => {
    fetch('/api/user-profile')
      .then((r) => r.json())
      .then((data: UserProfile) => {
        setProfile(data)
        setCandidateContext(data.candidate_context ?? '')
        setTargetRoles(data.target_roles ?? [])
        setTargetLocations(data.target_locations ?? [])
        setHomeCity(data.home_city ?? '')
        setCurrentIncome(data.current_income != null ? String(data.current_income) : '')
        setNotifyEmail(data.notify_email ?? '')
        setFullName(data.full_name ?? '')
        setPhone(data.phone ?? '')
        setLinkedinUrl(data.linkedin_url ?? '')
        setProfessionalTitle(data.professional_title ?? '')
        // Collapse contact section for returning users who already have some contact fields filled
        const hasContact = !!(data.full_name || data.phone || data.linkedin_url || data.professional_title || data.notify_email)
        setContactOpen(!hasContact)
      })
      .finally(() => setLoading(false))
  }, [])

  const save = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const evalChanged = profile !== null && (
        candidateContext !== (profile.candidate_context ?? '') ||
        JSON.stringify(targetRoles) !== JSON.stringify(profile.target_roles) ||
        JSON.stringify(targetLocations) !== JSON.stringify(profile.target_locations) ||
        homeCity !== (profile.home_city ?? '') ||
        currentIncome !== (profile.current_income != null ? String(profile.current_income) : '')
      )

      await fetch('/api/user-profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          candidate_context: candidateContext.trim() || null,
          target_roles: targetRoles,
          target_locations: targetLocations,
          home_city: homeCity.trim() || null,
          current_income: currentIncome ? Number(currentIncome) : null,
          notify_email: notifyEmail.trim() || null,
          full_name: fullName.trim() || null,
          phone: phone.trim() || null,
          linkedin_url: linkedinUrl.trim() || null,
          professional_title: professionalTitle.trim() || null,
        }),
      })

      setProfile((prev) => prev ? {
        ...prev,
        candidate_context: candidateContext.trim() || null,
        target_roles: targetRoles,
        target_locations: targetLocations,
        home_city: homeCity.trim() || null,
        current_income: currentIncome ? Number(currentIncome) : null,
        notify_email: notifyEmail.trim() || null,
        full_name: fullName.trim() || null,
        phone: phone.trim() || null,
        linkedin_url: linkedinUrl.trim() || null,
        professional_title: professionalTitle.trim() || null,
      } : prev)

      if (evalChanged) setEvalFieldsChanged(true)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } finally {
      setSaving(false)
    }
  }

  const isDirty = profile !== null && (
    candidateContext !== (profile.candidate_context ?? '') ||
    notifyEmail !== (profile.notify_email ?? '') ||
    homeCity !== (profile.home_city ?? '') ||
    currentIncome !== (profile.current_income != null ? String(profile.current_income) : '') ||
    JSON.stringify(targetRoles) !== JSON.stringify(profile.target_roles) ||
    JSON.stringify(targetLocations) !== JSON.stringify(profile.target_locations) ||
    fullName !== (profile.full_name ?? '') ||
    phone !== (profile.phone ?? '') ||
    linkedinUrl !== (profile.linkedin_url ?? '') ||
    professionalTitle !== (profile.professional_title ?? '')
  )

  const inputClass = "w-full rounded-lg border border-[#2a2a2a] bg-background px-3 py-2.5 text-xs text-white placeholder:text-zinc-700 outline-none focus:border-zinc-700 transition-colors"

  const innerContent = loading ? (
    <div className="flex justify-center py-12">
      <Spinner className="h-5 w-5" />
    </div>
  ) : (
    <div className="p-6 space-y-8">

      {/* ── Section: Match Preferences ─────────────────────────────────── */}
      <div>
        <div className="mb-5 border-b border-[#1a1a1a] pb-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-300">Match Preferences</h3>
          <p className="mt-0.5 text-[11px] text-zinc-600">These settings directly affect how the AI scores and ranks jobs for you.</p>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
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
              className="w-full rounded-lg border border-[#2a2a2a] bg-background px-3 py-2.5 text-xs text-white placeholder:text-zinc-700 outline-none focus:border-zinc-700 transition-colors resize-none font-mono"
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

          {/* Home city */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-zinc-400">
              Home city
              <span className="ml-2 font-normal text-zinc-700">— cost-of-living baseline for relocation math</span>
            </label>
            <input
              type="text"
              value={homeCity}
              onChange={(e) => setHomeCity(e.target.value)}
              placeholder="Chicago, IL"
              className={inputClass}
            />
          </div>

          {/* Current income */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-zinc-400">
              Current income
              <span className="ml-2 font-normal text-zinc-700">— annual, used to calculate relocation net gain</span>
            </label>
            <div className="relative">
              <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-xs text-zinc-600">$</span>
              <input
                type="number"
                value={currentIncome}
                onChange={(e) => setCurrentIncome(e.target.value)}
                placeholder="85000"
                min={0}
                step={1000}
                className="w-full rounded-lg border border-[#2a2a2a] bg-background pl-6 pr-3 py-2.5 text-xs text-white placeholder:text-zinc-700 outline-none focus:border-zinc-700 transition-colors"
              />
            </div>
          </div>

          {/* Relocation math nudge — inline after home city / income */}
          {(!homeCity.trim() || !currentIncome) && (
            <div className="lg:col-span-2 flex items-start gap-3 rounded-lg border border-zinc-800/60 bg-zinc-900/30 px-4 py-3">
              <svg className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p className="text-xs text-zinc-500 leading-relaxed">
                Set your <span className="text-zinc-300">home city</span> and{' '}
                <span className="text-zinc-300">current income</span> above to unlock relocation math —
                the evaluator will calculate net financial gain, compare cost-of-living, and flag
                QOL trade-offs for every out-of-city role.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ── Section: Contact & Outreach ────────────────────────────────── */}
      <div>
        <button
          onClick={() => setContactOpen(prev => !prev)}
          className="mb-3 flex w-full items-center justify-between border-b border-[#1a1a1a] pb-3 text-left"
        >
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-300">Contact & Outreach</h3>
            <p className="mt-0.5 text-[11px] text-zinc-600">Used for freelance outreach emails and notifications. Changes rarely.</p>
          </div>
          <svg
            className={cn('h-4 w-4 shrink-0 text-zinc-600 transition-transform', contactOpen && 'rotate-180')}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {contactOpen && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Full name */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                Full name
              </label>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Jane Doe"
                className={inputClass}
              />
            </div>

            {/* Professional title */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                Professional title
              </label>
              <input
                type="text"
                value={professionalTitle}
                onChange={(e) => setProfessionalTitle(e.target.value)}
                placeholder="A1 / RF Coordinator"
                className={inputClass}
              />
            </div>

            {/* Phone */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                Phone
              </label>
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="555-123-4567"
                className={inputClass}
              />
            </div>

            {/* LinkedIn */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                LinkedIn
              </label>
              <input
                type="text"
                value={linkedinUrl}
                onChange={(e) => setLinkedinUrl(e.target.value)}
                placeholder="linkedin.com/in/janedoe"
                className={inputClass}
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
                className={inputClass}
              />
            </div>
          </div>
        )}
      </div>

      {/* Save button */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
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

        {/* Re-eval prompt after eval-relevant settings change */}
        {evalFieldsChanged && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-amber-900/30 bg-amber-950/10 px-4 py-3">
            <div className="flex-1 min-w-0">
              <p className="text-xs text-amber-400">Preferences updated</p>
              <p className="mt-0.5 text-xs text-amber-700">
                Re-evaluate jobs to update scores based on your new preferences.
              </p>
            </div>
            <EvaluateForUserButton />
          </div>
        )}
      </div>
    </div>
  )

  if (!wrapper) return innerContent

  return (
    <div className="mt-6 rounded-xl border border-border bg-[#111]">
      <div className="flex items-center justify-between border-b border-[#1a1a1a] px-6 py-4">
        <div>
          <h2 className="text-sm font-semibold text-white">Scan preferences</h2>
          <p className="mt-0.5 text-xs text-zinc-600">
            Personalise how the scraper evaluates jobs against your profile.
          </p>
        </div>
        {loading && <Spinner className="h-4 w-4 text-zinc-700" />}
      </div>
      {innerContent}
    </div>
  )
}
