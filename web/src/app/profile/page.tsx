'use client'

import { useState, useEffect, useCallback } from 'react'
import { Nav } from '@/components/layout/nav'
import { ResumeUploader } from '@/components/profile/ResumeUploader'
import { ResumeList } from '@/components/profile/ResumeList'
import { InterviewQASection } from '@/components/profile/InterviewQASection'
import { Resume } from '@/lib/types'
import { Spinner } from '@/components/ui/spinner'

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
            Manage your resumes. The primary resume is used by the scraper for LLM evaluation.
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
      </main>
    </div>
  )
}
