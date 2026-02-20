import { createServiceClient } from '@/lib/supabase/server'

interface LogParams {
  source: 'web' | 'pipeline' | 'external'
  category: 'llm' | 'search_api' | 'dataset_api'
  operation: string
  provider?: string
  model?: string
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  cost_usd?: number
  latency_ms?: number
  user_id?: string
  http_status?: number
  success?: boolean
  metadata?: Record<string, unknown>
}

/** Fire-and-forget insert to api_usage_log. Never throws. */
export function logApiUsage(params: LogParams): void {
  try {
    const supabase = createServiceClient()
    const row = {
      source: params.source,
      category: params.category,
      operation: params.operation,
      provider: params.provider ?? null,
      model: params.model ?? null,
      prompt_tokens: params.prompt_tokens ?? null,
      completion_tokens: params.completion_tokens ?? null,
      total_tokens: params.total_tokens ?? null,
      cost_usd: params.cost_usd ?? null,
      latency_ms: params.latency_ms ?? null,
      user_id: params.user_id ?? null,
      http_status: params.http_status ?? null,
      success: params.success ?? true,
      metadata: params.metadata ?? null,
    }
    // Fire-and-forget — don't await
    supabase.from('api_usage_log').insert(row).then(() => {})
  } catch {
    // never block the caller
  }
}

/** Extract usage info from an OpenRouter response body. */
export function extractOpenRouterUsage(llmData: Record<string, unknown>): {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  cost_usd?: number
} {
  const usage = llmData.usage as Record<string, unknown> | undefined
  if (!usage) return {}

  const prompt_tokens = typeof usage.prompt_tokens === 'number' ? usage.prompt_tokens : undefined
  const completion_tokens = typeof usage.completion_tokens === 'number' ? usage.completion_tokens : undefined
  const total_tokens = typeof usage.total_tokens === 'number' ? usage.total_tokens : undefined

  // OpenRouter returns cost in the usage.cost field (in dollars) or native_tokens_cost
  let cost_usd: number | undefined
  if (typeof usage.cost === 'number') {
    cost_usd = usage.cost
  } else if (typeof (llmData as Record<string, unknown>).cost === 'number') {
    cost_usd = (llmData as Record<string, unknown>).cost as number
  }

  return { prompt_tokens, completion_tokens, total_tokens, cost_usd }
}
