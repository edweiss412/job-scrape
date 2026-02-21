'use client'

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { Nav } from '@/components/layout/nav'
import { AdminSubNav } from '@/components/admin/AdminSubNav'
import { useRealtimeCostUpdates } from '@/lib/hooks/useRealtimeCostUpdates'
import { cn } from '@/lib/utils'
import type { CostDashboardData, ApiUsageLog, AggLogRow, UserBreakdown } from '@/lib/types'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, PieChart, Pie, Cell, BarChart, Bar, Legend, ReferenceArea,
} from 'recharts'

/* ── Formatters ── */

function fmtCost(v: number | null): string {
  if (v == null || v === 0) return '$0.00'
  if (v < 0.01) return `$${v.toFixed(4)}`
  if (v < 1) return `$${v.toFixed(3)}`
  return `$${v.toFixed(2)}`
}

function fmtTokens(n: number | null): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

function fmtLatency(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function fmtChartDate(dateStr: string): string {
  const d = new Date(dateStr + 'T12:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/* ── Constants ── */

const SOURCE_COLORS: Record<string, string> = {
  web: '#3b82f6',       // blue-500
  pipeline: '#f59e0b',  // amber-500
  external: '#10b981',  // emerald-500
}

const SOURCE_BADGE: Record<string, string> = {
  web: 'border-blue-900/50 bg-blue-950/30 text-blue-400',
  pipeline: 'border-amber-900/50 bg-amber-950/30 text-amber-500',
  external: 'border-emerald-900/40 bg-emerald-950/20 text-emerald-500',
}

/* ── Custom Tooltip ── */

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number }>; label?: string }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-[#2a2a2a] bg-[#111] px-3 py-2 shadow-xl">
      <p className="font-mono text-[10px] text-zinc-500">{label}</p>
      <p className="font-mono text-sm text-amber-400">{fmtCost(payload[0].value)}</p>
    </div>
  )
}

/* ── Component ── */

