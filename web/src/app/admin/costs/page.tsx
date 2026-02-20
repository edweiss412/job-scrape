'use client'

import { useState, useEffect, useCallback } from 'react'
import { Nav } from '@/components/layout/nav'
import { AdminSubNav } from '@/components/admin/AdminSubNav'
import { cn } from '@/lib/utils'
import type { CostDashboardData, ApiUsageLog } from '@/lib/types'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, PieChart, Pie, Cell, BarChart, Bar, Legend,
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
  const [data, setData] = useState<CostDashboardData | null>(null)
  const [loading, setLoading] = useState(true)

  // Filters
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [pipelineFilter, setPipelineFilter] = useState('')

  const fetchData = useCallback(async () => {
    const params = new URLSearchParams()
    if (fromDate) params.set('from', new Date(fromDate).toISOString())
    if (toDate) params.set('to', new Date(toDate + 'T23:59:59').toISOString())
    if (sourceFilter) params.set('source', sourceFilter)
    if (categoryFilter) params.set('category', categoryFilter)
    if (pipelineFilter) params.set('pipeline', pipelineFilter)

    try {
      const res = await fetch(`/api/admin/costs?${params}`)
      if (!res.ok) return
      const json = await res.json()
      setData(json)
    } finally {
      setLoading(false)
    }
  }, [fromDate, toDate, sourceFilter, categoryFilter, pipelineFilter])

  useEffect(() => {
    setLoading(true)
    fetchData()
  }, [fetchData])

  const summary = data?.summary
  const dailyCosts = data?.dailyCosts ?? []
  const bySource = data?.bySource ?? []
  const byModel = data?.byModel ?? []
  const byPipeline = data?.byPipeline ?? []
  const recent = data?.recent ?? []

  // Pie data with colors
  const pieData = bySource.map((s) => ({
    name: s.source,
    value: s.cost,
    fill: SOURCE_COLORS[s.source] ?? '#71717a',
  }))

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
          <p className="mt-0.5 text-sm text-zinc-600">API &amp; LLM usage tracking</p>
        </div>

        {loading ? (
          <div className="py-24 text-center font-mono text-xs text-zinc-700">Loading cost data…</div>
        ) : (
          <>
            {/* ── Summary Cards ── */}
            <div className="mb-6 grid grid-cols-5 gap-3">
              {[
                { label: 'Today', value: fmtCost(summary?.today ?? 0), accent: 'text-amber-400' },
                { label: 'This Week', value: fmtCost(summary?.week ?? 0), accent: 'text-amber-400' },
                { label: 'This Month', value: fmtCost(summary?.month ?? 0), accent: 'text-amber-400' },
                { label: 'Total Calls', value: fmtTokens(summary?.total_calls ?? 0), accent: 'text-zinc-300' },
                { label: 'Total Tokens', value: fmtTokens(summary?.total_tokens ?? 0), accent: 'text-zinc-300' },
              ].map((card) => (
                <div key={card.label} className="rounded-xl border border-border bg-[#111] p-4">
                  <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">{card.label}</p>
                  <p className={cn('font-mono text-lg font-semibold tabular-nums', card.accent)}>{card.value}</p>
                </div>
              ))}
            </div>

            {/* ── Filters ── */}
            <div className="mb-6 flex flex-wrap items-end gap-3">
              <div>
                <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">From</label>
                <input
                  type="date"
                  value={fromDate}
                  onChange={(e) => setFromDate(e.target.value)}
                  className="rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-3 py-1.5 font-mono text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">To</label>
                <input
                  type="date"
                  value={toDate}
                  onChange={(e) => setToDate(e.target.value)}
                  className="rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-3 py-1.5 font-mono text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">Source</label>
                <select
                  value={sourceFilter}
                  onChange={(e) => setSourceFilter(e.target.value)}
                  className="rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-3 py-1.5 font-mono text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
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
                  className="rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-3 py-1.5 font-mono text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
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
                  className="rounded-lg border border-[#2a2a2a] bg-[#0e0e0e] px-3 py-1.5 font-mono text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
                >
                  <option value="">All</option>
                  <option value="web_app">Web App</option>
                  <option value="job_scraper">Job Scraper</option>
                  <option value="freelance_finder">Freelance Finder</option>
                  <option value="facebook_monitor">Facebook Monitor</option>
                </select>
              </div>
              {(fromDate || toDate || sourceFilter || categoryFilter || pipelineFilter) && (
                <button
                  onClick={() => { setFromDate(''); setToDate(''); setSourceFilter(''); setCategoryFilter(''); setPipelineFilter('') }}
                  className="mb-0.5 font-mono text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
                >
                  clear filters
                </button>
              )}
            </div>

            {/* ── Cost Trend Chart ── */}
            <div className="mb-6">
              <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-zinc-600">Daily Cost Trend</p>
              <div className="rounded-xl border border-border bg-[#111] p-4">
                {dailyCosts.length === 0 ? (
                  <div className="flex h-48 items-center justify-center font-mono text-xs text-zinc-700">
                    No cost data for this period
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={220}>
                    <AreaChart data={dailyCosts} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                      <defs>
                        <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.3} />
                          <stop offset="100%" stopColor="#f59e0b" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" vertical={false} />
                      <XAxis
                        dataKey="date"
                        tickFormatter={fmtChartDate}
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
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>

            {/* ── Breakdown Grid ── */}
            <div className="mb-6 grid grid-cols-3 gap-3">
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

            {/* ── Recent Activity Table ── */}
            <div className="mb-8">
              <div className="mb-3 flex items-center justify-between">
                <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-600">Recent Activity</p>
                <span className="font-mono text-[10px] text-zinc-700">{recent.length} entries</span>
              </div>

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
                  <div className="max-h-[480px] overflow-y-auto">
                    {recent.map((log: ApiUsageLog, i: number) => (
                      <div
                        key={log.id}
                        className={cn(
                          'grid grid-cols-[70px_70px_100px_1fr_80px_70px_60px_50px] items-center gap-3 px-4 py-2 transition-colors hover:bg-[#141414]',
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
