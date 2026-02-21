'use client'

import { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'

export type EvalPhase =
  | 'idle'
  | 'triggering'
  | 'pending'
  | 'running'
  | 'completed'
  | 'cancelled'
  | 'cancelling'
  | 'error'

interface EvalStatusContextValue {
  status: EvalPhase
  total: number | null
  done: number | null
  elapsed: number
  errorMsg: string
  trigger: () => Promise<void>
  cancel: () => Promise<void>
  dismiss: () => void
  refresh: () => Promise<void>
}

const EvalStatusContext = createContext<EvalStatusContextValue | null>(null)

export function useEvalStatus() {
  const ctx = useContext(EvalStatusContext)
  if (!ctx) throw new Error('useEvalStatus must be used within EvalStatusProvider')
  return ctx
}

export function EvalStatusProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [status, setStatus] = useState<EvalPhase>('idle')
  const [total, setTotal] = useState<number | null>(null)
  const [done, setDone] = useState<number | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const poll = useCallback(async () => {
    try {
      const res = await fetch('/api/scan/evaluate')
      if (!res.ok) return
      const data = await res.json()
      if (data.job_count != null) setTotal(data.job_count)
      if (data.jobs_done != null) setDone(data.jobs_done)

      if (data.status === 'pending' || data.status === 'running') {
        setStatus(prev => prev === 'cancelling' ? prev : data.status)
        if (data.started_at) setStartedAt(prev => prev ?? new Date(data.started_at).getTime())
      } else if (data.status === 'completed') {
        setStatus('completed')
        router.refresh()
      } else if (data.status === 'cancelled') {
        setStatus('cancelled')
      } else if (data.status === 'error') {
        setStatus('error')
        setErrorMsg('Evaluation failed — check GitHub Actions logs.')
      }
    } catch { /* network hiccup — ignore */ }
  }, [router])

  // Initial fetch on mount
  useEffect(() => { poll() }, [poll])

  // Polling: only when status is active
  useEffect(() => {
    const isActive = status === 'pending' || status === 'running' || status === 'cancelling'
    if (!isActive) {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
      if (status !== 'completed' && status !== 'error' && status !== 'cancelled') setElapsed(0)
      return
    }

    const t0 = startedAt ?? Date.now()
    timerRef.current = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000)
    pollRef.current = setInterval(poll, 5_000)

    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    }
  }, [status, startedAt, poll])

  const trigger = useCallback(async () => {
    setStatus('triggering')
    setErrorMsg('')
    setDone(null)
    setTotal(null)
    setElapsed(0)
    try {
      const res = await fetch('/api/scan/evaluate', { method: 'POST' })
      const data = await res.json()
      if (!res.ok) {
        setStatus('error')
        setErrorMsg(data.error ?? 'Unknown error')
        return
      }
      setStartedAt(Date.now())
      setStatus('pending')
    } catch (e) {
      setStatus('error')
      setErrorMsg(String(e))
    }
  }, [])

  const cancel = useCallback(async () => {
    setStatus('cancelling')
    try {
      await fetch('/api/scan/evaluate/cancel', { method: 'POST' })
    } catch { /* keep polling — status will update from server */ }
  }, [])

  const dismiss = useCallback(() => {
    setStatus('idle')
    setElapsed(0)
    setDone(null)
    setTotal(null)
    setErrorMsg('')
    router.refresh()
  }, [router])

  const refresh = useCallback(async () => { await poll() }, [poll])

  return (
    <EvalStatusContext.Provider value={{ status, total, done, elapsed, errorMsg, trigger, cancel, dismiss, refresh }}>
      {children}
    </EvalStatusContext.Provider>
  )
}