export default function AdminCostsPage() {
  const [rawData, setRawData] = useState<CostDashboardData | null>(null)
  const [loading, setLoading] = useState(true)

  // Time-range filters (trigger server re-fetch)
  const [timeFrame, setTimeFrame] = useState('')  // relative: '1h','6h','24h','7d','30d','90d'
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')

  // Chart type toggle (line or bar, like BrightData)
  const [chartType, setChartType] = useState<'line' | 'bar'>('line')

  // Zoom state for cost trend chart
  const [zoomRange, setZoomRange] = useState<[number, number] | null>(null)
  const [dragStart, setDragStart] = useState<string | null>(null)
  const [dragEnd, setDragEnd] = useState<string | null>(null)
  const trendChartRef = useRef<HTMLDivElement>(null)
  const lastTapRef = useRef(0)

  // Client-side filters (instant, no server round-trip)
  const [sourceFilter, setSourceFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [pipelineFilter, setPipelineFilter] = useState('')
  const [userFilter, setUserFilter] = useState('')

  // Only re-fetch from server when time range changes
  const fetchData = useCallback(async () => {
    const params = new URLSearchParams()
    if (timeFrame) {
      const now = new Date()
      const ms: Record<string, number> = {
        '1h': 3600000, '6h': 21600000, '24h': 86400000,
        '7d': 604800000, '30d': 2592000000, '90d': 7776000000,
      }
      params.set('from', new Date(now.getTime() - (ms[timeFrame] ?? 0)).toISOString())
    } else {
      if (fromDate) params.set('from', new Date(fromDate).toISOString())
      if (toDate) params.set('to', new Date(toDate + 'T23:59:59').toISOString())
    }

    try {
      const res = await fetch(`/api/admin/costs?${params}`)
      if (!res.ok) return
      const json = await res.json()
      setRawData(json)
    } finally {
      setLoading(false)
    }
  }, [timeFrame, fromDate, toDate])

  useEffect(() => {
    if (!rawData) setLoading(true)
    fetchData()
  }, [fetchData]) // eslint-disable-line react-hooks/exhaustive-deps

  // Realtime: re-fetch when new api_usage_log rows are inserted
  useRealtimeCostUpdates(true, fetchData)

  // Shared filter predicate for both aggregation and activity data
  const matchesFilters = useCallback((l: { source: string; category: string; pipeline: string | null; user_id: string | null }) => {
    if (sourceFilter && l.source !== sourceFilter) return false
    if (categoryFilter && l.category !== categoryFilter) return false
    if (pipelineFilter && (l.pipeline ?? 'unknown') !== pipelineFilter) return false
    if (userFilter) {
      if (userFilter === 'system' && l.user_id != null) return false
      if (userFilter !== 'system' && l.user_id !== userFilter) return false
    }
    return true
  }, [sourceFilter, categoryFilter, pipelineFilter, userFilter])

  // Aggregation from lightweight agg data (covers ALL rows, no limit)
  // Activity table from recent data (limited to 500 most recent)
  const { summary, hourly, dailyCosts, bySource, byModel, byPipeline, byUser, users, recent } = useMemo(() => {
    const aggLogs: AggLogRow[] = rawData?.agg ?? []
    const recentLogs: ApiUsageLog[] = rawData?.recent ?? []
    const allUsers = rawData?.users ?? []

    // Filter aggregation data (all rows)
    const filtered = aggLogs.filter(matchesFilters)
    // Filter activity table data (recent 500)
    const filteredRecent = recentLogs.filter(matchesFilters)

    // Summary — dynamic time buckets based on active time range
    const now = new Date()
    const bucketDefs: Record<string, { label: string; ms: number }[]> = {
      '1h':  [{ label: 'Last 15m', ms: 900000 },    { label: 'Last 30m', ms: 1800000 },   { label: 'Last Hour', ms: 3600000 }],
      '6h':  [{ label: 'Last Hour', ms: 3600000 },   { label: 'Last 3h', ms: 10800000 },   { label: 'Last 6h', ms: 21600000 }],
      '24h': [{ label: 'Last Hour', ms: 3600000 },   { label: 'Last 6h', ms: 21600000 },   { label: 'Last 24h', ms: 86400000 }],
      '7d':  [{ label: 'Today', ms: 0 },             { label: 'Last 3d', ms: 259200000 },   { label: 'Last 7d', ms: 604800000 }],
      '30d': [{ label: 'Today', ms: 0 },             { label: 'This Week', ms: 604800000 }, { label: 'Last 30d', ms: 2592000000 }],
      '90d': [{ label: 'Today', ms: 0 },             { label: 'This Week', ms: 604800000 }, { label: 'This Month', ms: 0 }],
      '':    [{ label: 'Today', ms: 0 },             { label: 'This Week', ms: 604800000 }, { label: 'This Month', ms: 0 }],
    }
    const buckets = bucketDefs[timeFrame] ?? bucketDefs['']
    const bucketCosts = buckets.map((b) => {
      let cutoff: string
      if (b.label === 'Today') {
        cutoff = new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString()
      } else if (b.label === 'This Month') {
        cutoff = new Date(now.getFullYear(), now.getMonth(), 1).toISOString()
      } else {
        cutoff = new Date(now.getTime() - b.ms).toISOString()
      }
      return {
        label: b.label,
        value: filtered.filter(l => l.created_at >= cutoff).reduce((s, l) => s + (l.cost_usd ?? 0), 0),
      }
    })

    // Cost trend — granularity adapts to time frame
    const granularity = timeFrame === '1h' ? 5 : timeFrame === '6h' ? 15 : timeFrame === '24h' ? 30 : 0
    const hourly = granularity > 0
    const dailyMap = new Map<string, { cost: number; calls: number }>()
    for (const l of filtered) {
      let key: string
      if (granularity > 0) {
        const d = new Date(l.created_at)
        const mins = Math.floor(d.getMinutes() / granularity) * granularity
        d.setMinutes(mins, 0, 0)
        key = d.toISOString().slice(0, 16)
      } else {
        key = l.created_at.slice(0, 10)
      }
      const e = dailyMap.get(key) || { cost: 0, calls: 0 }
      e.cost += l.cost_usd ?? 0; e.calls += 1
      dailyMap.set(key, e)
    }

    // Fill in zero-value gaps so the chart has a continuous x-axis
    const timeMs: Record<string, number> = {
      '1h': 3600000, '6h': 21600000, '24h': 86400000,
      '7d': 604800000, '30d': 2592000000, '90d': 7776000000,
    }
    if (granularity > 0) {
      // Hourly: fill every granularity-minute slot across the range
      const rangeMs = timeMs[timeFrame] ?? 86400000
      const end = new Date(Math.ceil(now.getTime() / (granularity * 60000)) * granularity * 60000)
      const start = new Date(end.getTime() - rangeMs)
      for (let t = start.getTime(); t <= end.getTime(); t += granularity * 60000) {
        const d = new Date(t)
        const key = d.toISOString().slice(0, 16)
        if (!dailyMap.has(key)) dailyMap.set(key, { cost: 0, calls: 0 })
      }
    } else {
      // Daily: fill every day from the earliest data point (or range start) to today
      const rangeMs = timeMs[timeFrame] ?? 2592000000 // default 30d
      const rangeStartDate = new Date(now.getTime() - rangeMs)
      const startDay = new Date(rangeStartDate.getFullYear(), rangeStartDate.getMonth(), rangeStartDate.getDate())
      const endDay = new Date(now.getFullYear(), now.getMonth(), now.getDate())
      for (let t = startDay.getTime(); t <= endDay.getTime(); t += 86400000) {
        const key = new Date(t).toISOString().slice(0, 10)
        if (!dailyMap.has(key)) dailyMap.set(key, { cost: 0, calls: 0 })
      }
    }

    // By source
    const srcMap = new Map<string, { cost: number; calls: number }>()
    for (const l of filtered) {
      const e = srcMap.get(l.source) || { cost: 0, calls: 0 }
      e.cost += l.cost_usd ?? 0; e.calls += 1
      srcMap.set(l.source, e)
    }

    // By model
    const mdlMap = new Map<string, { cost: number; calls: number; tokens: number }>()
    for (const l of filtered) {
      const m = l.model ?? 'unknown'
      const e = mdlMap.get(m) || { cost: 0, calls: 0, tokens: 0 }
      e.cost += l.cost_usd ?? 0; e.calls += 1; e.tokens += l.total_tokens ?? 0
      mdlMap.set(m, e)
    }

    // By pipeline
    const pipMap = new Map<string, { cost: number; calls: number; tokens: number }>()
    for (const l of filtered) {
      const p = l.pipeline ?? 'unknown'
      const e = pipMap.get(p) || { cost: 0, calls: 0, tokens: 0 }
      e.cost += l.cost_usd ?? 0; e.calls += 1; e.tokens += l.total_tokens ?? 0
      pipMap.set(p, e)
    }

    // By user
    const usrMap = new Map<string, { cost: number; calls: number; tokens: number }>()
    for (const l of filtered) {
      const uid = l.user_id ?? 'system'
      const e = usrMap.get(uid) || { cost: 0, calls: 0, tokens: 0 }
      e.cost += l.cost_usd ?? 0; e.calls += 1; e.tokens += l.total_tokens ?? 0
      usrMap.set(uid, e)
    }
    const emailMap = new Map(allUsers.map(u => [u.id, u.email]))
    emailMap.set('system', 'System / Pipeline')

    return {
      summary: {
        buckets: bucketCosts,
        total_calls: filtered.length,
        total_tokens: filtered.reduce((s, l) => s + (l.total_tokens ?? 0), 0),
      },
      hourly,
      dailyCosts: Array.from(dailyMap.entries()).map(([date, v]) => ({ date, ...v })).sort((a, b) => a.date.localeCompare(b.date)),
      bySource: Array.from(srcMap.entries()).map(([source, v]) => ({ source, ...v })),
      byModel: Array.from(mdlMap.entries()).map(([model, v]) => ({ model, ...v })).sort((a, b) => b.cost - a.cost),
      byPipeline: Array.from(pipMap.entries()).map(([pipeline, v]) => ({ pipeline, ...v })).sort((a, b) => b.cost - a.cost),
      byUser: Array.from(usrMap.entries()).map(([uid, v]) => ({ user_id: uid, email: emailMap.get(uid) ?? uid, ...v })).sort((a, b) => b.cost - a.cost),
      users: allUsers,
      recent: filteredRecent,
    }
  }, [rawData, matchesFilters, timeFrame])

  // Zoomed slice of cost trend data
  const zoomedCosts = useMemo(() => {
    if (!zoomRange) return dailyCosts
    return dailyCosts.slice(zoomRange[0], zoomRange[1] + 1)
  }, [dailyCosts, zoomRange])

  // Reset zoom when filters change
  useEffect(() => { setZoomRange(null) }, [timeFrame, fromDate, toDate, sourceFilter, categoryFilter, pipelineFilter, userFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  // Wheel/pinch zoom on cost trend chart
  const dailyCostsLenRef = useRef(dailyCosts.length)
  dailyCostsLenRef.current = dailyCosts.length

  useEffect(() => {
    const el = trendChartRef.current
    if (!el) return

    const handler = (e: WheelEvent) => {
      const len = dailyCostsLenRef.current
      if (len < 5) return
      e.preventDefault()

      setZoomRange(prev => {
        const [lo, hi] = prev ?? [0, len - 1]
        const span = hi - lo
        const step = Math.max(1, Math.round(span * 0.1))

        let newLo: number, newHi: number
        if (e.deltaY < 0) {
          newLo = lo + step; newHi = hi - step
        } else {
          newLo = Math.max(0, lo - step); newHi = Math.min(len - 1, hi + step)
        }

        if (newHi - newLo < 4) return prev
        return newLo === 0 && newHi === len - 1 ? null : [newLo, newHi]
      })
    }

    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, [loading]) // Re-attach when chart appears after loading

  // Drag-to-zoom handlers
  const dailyCostsRef = useRef(dailyCosts)
  dailyCostsRef.current = dailyCosts

  const onTrendMouseDown = useCallback((e: { activeLabel?: string | number }) => {
    if (e?.activeLabel != null) { setDragStart(String(e.activeLabel)); setDragEnd(null) }
  }, [])

  const onTrendMouseMove = useCallback((e: { activeLabel?: string | number }) => {
    if (dragStart && e?.activeLabel != null) setDragEnd(String(e.activeLabel))
  }, [dragStart])

  const onTrendMouseUp = useCallback(() => {
    if (dragStart && dragEnd && dragStart !== dragEnd) {
      const costs = dailyCostsRef.current
      const si = costs.findIndex(d => d.date === dragStart)
      const ei = costs.findIndex(d => d.date === dragEnd)
      if (si >= 0 && ei >= 0) {
        const [lo, hi] = si < ei ? [si, ei] : [ei, si]
        if (hi - lo >= 2) setZoomRange([lo, hi])
      }
    }
    setDragStart(null); setDragEnd(null)
  }, [dragStart, dragEnd])

  // Double-tap to reset zoom on mobile
  const handleDoubleTap = useCallback((e: React.TouchEvent) => {
    const now = Date.now()
    if (now - lastTapRef.current < 300) {
      e.preventDefault()
      setZoomRange(null)
    }
    lastTapRef.current = now
  }, [])

  // Pie data with colors
  const pieData = bySource.map((s) => ({
    name: s.source,
    value: s.cost,
    fill: SOURCE_COLORS[s.source] ?? '#71717a',
  }))

  // Selection state for recent activity rows
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const lastClickedIdx = useRef<number | null>(null)

  // Clear selection when data changes
  useEffect(() => { setSelectedIds(new Set()); lastClickedIdx.current = null }, [rawData])

  function handleRowClick(log: ApiUsageLog, idx: number, e: React.MouseEvent) {
    setSelectedIds((prev) => {
      const next = new Set(prev)

      if (e.shiftKey && lastClickedIdx.current != null) {
        // Range select
        const start = Math.min(lastClickedIdx.current, idx)
        const end = Math.max(lastClickedIdx.current, idx)
        for (let i = start; i <= end; i++) {
          next.add(recent[i].id)
        }
      } else if (e.metaKey || e.ctrlKey) {
        // Toggle single
        if (next.has(log.id)) next.delete(log.id)
        else next.add(log.id)
      } else {
        // Single click — select only this row (or deselect if it's the only one)
        if (next.size === 1 && next.has(log.id)) {
          next.clear()
        } else {
          next.clear()
          next.add(log.id)
        }
      }

      lastClickedIdx.current = idx
      return next
    })
  }

  const selectionAgg = useMemo(() => {
    if (selectedIds.size === 0) return null
    const sel = recent.filter((l) => selectedIds.has(l.id))
    const totalCost = sel.reduce((s, l) => s + (l.cost_usd ?? 0), 0)
    const totalTokens = sel.reduce((s, l) => s + (l.total_tokens ?? 0), 0)
    const promptTokens = sel.reduce((s, l) => s + (l.prompt_tokens ?? 0), 0)
    const completionTokens = sel.reduce((s, l) => s + (l.completion_tokens ?? 0), 0)
    const latencies = sel.map((l) => l.latency_ms).filter((v): v is number => v != null)
    const avgLatency = latencies.length ? Math.round(latencies.reduce((s, v) => s + v, 0) / latencies.length) : null
    return { count: sel.length, totalCost, totalTokens, promptTokens, completionTokens, avgLatency }
  }, [selectedIds, recent])

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-5xl px-4 py-8">

        <AdminSubNav />

        {/* Header */}
        <div className="mb-6">
          <div className="mb-1 flex items-center gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-widest text-amber-500">Admin</span>
            <span className="font-mono text-[10px] text-zinc-700">/</span>
            <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">Costs</span>
          </div>
          <h1 className="text-xl font-bold text-white" style={{ fontFamily: 'Syne, sans-serif' }}>
            Cost Dashboard
          </h1>
          <div className="mt-0.5 flex items-center gap-2">
            <p className="text-sm text-zinc-600">API &amp; LLM usage tracking</p>
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-900/40 bg-emerald-950/20 px-1.5 py-0.5">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
              </span>
              <span className="font-mono text-[9px] font-semibold uppercase tracking-wider text-emerald-500">Live</span>
            </span>
          </div>
        </div>

        {loading ? (
          <div className="py-24 text-center font-mono text-xs text-zinc-700">Loading cost data…</div>
        ) : (
          <>
            {/* ── Summary Cards ── */}
            <div className="mb-6 grid grid-cols-3 gap-3 sm:grid-cols-5">
              {(summary?.buckets ?? []).map((b) => (
                <div key={b.label} className="rounded-xl border border-border bg-[#111] p-4">
                  <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">{b.label}</p>
                  <p className="font-mono text-lg font-semibold tabular-nums text-amber-400">{fmtCost(b.value)}</p>
                </div>
              ))}
              <div className="rounded-xl border border-border bg-[#111] p-4">
                <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">Total Calls</p>
                <p className="font-mono text-lg font-semibold tabular-nums text-zinc-300">{fmtTokens(summary?.total_calls ?? 0)}</p>
              </div>
              <div className="rounded-xl border border-border bg-[#111] p-4">
                <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">Total Tokens</p>
                <p className="font-mono text-lg font-semibold tabular-nums text-zinc-300">{fmtTokens(summary?.total_tokens ?? 0)}</p>
              </div>
            </div>

            {/* ── Filters ── */}
            <div className="mb-6">
              <div className="grid grid-cols-2 items-end gap-2 sm:grid-cols-4 lg:grid-cols-8">
                <div>
                  <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">Time Frame</label>
                  <select
                    value={timeFrame}
                    onChange={(e) => { setTimeFrame(e.target.value); if (e.target.value) { setFromDate(''); setToDate('') } }}
                    className="w-full rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-2 py-1.5 font-mono text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
                  >
                    <option value="">All time</option>
                    <option value="1h">Last hour</option>
                    <option value="6h">Last 6 hours</option>
                    <option value="24h">Last 24 hours</option>
                    <option value="7d">Last 7 days</option>
                    <option value="30d">Last 30 days</option>
                    <option value="90d">Last 90 days</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">From</label>
                  <input
                    type="date"
                    value={fromDate}
                    onChange={(e) => { setFromDate(e.target.value); setTimeFrame('') }}
                    className="w-full rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-2 py-1.5 font-mono text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">To</label>
                  <input
                    type="date"
                    value={toDate}
                    onChange={(e) => { setToDate(e.target.value); setTimeFrame('') }}
                    className="w-full rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-2 py-1.5 font-mono text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">Source</label>
                  <select
                    value={sourceFilter}
                    onChange={(e) => setSourceFilter(e.target.value)}
                    className="w-full rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-2 py-1.5 font-mono text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
                  >
                    <option value="">All</option>
                    <option value="web">Web</option>
                    <option value="pipeline">Pipeline</option>
                    <option value="external">External</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">Category</label>
                  <select
                    value={categoryFilter}
                    onChange={(e) => setCategoryFilter(e.target.value)}
                    className="w-full rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-2 py-1.5 font-mono text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
                  >
                    <option value="">All</option>
                    <option value="llm">LLM</option>
                    <option value="search_api">Search API</option>
                    <option value="dataset_api">Dataset API</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">Pipeline</label>
                  <select
                    value={pipelineFilter}
                    onChange={(e) => setPipelineFilter(e.target.value)}
                    className="w-full rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-2 py-1.5 font-mono text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
                  >
                    <option value="">All</option>
                    <option value="web_app">Web App</option>
                    <option value="job_scraper">Job Scraper</option>
                    <option value="freelance_finder">Freelance</option>
                    <option value="facebook_monitor">FB Monitor</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">User</label>
                  <select
                    value={userFilter}
                    onChange={(e) => setUserFilter(e.target.value)}
                    className="w-full rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-2 py-1.5 font-mono text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
                  >
                    <option value="">All</option>
                    {users.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.email.length > 20 ? u.email.slice(0, 20) + '…' : u.email}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex items-end pb-1">
                  {(timeFrame || fromDate || toDate || sourceFilter || categoryFilter || pipelineFilter || userFilter) && (
                    <button
                      onClick={() => { setTimeFrame(''); setFromDate(''); setToDate(''); setSourceFilter(''); setCategoryFilter(''); setPipelineFilter(''); setUserFilter('') }}
                      className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
                    >
                      clear
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* ── Cost Trend Chart ── */}
            <div className="mb-6">
              <div className="mb-3 flex items-center justify-between">
                <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-600">
                  {hourly ? 'Hourly Cost Trend' : 'Daily Cost Trend'}
                </p>
                <div className="flex items-center gap-2">
                  {zoomRange && (
                    <button
                      onClick={() => setZoomRange(null)}
                      className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
                    >
                      Reset zoom
                    </button>
                  )}
                  <div className="flex items-center gap-0.5 rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] p-0.5">
                  <button
                    onClick={() => setChartType('line')}
                    className={cn(
                      'rounded-md px-2 py-1 transition-colors',
                      chartType === 'line' ? 'bg-[#1a1a1a] text-zinc-300' : 'text-zinc-600 hover:text-zinc-400',
                    )}
                    title="Line chart"
                  >
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="1,11 4,6 7,8 10,3 13,5" />
                    </svg>
                  </button>
                  <button
                    onClick={() => setChartType('bar')}
                    className={cn(
                      'rounded-md px-2 py-1 transition-colors',
                      chartType === 'bar' ? 'bg-[#1a1a1a] text-zinc-300' : 'text-zinc-600 hover:text-zinc-400',
                    )}
                    title="Bar chart"
                  >
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                      <rect x="1" y="8" width="2" height="5" rx="0.5" />
                      <rect x="4.5" y="5" width="2" height="8" rx="0.5" />
                      <rect x="8" y="2" width="2" height="11" rx="0.5" />
                      <rect x="11.5" y="6" width="2" height="7" rx="0.5" />
                    </svg>
                  </button>
                </div>
                </div>
              </div>
              <div ref={trendChartRef} className="rounded-xl border border-border bg-[#111] p-4" style={{ touchAction: 'none' }} onTouchEnd={handleDoubleTap}>
                {dailyCosts.length === 0 ? (
                  <div className="flex h-48 items-center justify-center font-mono text-xs text-zinc-700">
                    No cost data for this period
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={260}>
                    {chartType === 'bar' ? (
                      <BarChart data={zoomedCosts} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap="40%" onMouseDown={onTrendMouseDown} onMouseMove={onTrendMouseMove} onMouseUp={onTrendMouseUp}>
                        <CartesianGrid strokeDasharray="3 6" stroke="#1a1a1a" />
                        <XAxis
                          dataKey="date"
                          tickFormatter={(v: string) => {
                            if (hourly) {
                              const h = parseInt(v.slice(11, 13), 10)
                              const m = v.slice(14, 16)
                              const suffix = h >= 12 ? 'pm' : 'am'
                              const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h
                              return m === '00' ? `${h12}${suffix}` : `${h12}:${m}`
                            }
                            return fmtChartDate(v)
                          }}
                          tick={{ fill: '#52525b', fontSize: 10, fontFamily: 'monospace' }}
                          axisLine={{ stroke: '#1a1a1a' }}
                          tickLine={false}
                        />
                        <YAxis
                          tickFormatter={(v: number) => `$${v < 1 ? v.toFixed(2) : v.toFixed(0)}`}
                          tick={{ fill: '#52525b', fontSize: 10, fontFamily: 'monospace' }}
                          axisLine={false}
                          tickLine={false}
                          width={50}
                        />
                        <RechartsTooltip
                          cursor={false}
                          content={<ChartTooltip />}
                        />
                        <Bar dataKey="cost" fill="#f59e0b" maxBarSize={2} radius={[1, 1, 0, 0]} animationDuration={800} animationEasing="ease-out" />
                        {dragStart && dragEnd && (
                          <ReferenceArea x1={dragStart} x2={dragEnd} strokeOpacity={0.3} fill="#f59e0b" fillOpacity={0.08} />
                        )}
                      </BarChart>
                    ) : (
                      <AreaChart data={zoomedCosts} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} onMouseDown={onTrendMouseDown} onMouseMove={onTrendMouseMove} onMouseUp={onTrendMouseUp}>
                        <defs>
                          <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.1} />
                            <stop offset="100%" stopColor="#f59e0b" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 6" stroke="#1a1a1a" />
                        <XAxis
                          dataKey="date"
                          tickFormatter={(v: string) => {
                            if (hourly) {
                              const h = parseInt(v.slice(11, 13), 10)
                              const m = v.slice(14, 16)
                              const suffix = h >= 12 ? 'pm' : 'am'
                              const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h
                              return m === '00' ? `${h12}${suffix}` : `${h12}:${m}`
                            }
                            return fmtChartDate(v)
                          }}
                          tick={{ fill: '#52525b', fontSize: 10, fontFamily: 'monospace' }}
                          axisLine={{ stroke: '#1a1a1a' }}
                          tickLine={false}
                        />
                        <YAxis
                          tickFormatter={(v: number) => `$${v < 1 ? v.toFixed(2) : v.toFixed(0)}`}
                          tick={{ fill: '#52525b', fontSize: 10, fontFamily: 'monospace' }}
                          axisLine={false}
                          tickLine={false}
                          width={50}
                        />
                        <RechartsTooltip content={<ChartTooltip />} />
                        <Area
                          type="monotone"
                          dataKey="cost"
                          stroke="#f59e0b"
                          strokeWidth={1.5}
                          fill="url(#costGradient)"
                          dot={false}
                          activeDot={{ r: 3, fill: '#fbbf24', stroke: '#111', strokeWidth: 1.5 }}
                          animationDuration={1000}
                          animationEasing="ease-out"
                        />
                        {dragStart && dragEnd && (
                          <ReferenceArea x1={dragStart} x2={dragEnd} strokeOpacity={0.3} fill="#f59e0b" fillOpacity={0.08} />
                        )}
                      </AreaChart>
                    )}
                  </ResponsiveContainer>
                )}
                {!zoomRange && dailyCosts.length > 5 && (
                  <p className="mt-2 text-center font-mono text-[9px] text-zinc-700">
                    Scroll to zoom · Drag to select range
                  </p>
                )}
                {zoomRange && (
                  <p className="mt-2 text-center font-mono text-[9px] text-zinc-600">
                    Showing {zoomRange[1] - zoomRange[0] + 1} of {dailyCosts.length} points
                  </p>
                )}
              </div>
            </div>

            {/* ── Breakdown Grid ── */}
            <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
              {/* By Source — Pie */}
              <div>
                <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-zinc-600">By Source</p>
                <div className="rounded-xl border border-border bg-[#111] p-4">
                  {pieData.length === 0 || pieData.every((d) => d.value === 0) ? (
                    <div className="flex h-48 items-center justify-center font-mono text-xs text-zinc-700">
                      No data
                    </div>
                  ) : (
                    <div className="flex items-center gap-4">
                      <ResponsiveContainer width="60%" height={180}>
                        <PieChart>
                          <Pie
                            data={pieData}
                            dataKey="value"
                            nameKey="name"
                            cx="50%"
                            cy="50%"
                            innerRadius={40}
                            outerRadius={70}
                            strokeWidth={0}
                          >
                            {pieData.map((entry, i) => (
                              <Cell key={i} fill={entry.fill} />
                            ))}
                          </Pie>
                        </PieChart>
                      </ResponsiveContainer>
                      <div className="flex flex-col gap-2">
                        {bySource.map((s) => (
                          <div key={s.source} className="flex items-center gap-2">
                            <span
                              className="h-2 w-2 rounded-full"
                              style={{ backgroundColor: SOURCE_COLORS[s.source] ?? '#71717a' }}
                            />
                            <span className="font-mono text-[10px] uppercase text-zinc-400">{s.source}</span>
                            <span className="font-mono text-[10px] tabular-nums text-zinc-600">{fmtCost(s.cost)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* By Model — Bar */}
              <div>
                <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-zinc-600">By Model</p>
                <div className="rounded-xl border border-border bg-[#111] p-4">
                  {byModel.length === 0 ? (
                    <div className="flex h-48 items-center justify-center font-mono text-xs text-zinc-700">
                      No data
                    </div>
                  ) : (
                    <ResponsiveContainer width="100%" height={180}>
                      <BarChart
                        data={byModel.slice(0, 8)}
                        layout="vertical"
                        margin={{ top: 0, right: 4, bottom: 0, left: 0 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" horizontal={false} />
                        <XAxis
                          type="number"
                          tickFormatter={(v: number) => fmtCost(v)}
                          tick={{ fill: '#52525b', fontSize: 10, fontFamily: 'monospace' }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <YAxis
                          type="category"
                          dataKey="model"
                          tick={{ fill: '#71717a', fontSize: 9, fontFamily: 'monospace' }}
                          axisLine={false}
                          tickLine={false}
                          width={140}
                          tickFormatter={(v: string) => v.length > 22 ? v.slice(0, 22) + '…' : v}
                        />
                        <RechartsTooltip
                          cursor={false}
                          content={({ active, payload }) => {
                            if (!active || !payload?.length) return null
                            const d = payload[0].payload as { model: string; cost: number; calls: number; tokens: number }
                            return (
                              <div className="rounded-lg border border-[#2a2a2a] bg-[#111] px-3 py-2 shadow-xl">
                                <p className="font-mono text-[10px] text-zinc-400">{d.model}</p>
                                <p className="font-mono text-sm text-amber-400">{fmtCost(d.cost)}</p>
                                <p className="font-mono text-[10px] text-zinc-600">{d.calls} calls · {fmtTokens(d.tokens)} tokens</p>
                              </div>
                            )
                          }}
                        />
                        <Bar dataKey="cost" fill="#f59e0b" radius={[0, 3, 3, 0]} barSize={14} />
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </div>

              {/* By Pipeline — Bar */}
              <div>
                <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-zinc-600">By Pipeline</p>
                <div className="rounded-xl border border-border bg-[#111] p-4">
                  {byPipeline.length === 0 ? (
                    <div className="flex h-48 items-center justify-center font-mono text-xs text-zinc-700">
                      No data
                    </div>
                  ) : (
                    <ResponsiveContainer width="100%" height={180}>
                      <BarChart
                        data={byPipeline.slice(0, 8)}
                        layout="vertical"
                        margin={{ top: 0, right: 4, bottom: 0, left: 0 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" horizontal={false} />
                        <XAxis
                          type="number"
                          tickFormatter={(v: number) => fmtCost(v)}
                          tick={{ fill: '#52525b', fontSize: 10, fontFamily: 'monospace' }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <YAxis
                          type="category"
                          dataKey="pipeline"
                          tick={{ fill: '#71717a', fontSize: 9, fontFamily: 'monospace' }}
                          axisLine={false}
                          tickLine={false}
                          width={120}
                          tickFormatter={(v: string) => v.replace(/_/g, ' ')}
                        />
                        <RechartsTooltip
                          cursor={false}
                          content={({ active, payload }) => {
                            if (!active || !payload?.length) return null
                            const d = payload[0].payload as { pipeline: string; cost: number; calls: number; tokens: number }
                            return (
                              <div className="rounded-lg border border-[#2a2a2a] bg-[#111] px-3 py-2 shadow-xl">
                                <p className="font-mono text-[10px] text-zinc-400">{d.pipeline.replace(/_/g, ' ')}</p>
                                <p className="font-mono text-sm text-amber-400">{fmtCost(d.cost)}</p>
                                <p className="font-mono text-[10px] text-zinc-600">{d.calls} calls · {fmtTokens(d.tokens)} tokens</p>
                              </div>
                            )
                          }}
                        />
                        <Bar dataKey="cost" fill="#8b5cf6" radius={[0, 3, 3, 0]} barSize={14} />
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </div>
            </div>

            {/* ── By User Breakdown ── */}
            <div className="mb-6">
              <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-zinc-600">By User</p>
              <div className="rounded-xl border border-border bg-[#111] p-4">
                {byUser.length === 0 ? (
                  <div className="flex h-32 items-center justify-center font-mono text-xs text-zinc-700">
                    No data
                  </div>
                ) : (
                  <div className="grid grid-cols-[1fr_80px_60px_80px] gap-3">
                    {/* Header */}
                    <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">User</span>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 text-right">Cost</span>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 text-right">Calls</span>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 text-right">Tokens</span>
                    {/* Rows */}
                    {byUser.map((u: UserBreakdown) => {
                      const maxCost = byUser[0]?.cost || 1
                      const pct = Math.max(2, (u.cost / maxCost) * 100)
                      return (
                        <React.Fragment key={u.user_id}>
                          <div className="flex items-center gap-2 overflow-hidden">
                            <div
                              className="h-1.5 shrink-0 rounded-full bg-cyan-500/60"
                              style={{ width: `${pct}%`, maxWidth: '40%' }}
                            />
                            <span
                              className={cn(
                                'truncate font-mono text-[11px]',
                                u.user_id === 'system' ? 'text-zinc-600 italic' : 'text-zinc-400',
                              )}
                            >
                              {u.email}
                            </span>
                          </div>
                          <span className="text-right font-mono text-[11px] tabular-nums text-amber-400">{fmtCost(u.cost)}</span>
                          <span className="text-right font-mono text-[11px] tabular-nums text-zinc-500">{u.calls}</span>
                          <span className="text-right font-mono text-[11px] tabular-nums text-zinc-600">{fmtTokens(u.tokens)}</span>
                        </React.Fragment>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>

            {/* ── Recent Activity Table ── */}
            <div className="mb-8">
              <div className="mb-3 flex items-center justify-between">
                <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-600">Recent Activity</p>
                <div className="flex items-center gap-3">
                  {selectedIds.size > 0 && (
                    <button
                      onClick={() => { setSelectedIds(new Set()); lastClickedIdx.current = null }}
                      className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
                    >
                      clear selection
                    </button>
                  )}
                  <span className="font-mono text-[10px] text-zinc-700">{recent.length} entries</span>
                </div>
              </div>

              {/* Selection aggregate bar */}
              {selectionAgg && (
                <div className="mb-3 flex items-center gap-4 rounded-xl border border-amber-900/30 bg-amber-950/10 px-4 py-2.5">
                  <span className="font-mono text-[10px] font-semibold uppercase tracking-wider text-amber-500">
                    {selectionAgg.count} selected
                  </span>
                  <span className="h-3 w-px bg-amber-900/30" />
                  <div className="flex items-center gap-1">
                    <span className="font-mono text-[10px] uppercase text-zinc-600">Cost</span>
                    <span className="font-mono text-xs tabular-nums text-amber-400">{fmtCost(selectionAgg.totalCost)}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="font-mono text-[10px] uppercase text-zinc-600">Tokens</span>
                    <span className="font-mono text-xs tabular-nums text-zinc-300">{fmtTokens(selectionAgg.totalTokens)}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="font-mono text-[10px] uppercase text-zinc-600">Prompt</span>
                    <span className="font-mono text-xs tabular-nums text-zinc-500">{fmtTokens(selectionAgg.promptTokens)}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="font-mono text-[10px] uppercase text-zinc-600">Completion</span>
                    <span className="font-mono text-xs tabular-nums text-zinc-500">{fmtTokens(selectionAgg.completionTokens)}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="font-mono text-[10px] uppercase text-zinc-600">Avg Latency</span>
                    <span className="font-mono text-xs tabular-nums text-zinc-300">{fmtLatency(selectionAgg.avgLatency)}</span>
                  </div>
                </div>
              )}

              {recent.length === 0 ? (
                <div className="rounded-xl border border-border bg-[#111] p-12 text-center text-sm text-zinc-600">
                  No API calls logged yet.
                </div>
              ) : (
                <div className="overflow-hidden rounded-xl border border-border bg-[#111]">
                  {/* Table header */}
                  <div className="grid grid-cols-[70px_70px_100px_1fr_80px_70px_60px_50px] gap-3 border-b border-border px-4 py-2.5">
                    <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Time</span>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Source</span>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Operation</span>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Model</span>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 text-right">Tokens</span>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 text-right">Cost</span>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 text-right">Latency</span>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600 text-right">Status</span>
                  </div>

                  {/* Rows */}
                  <div className="max-h-120 overflow-y-auto select-none">
                    {recent.map((log: ApiUsageLog, i: number) => (
                      <div
                        key={log.id}
                        onClick={(e) => handleRowClick(log, i, e)}
                        className={cn(
                          'grid cursor-pointer grid-cols-[70px_70px_100px_1fr_80px_70px_60px_50px] items-center gap-3 px-4 py-2 transition-colors',
                          selectedIds.has(log.id)
                            ? 'bg-amber-950/20 hover:bg-amber-950/30'
                            : 'hover:bg-[#141414]',
                          i !== recent.length - 1 && 'border-b border-border',
                        )}
                      >
                        <span className="font-mono text-[10px] text-zinc-600">{relativeTime(log.created_at)}</span>

                        <span className={cn('inline-flex w-fit rounded-full border px-1.5 py-0.5 font-mono text-[10px] font-semibold', SOURCE_BADGE[log.source] ?? 'border-zinc-700 text-zinc-500')}>
                          {log.source}
                        </span>

                        <span className="truncate font-mono text-[10px] text-zinc-400">{log.operation}</span>

                        <span className="truncate font-mono text-[10px] text-zinc-600">{log.model ?? '—'}</span>

                        <span className="text-right font-mono text-[10px] tabular-nums text-zinc-600">
                          {log.total_tokens ? fmtTokens(log.total_tokens) : '—'}
                        </span>

                        <span className="text-right font-mono text-[10px] tabular-nums text-zinc-400">
                          {log.cost_usd != null ? fmtCost(log.cost_usd) : '—'}
                        </span>

                        <span className="text-right font-mono text-[10px] tabular-nums text-zinc-600">
                          {fmtLatency(log.latency_ms)}
                        </span>

                        <span className="flex justify-end">
                          <span className={cn(
                            'h-1.5 w-1.5 rounded-full',
                            log.success ? 'bg-emerald-500' : 'bg-red-500',
                          )} />
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  )
}
