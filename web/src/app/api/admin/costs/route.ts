import { createClient } from '@/lib/supabase/server'
import { createServiceClient } from '@/lib/supabase/server'
import { NextResponse } from 'next/server'
import { ADMIN_EMAIL } from '@/lib/admin'

export async function GET(request: Request) {
  // Admin-only
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user || user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const { searchParams } = new URL(request.url)
  const from = searchParams.get('from')
  const to = searchParams.get('to')
  const source = searchParams.get('source')
  const category = searchParams.get('category')
  const pipeline = searchParams.get('pipeline')

  const admin = createServiceClient()

  // Summary: today, this week, this month
  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString()
  const weekStart = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString()
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString()

  // Fetch all logs within the relevant period (last 30 days default, or custom range)
  const rangeStart = from || new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString()
  const rangeEnd = to || now.toISOString()

  let logsQuery = admin
    .from('api_usage_log')
    .select('*')
    .gte('created_at', rangeStart)
    .lte('created_at', rangeEnd)
    .order('created_at', { ascending: false })
    .limit(2000)

  if (source) logsQuery = logsQuery.eq('source', source)
  if (category) logsQuery = logsQuery.eq('category', category)
  if (pipeline) logsQuery = logsQuery.eq('pipeline', pipeline)

  const { data: logs, error } = await logsQuery

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }

  const allLogs = logs || []

  // Compute summary
  const todayCost = allLogs
    .filter(l => l.created_at >= todayStart)
    .reduce((sum, l) => sum + (l.cost_usd || 0), 0)
  const weekCost = allLogs
    .filter(l => l.created_at >= weekStart)
    .reduce((sum, l) => sum + (l.cost_usd || 0), 0)
  const monthCost = allLogs
    .filter(l => l.created_at >= monthStart)
    .reduce((sum, l) => sum + (l.cost_usd || 0), 0)
  const totalCalls = allLogs.length
  const totalTokens = allLogs.reduce((sum, l) => sum + (l.total_tokens || 0), 0)

  // Daily costs (aggregate by date)
  const dailyMap = new Map<string, { cost: number; calls: number }>()
  for (const log of allLogs) {
    const date = log.created_at.slice(0, 10)
    const entry = dailyMap.get(date) || { cost: 0, calls: 0 }
    entry.cost += log.cost_usd || 0
    entry.calls += 1
    dailyMap.set(date, entry)
  }
  const dailyCosts = Array.from(dailyMap.entries())
    .map(([date, { cost, calls }]) => ({ date, cost, calls }))
    .sort((a, b) => a.date.localeCompare(b.date))

  // By source
  const sourceMap = new Map<string, { cost: number; calls: number }>()
  for (const log of allLogs) {
    const entry = sourceMap.get(log.source) || { cost: 0, calls: 0 }
    entry.cost += log.cost_usd || 0
    entry.calls += 1
    sourceMap.set(log.source, entry)
  }
  const bySource = Array.from(sourceMap.entries())
    .map(([source, { cost, calls }]) => ({ source, cost, calls }))

  // By model
  const modelMap = new Map<string, { cost: number; calls: number; tokens: number }>()
  for (const log of allLogs) {
    const model = log.model || 'unknown'
    const entry = modelMap.get(model) || { cost: 0, calls: 0, tokens: 0 }
    entry.cost += log.cost_usd || 0
    entry.calls += 1
    entry.tokens += log.total_tokens || 0
    modelMap.set(model, entry)
  }
  const byModel = Array.from(modelMap.entries())
    .map(([model, { cost, calls, tokens }]) => ({ model, cost, calls, tokens }))
    .sort((a, b) => b.cost - a.cost)

  // By pipeline
  const pipelineMap = new Map<string, { cost: number; calls: number; tokens: number }>()
  for (const log of allLogs) {
    const p = log.pipeline || 'unknown'
    const entry = pipelineMap.get(p) || { cost: 0, calls: 0, tokens: 0 }
    entry.cost += log.cost_usd || 0
    entry.calls += 1
    entry.tokens += log.total_tokens || 0
    pipelineMap.set(p, entry)
  }
  const byPipeline = Array.from(pipelineMap.entries())
    .map(([pipeline, { cost, calls, tokens }]) => ({ pipeline, cost, calls, tokens }))
    .sort((a, b) => b.cost - a.cost)

  // Recent 500
  const recent = allLogs.slice(0, 500)

  return NextResponse.json({
    summary: {
      today: todayCost,
      week: weekCost,
      month: monthCost,
      total_calls: totalCalls,
      total_tokens: totalTokens,
    },
    dailyCosts,
    bySource,
    byModel,
    byPipeline,
    recent,
  })
}
