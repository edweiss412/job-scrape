'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import Link from 'next/link'

export interface MatchItem {
  job_id: string
  title: string
  company: string
  location: string | null
  score: number | null
  verdict: string
  summary: string | null
  saved?: boolean
}

const AUTO_PLAY_MS = 4000
const RESUME_DELAY_MS = 6000

export function TopMatchesCarousel({ matches }: { matches: MatchItem[] }) {
  const n = matches.length
  const [cols, setCols] = useState(3)
  const cloneCount = cols
  const needsCarousel = n > cols

  // Extended array: [clones of last N, ...originals, clones of first N]
  const extended = needsCarousel
    ? [...matches.slice(-cloneCount), ...matches, ...matches.slice(0, cloneCount)]
    : matches
  const startIndex = needsCarousel ? cloneCount : 0

  const [index, setIndex] = useState(startIndex)
  const [animated, setAnimated] = useState(true)
  const [dragging, setDragging] = useState(false)
  const [dragOffset, setDragOffset] = useState(0)
  const [paused, setPaused] = useState(false)
  const resumeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const dragStart = useRef(0)
  const dragCurrent = useRef(0)
  const containerRef = useRef<HTMLDivElement>(null)

  // Responsive column count
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 640px)')
    const update = () => setCols(mq.matches ? 3 : 1)
    update()
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [])

  // Reset index when cols changes
  useEffect(() => {
    setAnimated(false)
    setIndex(needsCarousel ? cols : 0)
  }, [cols, needsCarousel])

  // Re-enable animation after instant jumps
  useEffect(() => {
    if (!animated) {
      const id = requestAnimationFrame(() =>
        requestAnimationFrame(() => setAnimated(true))
      )
      return () => cancelAnimationFrame(id)
    }
  }, [animated])

  const cardPct = 100 / cols
  const translateX = -(index * cardPct) + (dragOffset / (containerRef.current?.offsetWidth ?? 1)) * 100

  const next = useCallback(() => {
    if (!needsCarousel) return
    setAnimated(true)
    setIndex(i => i + 1)
  }, [needsCarousel])

  const prev = useCallback(() => {
    if (!needsCarousel) return
    setAnimated(true)
    setIndex(i => i - 1)
  }, [needsCarousel])

  // Auto-play when not paused
  useEffect(() => {
    if (!needsCarousel || paused) return
    const id = setInterval(next, AUTO_PLAY_MS)
    return () => clearInterval(id)
  }, [needsCarousel, paused, next])

  // Pause auto-play on interaction, resume after idle period
  const pauseAutoPlay = useCallback(() => {
    setPaused(true)
    if (resumeTimer.current) clearTimeout(resumeTimer.current)
    resumeTimer.current = setTimeout(() => setPaused(false), RESUME_DELAY_MS)
  }, [])

  // Cleanup resume timer
  useEffect(() => {
    return () => { if (resumeTimer.current) clearTimeout(resumeTimer.current) }
  }, [])

  // Wrap around after transition ends
  const handleTransitionEnd = useCallback(() => {
    if (!needsCarousel) return
    if (index >= cloneCount + n) {
      setAnimated(false)
      setIndex(cloneCount)
    } else if (index < cloneCount) {
      setAnimated(false)
      setIndex(cloneCount + n - 1)
    }
  }, [index, n, cloneCount, needsCarousel])

  // Touch / pointer drag
  const onPointerDown = useCallback((e: React.PointerEvent) => {
    if (!needsCarousel) return
    pauseAutoPlay()
    setDragging(true)
    setAnimated(false)
    dragStart.current = e.clientX
    dragCurrent.current = e.clientX
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  }, [needsCarousel, pauseAutoPlay])

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging) return
    dragCurrent.current = e.clientX
    setDragOffset(dragCurrent.current - dragStart.current)
  }, [dragging])

  const onPointerUp = useCallback(() => {
    if (!dragging) return
    setDragging(false)
    const delta = dragCurrent.current - dragStart.current
    const threshold = (containerRef.current?.offsetWidth ?? 300) / cols * 0.25
    setDragOffset(0)
    setAnimated(true)
    if (delta < -threshold) next()
    else if (delta > threshold) prev()
  }, [dragging, cols, next, prev])

  // Indicator dot: which real item is "first visible"
  const realIndex = needsCarousel
    ? ((index - cloneCount) % n + n) % n
    : 0

  return (
    <div className="group/carousel relative">
      {/* Track */}
      <div
        ref={containerRef}
        className="overflow-hidden"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        style={{ touchAction: 'pan-y' }}
      >
        <div
          className={`flex ${animated ? `transition-transform ${paused ? 'duration-500 ease-out' : 'duration-[900ms] ease-in-out'}` : ''}`}
          style={{ transform: `translateX(${translateX}%)` }}
          onTransitionEnd={handleTransitionEnd}
        >
          {extended.map((match, i) => (
            <div
              key={`${match.job_id}-${i}`}
              className="w-full shrink-0 px-1.5 sm:w-1/3"
            >
              <Link
                href={`/opportunities/fulltime/${match.job_id}`}
                className="group flex h-full flex-col rounded-xl border border-border bg-[#111] p-5 transition-all hover:border-[#2a2a2a] hover:bg-surface-2"
                draggable={false}
                onClick={e => { if (Math.abs(dragCurrent.current - dragStart.current) > 5) e.preventDefault() }}
              >
                <div className="mb-3 flex items-center gap-2">
                  {match.score != null && (
                    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[10px] font-semibold ${
                      match.verdict === 'STRONG'
                        ? 'border-emerald-800 bg-emerald-950/60 text-emerald-400'
                        : 'border-amber-800 bg-amber-950/60 text-amber-400'
                    }`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${
                        match.verdict === 'STRONG' ? 'bg-emerald-400' : 'bg-amber-400'
                      }`} />
                      {match.score}
                    </span>
                  )}
                  {match.saved && (
                    <svg className="h-3.5 w-3.5 fill-blue-400 text-blue-400" viewBox="0 0 24 24">
                      <path d="M5 2h14a1 1 0 011 1v19.143a.5.5 0 01-.766.424L12 18.03l-7.234 4.536A.5.5 0 014 22.143V3a1 1 0 011-1z" />
                    </svg>
                  )}
                  {match.location && (
                    <span className="text-[11px] text-zinc-600">{match.location}</span>
                  )}
                </div>
                <h3 className="mb-1 truncate text-sm font-semibold text-white group-hover:text-zinc-100">
                  {match.title}
                </h3>
                <p className="mb-2 text-xs text-zinc-500">{match.company}</p>
                {match.summary && (
                  <p className="line-clamp-2 text-xs leading-relaxed text-zinc-600">
                    {match.summary}
                  </p>
                )}
              </Link>
            </div>
          ))}
        </div>
      </div>

      {/* Navigation arrows — visible when paused */}
      {needsCarousel && paused && (
        <>
          <button
            onClick={() => { pauseAutoPlay(); prev() }}
            className="absolute -left-3 top-1/2 z-10 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border border-zinc-800 bg-[#111] text-zinc-500 opacity-0 shadow-lg transition-all hover:border-zinc-700 hover:bg-surface-2 hover:text-white group-hover/carousel:opacity-100 sm:-left-4"
            aria-label="Previous"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <button
            onClick={() => { pauseAutoPlay(); next() }}
            className="absolute -right-3 top-1/2 z-10 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border border-zinc-800 bg-[#111] text-zinc-500 opacity-0 shadow-lg transition-all hover:border-zinc-700 hover:bg-surface-2 hover:text-white group-hover/carousel:opacity-100 sm:-right-4"
            aria-label="Next"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </>
      )}

      {/* Dot indicators — visible when paused */}
      {needsCarousel && paused && (
        <div className="mt-4 flex justify-center gap-1.5">
          {matches.map((_, i) => (
            <button
              key={i}
              onClick={() => { pauseAutoPlay(); setAnimated(true); setIndex((needsCarousel ? cloneCount : 0) + i) }}
              className={`h-1.5 rounded-full transition-all ${
                i === realIndex
                  ? 'w-4 bg-emerald-400'
                  : 'w-1.5 bg-zinc-700 hover:bg-zinc-600'
              }`}
              aria-label={`Go to match ${i + 1}`}
            />
          ))}
        </div>
      )}
    </div>
  )
}
