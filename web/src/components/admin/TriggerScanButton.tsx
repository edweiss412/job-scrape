'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { ADMIN_EMAIL } from '@/lib/admin'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'

type ScanPhase =
  | { phase: 'idle' }
  | { phase: 'inputs' }
  | { phase: 'triggering' }
  | { phase: 'polling'; workflowUrl: string | null }
  | { phase: 'done'; success: boolean; workflowUrl: string | null }
  | { phase: 'error'; message: string }

interface FreelanceInputs {
  category: string
  max_companies: number
  no_verify: boolean
}

const FREELANCE_CATEGORIES = [
  { value: '', label: 'All categories' },
  { value: 'av_rental', label: 'AV Rental' },
  { value: 'production_co', label: 'Production Co' },
  { value: 'venue', label: 'Venue' },
  { value: 'touring', label: 'Touring' },
  { value: 'corporate_av', label: 'Corporate AV' },
  { value: 'university', label: 'University' },
]

export function TriggerScanButton({ type }: { type: 'fulltime' | 'freelance' }) {
  const router = useRouter()
  const [isAdmin, setIsAdmin] = useState(false)
  const [scanPhase, setScanPhase] = useState<ScanPhase>({ phase: 'idle' })
  const [pollStartedAt, setPollStartedAt] = useState<number | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [freelanceInputs, setFreelanceInputs] = useState<FreelanceInputs>({
    category: '',
    max_companies: 100,
    no_verify: false,
  })

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const elapsedIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Admin check + concurrent run detection on mount
  useEffect(() => {
    createClient()
      .auth.getUser()
      .then(async ({ data }) => {
        if (data.user?.email !== ADMIN_EMAIL) return
        setIsAdmin(true)

        // Check if a scan is already running
        const res = await fetch(`/api/scan/status?type=${type}`)
        if (!res.ok) return
        const status = await res.json()
        if (status.status === 'queued' || status.status === 'in_progress') {
          setScanPhase({ phase: 'polling', workflowUrl: status.workflow_url ?? null })
          setPollStartedAt(Date.now())
        }
      })
  }, [type])

  // Polling interval
  useEffect(() => {
    if (scanPhase.phase !== 'polling') {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
        pollIntervalRef.current = null
      }
      return
    }

    async function poll() {
      const res = await fetch(`/api/scan/status?type=${type}`)
      if (!res.ok) return
      const data = await res.json()
      if (data.status === 'completed') {
        setScanPhase({ phase: 'done', success: true, workflowUrl: data.workflow_url ?? null })
      } else if (data.status === 'error') {
        setScanPhase({ phase: 'done', success: false, workflowUrl: data.workflow_url ?? null })
      }
      // queued / in_progress: keep polling
    }

    pollIntervalRef.current = setInterval(poll, 10_000)
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
    }
  }, [scanPhase.phase, type])

  // Elapsed timer
  useEffect(() => {
    if (scanPhase.phase !== 'polling' || !pollStartedAt) {
      if (elapsedIntervalRef.current) {
        clearInterval(elapsedIntervalRef.current)
        elapsedIntervalRef.current = null
      }
      setElapsed(0)
      return
    }

    elapsedIntervalRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - pollStartedAt) / 1000))
    }, 1000)

    return () => {
      if (elapsedIntervalRef.current) clearInterval(elapsedIntervalRef.current)
    }
  }, [scanPhase.phase, pollStartedAt])

  async function triggerScan() {
    setScanPhase({ phase: 'triggering' })

    const body: Record<string, unknown> = { type }
    if (type === 'freelance') {
      if (freelanceInputs.category) body.category = freelanceInputs.category
      body.max_companies = freelanceInputs.max_companies
      if (freelanceInputs.no_verify) body.no_verify = true
    }

    const res = await fetch('/api/scan/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      setScanPhase({ phase: 'error', message: data.error ?? 'Unknown error' })
      return
    }

    setPollStartedAt(Date.now())
    setScanPhase({ phase: 'polling', workflowUrl: null })
  }

  function handleTriggerClick() {
    if (type === 'freelance') {
      setScanPhase({ phase: 'inputs' })
    } else {
      triggerScan()
    }
  }

  function formatElapsed(s: number) {
    const m = Math.floor(s / 60)
    const sec = s % 60
    return `${m}:${String(sec).padStart(2, '0')}`
  }

  if (!isAdmin) return null

  const isActive = scanPhase.phase !== 'idle' && scanPhase.phase !== 'inputs'

  return (
    <div className="flex flex-col gap-2">
      {/* Trigger button */}
      <Button
        variant="secondary"
        size="sm"
        onClick={handleTriggerClick}
        disabled={isActive}
      >
        {isActive ? (
          <>
            <Spinner className="h-3 w-3" />
            Run Scan
          </>
        ) : (
          'Run Scan'
        )}
      </Button>

      {/* Freelance inputs panel */}
      {scanPhase.phase === 'inputs' && (
        <div className="rounded-xl border border-[#252525] bg-[#0e0e0e] p-4 shadow-xl w-72">
          <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-zinc-500">Freelance scan options</p>

          <div className="space-y-3">
            {/* Category */}
            <div>
              <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">
                Category
              </label>
              <select
                value={freelanceInputs.category}
                onChange={(e) => setFreelanceInputs((f) => ({ ...f, category: e.target.value }))}
                className="w-full rounded-lg border border-[#2a2a2a] bg-[#111] px-3 py-1.5 text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
              >
                {FREELANCE_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </div>

            {/* Max companies */}
            <div>
              <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">
                Max companies
              </label>
              <input
                type="number"
                min={1}
                max={500}
                value={freelanceInputs.max_companies}
                onChange={(e) => setFreelanceInputs((f) => ({ ...f, max_companies: Number(e.target.value) }))}
                className="w-full rounded-lg border border-[#2a2a2a] bg-[#111] px-3 py-1.5 text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
              />
            </div>

            {/* Skip verification toggle */}
            <div className="flex items-center justify-between">
              <label className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">
                Skip verification
              </label>
              <button
                type="button"
                onClick={() => setFreelanceInputs((f) => ({ ...f, no_verify: !f.no_verify }))}
                className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[10px] transition-all ${
                  freelanceInputs.no_verify
                    ? 'border-emerald-900/50 bg-emerald-950/20 text-emerald-500'
                    : 'border-[#2a2a2a] text-zinc-600 hover:border-[#333] hover:text-zinc-400'
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full transition-colors ${freelanceInputs.no_verify ? 'bg-emerald-500' : 'bg-zinc-700'}`} />
                {freelanceInputs.no_verify ? 'skipped' : 'verify'}
              </button>
            </div>
          </div>

          <div className="mt-4 flex items-center gap-3">
            <button
              onClick={triggerScan}
              className="flex-1 rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-black transition-opacity hover:opacity-90"
            >
              Start Scan
            </button>
            <button
              onClick={() => setScanPhase({ phase: 'idle' })}
              className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Status bar */}
      {scanPhase.phase === 'triggering' && (
        <div className="flex items-center gap-2 rounded-lg border border-[#252525] bg-[#0e0e0e] px-3 py-2">
          <Spinner className="h-3 w-3 text-zinc-500" />
          <span className="font-mono text-[10px] text-zinc-500">Starting scan…</span>
        </div>
      )}

      {scanPhase.phase === 'polling' && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-900/30 bg-amber-950/10 px-3 py-2">
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-500 opacity-40" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
          </span>
          <span className="font-mono text-[10px] text-amber-500">
            Running for {formatElapsed(elapsed)}
          </span>
          {scanPhase.workflowUrl && (
            <a
              href={scanPhase.workflowUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-auto font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
            >
              view logs ↗
            </a>
          )}
        </div>
      )}

      {scanPhase.phase === 'done' && scanPhase.success && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-900/30 bg-emerald-950/10 px-3 py-2">
          <svg className="h-3 w-3 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          <span className="font-mono text-[10px] text-emerald-500">Scan complete</span>
          <button
            onClick={() => {
              setScanPhase({ phase: 'idle' })
              router.refresh()
            }}
            className="ml-auto font-mono text-[10px] text-zinc-400 transition-colors hover:text-white"
          >
            Refresh →
          </button>
        </div>
      )}

      {scanPhase.phase === 'done' && !scanPhase.success && (
        <div className="flex items-center gap-2 rounded-lg border border-red-900/30 bg-red-950/10 px-3 py-2">
          <span className="font-mono text-[10px] text-red-400">Scan failed</span>
          {scanPhase.workflowUrl && (
            <a
              href={scanPhase.workflowUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
            >
              view logs ↗
            </a>
          )}
          <button
            onClick={() => setScanPhase({ phase: 'idle' })}
            className="ml-auto font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
          >
            dismiss
          </button>
        </div>
      )}

      {scanPhase.phase === 'error' && (
        <div className="flex items-center gap-2 rounded-lg border border-red-900/30 bg-red-950/10 px-3 py-2">
          <span className="font-mono text-[10px] text-red-400">
            Could not start scan: {scanPhase.message}
          </span>
          <button
            onClick={() => setScanPhase({ phase: 'idle' })}
            className="ml-auto font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
          >
            dismiss
          </button>
        </div>
      )}
    </div>
  )
}
