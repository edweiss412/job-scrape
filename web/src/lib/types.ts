export type Verdict = 'STRONG' | 'MODERATE' | 'STRETCH' | 'WEAK'
export type FitTier = 'HOT' | 'WARM' | 'COLD' | 'SKIP'
export type FeedbackType = 'bug' | 'feature'
export type FeedbackStatus = 'open' | 'in_progress' | 'done'
export type FeedbackPriority = 'low' | 'medium' | 'high'

export interface Feedback {
  id: string
  type: FeedbackType
  title: string
  description: string
  priority: FeedbackPriority
  status: FeedbackStatus
  page_url: string | null
  steps_to_reproduce: string | null
  expected_behavior: string | null
  actual_behavior: string | null
  use_case: string | null
  user_impact: string | null
  reporter_email: string | null
  screenshot_url: string | null
  created_at: string
  updated_at: string
}

export interface Run {
  id: string
  run_date: string          // "2026-02-17"
  resume_id: string | null
  user_id: string | null
  total_jobs: number
  evaluated: number
  strong_count: number
  moderate_count: number
  stretch_count: number
  weak_count: number
  new_job_ids: string[]
  sources: string[] | null
  created_at: string
}

export type ListingStatus = 'active' | 'expired' | 'removed'

export interface Job {
  id: string
  job_id: string            // MD5 hash, the canonical dedup key
  title: string
  company: string
  location: string
  url: string
  source: string
  salary: string | null
  date_posted: string | null
  tier: string | null
  description: string | null
  description_length: number | null
  listing_status: ListingStatus
  listing_expired_at: string | null
  last_verified_at: string | null
  pre_filter_score: number | null
  pre_filter_passed: boolean | null
  title_keywords: string[] | null
  match_score: number | null
  match_verdict: Verdict | null
  match_reasoning: string | null
  job_summary: string | null
  full_evaluation: string | null
  deep_evaluation: string | null
  first_seen_run: string | null
  last_seen_run: string | null
  archived_at: string | null
  first_seen_date: string
  last_seen_date: string
  date_scraped: string
  created_at: string
  updated_at: string
}

export interface ScrapeRun {
  id: string
  run_date: string
  total_scraped: number
  new_jobs: number
  sources: string[]
  expired_checked: number | null
  expired_found: number | null
  pre_filter_stats: {
    total?: number
    passed?: number
    failed?: number
    llm_called?: number
  } | null
  created_at: string
}

export interface RunJob {
  run_id: string
  job_id_ref: string
  is_new_this_run: boolean
}

// Job with the is_new_this_run flag joined from run_jobs
export interface JobWithRunMeta extends Job {
  is_new_this_run?: boolean
}

export interface Resume {
  id: string
  user_id: string
  name: string
  is_primary: boolean
  file_path: string         // Storage path: "{id}/{filename}"
  file_name: string         // Original filename
  file_size: number | null
  content_text: string | null
  resume_evaluation: string | null
  resume_evaluated_at: string | null
  created_at: string
  updated_at: string
}

export type QACategory = 'technical' | 'behavioral' | 'situational' | 'general'
export type QASource = 'manual' | 'ai_generated'

export interface InterviewQA {
  id: string
  user_id: string
  question: string
  answer: string | null
  category: QACategory | null
  source: QASource
  created_at: string
  updated_at: string
}

export interface UserEvaluation {
  id: string
  user_id: string
  job_id: string
  match_score: number | null
  match_verdict: Verdict | null
  match_reasoning: string | null
  job_summary: string | null
  full_evaluation: string | null
  deep_evaluation: string | null
  evaluated_at: string
}

export type EvalStatus = 'idle' | 'pending' | 'running' | 'completed' | 'error'

export interface UserProfile {
  user_id: string
  target_roles: string[]
  target_locations: string[]
  candidate_context: string | null
  notify_email: string | null
  home_city: string | null
  current_income: number | null
  full_name: string | null
  phone: string | null
  linkedin_url: string | null
  professional_title: string | null
  eval_status: EvalStatus
  eval_started_at: string | null
  eval_completed_at: string | null
  eval_job_count: number | null
  created_at: string
  updated_at: string
}

export interface FreelanceCompany {
  id: string
  company_id: string
  name: string
  city: string
  state: string | null
  website: string | null
  category: string | null
  // Catalog/discovery data
  recent_activity: string | null
  scale_signals: string | null
  notable_clients: string | null
  gear_mentioned: string | null
  website_about: string | null
  logo_url: string | null
  archived_at: string | null
  first_seen_date: string
  last_seen_date: string
  created_at: string
  updated_at: string
  // Legacy eval fields (still on freelance_companies during transition)
  relationship: string | null
  relationship_notes: string | null
  fit_tier: FitTier | null
  fit_score: number | null
  fit_reasoning: string | null
  full_evaluation: string | null
  outreach_draft: string | null
  outreach_subject: string | null
}

