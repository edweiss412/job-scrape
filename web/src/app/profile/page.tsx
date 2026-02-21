'use client'

import { useState, useEffect, useCallback } from 'react'
import { Nav } from '@/components/layout/nav'
import { ResumeUploader } from '@/components/profile/ResumeUploader'
import { ResumeList } from '@/components/profile/ResumeList'
import { InterviewQASection } from '@/components/profile/InterviewQASection'
import { UserSettingsSection } from '@/components/profile/UserSettingsSection'
import { EvaluateForUserButton } from '@/components/jobs/EvaluateForUserButton'
import { Resume } from '@/lib/types'
import { Spinner } from '@/components/ui/spinner'
import { CollapsibleSection } from '@/components/ui/CollapsibleSection'
import { TagInput } from '@/components/ui/TagInput'

// Re-export TagInput so any existing imports still work
export { TagInput }

export default function ProfilePage() {
  const [resumes, setResumes] = useState<Resume[]>([])
  const [loading, setLoading] = useState(true)
  const [evalQueued, setEvalQueued] = useState(false)

  const fetchResumes = useCallback(async () => {
    setLoading(true)
    const res = await fetch('/api/resumes')
    const data = await res.json()
    setResumes(Array.isArray(data) ? data : [])
    setLoading(false)
  }, [])

  useEffect(() => { fetchResumes() }, [fetchResumes])

  const primary = resumes.find((r) => r.is_primary)
  const isOnboarding = resumes.length === 0 && !loading

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
            {isOnboarding
              ? 'Upload your resume to get started with personalised job scoring.'
              : 'Manage your resumes and scan preferences.'}
          </p>
        </div>

        {isOnboarding ? (
          /* ── Onboarding layout: single column, resume uploader prominent ── */
          <div className="flex flex-col gap-6 max-w-2xl">
            {/* Upload section — prominent */}
            <div className="rounded-xl border border-border bg-[#111] p-6">
              <h2 className="mb-4 text-sm font-semibold text-white">Upload resume</h2>
              <ResumeUploader
                onSuccess={fetchResumes}
                isFirstResume
                onEvalTriggered={() => setEvalQueued(true)}
              />
            </div>

            {/* Auto-triggered eval callout */}
            {evalQueued && (
              <div className="rounded-xl border border-amber-900/30 bg-amber-950/10 p-4">
                <p className="mb-3 text-xs text-amber-400/80">
                  Evaluating existing jobs against your new resume…
                </p>
                <EvaluateForUserButton />
              </div>
            )}

            {/* Interview Q&A — collapsed for onboarding */}
            <CollapsibleSection
              title="Interview Q&A"
              subtitle="Prepare answers to common interview questions"
              defaultOpen={false}
              badge="optional"
            >
              <div className="p-6">
                <InterviewQASection resumes={resumes} />
              </div>
            </CollapsibleSection>

            {/* Scan preferences — collapsed for onboarding */}
            <CollapsibleSection
              title="Scan preferences"
              subtitle="Personalise how the scraper evaluates jobs against your profile"
              defaultOpen={false}
              badge="optional"
            >
              <UserSettingsSection wrapper={false} />
            </CollapsibleSection>
          </div>
        ) : (
          /* ── Returning user layout: Settings first, then Resumes, then Q&A ── */
          <>
            {/* Settings — full width at top (most actionable) */}
            <UserSettingsSection />

            <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
              {/* Left column: resume management */}
              <div className="flex flex-col gap-6 lg:self-start lg:sticky lg:top-8">
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
                <div className="rounded-xl border border-border bg-[#111] p-6">
                  <h2 className="mb-4 text-sm font-semibold text-white">Upload resume</h2>
                  <ResumeUploader
                    onSuccess={fetchResumes}
                    isFirstResume={resumes.length === 0}
                    onEvalTriggered={() => setEvalQueued(true)}
                  />
                </div>

                {/* Auto-triggered eval callout */}
                {evalQueued && (
                  <div className="rounded-xl border border-amber-900/30 bg-amber-950/10 p-4">
                    <p className="mb-3 text-xs text-amber-400/80">
                      Evaluating existing jobs against your new resume…
                    </p>
                    <EvaluateForUserButton />
                  </div>
                )}

                {/* Resume list */}
                <div className="rounded-xl border border-border bg-[#111] p-6">
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
              <div className="rounded-xl border border-border bg-[#111] p-6">
                <InterviewQASection resumes={resumes} />
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  )
}
