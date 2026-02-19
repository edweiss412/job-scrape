'use client'

import { useState } from 'react'
import { ResumeTailorOverlay } from './ResumeTailorOverlay'

interface Props {
  jobId: string
  jobTitle: string
  company: string
}

export function ResumeTailorButton({ jobId, jobTitle, company }: Props) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="rounded-lg border border-orange-900/40 bg-orange-950/20 px-4 py-2 text-xs font-medium text-orange-400 transition-all hover:bg-orange-950/40"
      >
        Tailor Resume
      </button>
      {open && (
        <ResumeTailorOverlay
          jobId={jobId}
          jobTitle={jobTitle}
          company={company}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  )
}