export interface UserFreelanceEvaluation {
  id: string
  user_id: string
  company_id: string
  fit_tier: FitTier | null
  fit_score: number | null
  geographic_fit: number | null
  scale_gear: number | null
  work_type: number | null
  relationship_potential: number | null
  credibility: number | null
  geographic_fit_rationale: string | null
  scale_gear_rationale: string | null
  work_type_rationale: string | null
  relationship_potential_rationale: string | null
  credibility_rationale: string | null
  fit_reasoning: string | null
  full_evaluation: string | null
  outreach_draft: string | null
  outreach_subject: string | null
  relationship: string | null
  relationship_notes: string | null
  created_at: string
  updated_at: string
}

/** FreelanceCompany with per-user evaluation data joined */
export interface FreelanceCompanyWithEval extends FreelanceCompany {
  user_eval?: UserFreelanceEvaluation | null
}

export interface TailoringSuggestion {
  id: string
  type: 'rewrite' | 'add' | 'remove'
  section: string
  before?: string
  after: string
  reasoning: string
  priority: 'high' | 'medium' | 'low'
}

export interface TailoringSuggestionsResponse {
  summary: string
  ats_keywords: string[]
  suggestions: TailoringSuggestion[]
}

export interface TailoringQuestion {
  id: string
  question: string
  context: string  // why this question matters
  placeholder?: string  // example answer hint
}

export type RelevanceTier = 'HOT' | 'WARM' | 'COLD'

export interface FacebookPost {
  id: string
  fb_post_hash: string
  post_id: string
  group_name: string | null
  group_url: string | null
  content: string | null
  date_posted: string | null
  author_username: string | null
  post_url: string | null
  matched_keywords: string[]
  relevance_tier: RelevanceTier | null
  relevance_score: number | null
  relevance_reasoning: string | null
  gig_summary: string | null
  location_mentioned: string | null
  date_mentioned: string | null
  pay_mentioned: string | null
  alert_sent: boolean
  first_seen_date: string
  last_seen_date: string
  created_at: string
  updated_at: string
}

// API usage logging
export interface ApiUsageLog {
  id: string
  created_at: string
  source: string          // 'web' | 'pipeline' | 'external'
  category: string        // 'llm' | 'search_api' | 'dataset_api'
  pipeline: string | null // 'job_scraper' | 'freelance_finder' | 'facebook_monitor' | 'web_app'
  operation: string       // e.g. 'resume_eval', 'serpapi_search'
  provider: string | null
  model: string | null
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  cost_usd: number | null
  latency_ms: number | null
  user_id: string | null
  http_status: number | null
  success: boolean
  metadata: Record<string, unknown> | null
}

export interface CostBucket {
  label: string
  value: number
}

export interface CostSummary {
  buckets: CostBucket[]
  total_calls: number
  total_tokens: number
}

export interface DailyCost {
  date: string
  cost: number
  calls: number
}

export interface SourceBreakdown {
  source: string
  cost: number
  calls: number
}

export interface ModelBreakdown {
  model: string
  cost: number
  calls: number
  tokens: number
}

export interface PipelineBreakdown {
  pipeline: string
  cost: number
  calls: number
  tokens: number
}

export interface UserBreakdown {
  user_id: string
  email: string
  cost: number
  calls: number
  tokens: number
}

/** Lightweight row for aggregation (no metadata JSONB) */
export interface AggLogRow {
  created_at: string
  source: string
  category: string
  pipeline: string | null
  model: string | null
  user_id: string | null
  cost_usd: number | null
  total_tokens: number | null
  prompt_tokens: number | null
  completion_tokens: number | null
  latency_ms: number | null
  success: boolean
}

/** Raw API response from /api/admin/costs */
export interface CostDashboardData {
  agg: AggLogRow[]           // ALL rows (lightweight, no limit)
  recent: ApiUsageLog[]      // Most recent 500 (full data for activity table)
  users: { id: string; email: string }[]
  // Legacy fields kept for type compat
  summary?: CostSummary
  dailyCosts?: DailyCost[]
  bySource?: SourceBreakdown[]
  byModel?: ModelBreakdown[]
  byPipeline?: PipelineBreakdown[]
  byUser?: UserBreakdown[]
}

// Aggregated counts for a freelance run (derived from freelance_companies)
export interface FreelanceRunSummary {
  run_date: string
  hot_count: number
  warm_count: number
  cold_count: number
  total: number
}
