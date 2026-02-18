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
  created_at: string
  updated_at: string
}

export interface Run {
  id: string
  run_date: string          // "2026-02-17"
  resume_id: string | null
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
  match_score: number | null
  match_verdict: Verdict | null
  match_reasoning: string | null
  job_summary: string | null
  full_evaluation: string | null
  deep_evaluation: string | null
  first_seen_run: string | null
  last_seen_run: string | null
  first_seen_date: string
  last_seen_date: string
  date_scraped: string
  created_at: string
  updated_at: string
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
  name: string
  is_primary: boolean
  file_path: string         // Storage path: "{id}/{filename}"
  file_name: string         // Original filename
  file_size: number | null
  content_text: string | null
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
  relationship: string | null
  relationship_notes: string | null
  fit_tier: FitTier | null
  fit_score: number | null
  fit_reasoning: string | null
  full_evaluation: string | null
  outreach_draft: string | null
  outreach_subject: string | null
  first_seen_date: string
  last_seen_date: string
  created_at: string
  updated_at: string
}

// Aggregated counts for a freelance run (derived from freelance_companies)
export interface FreelanceRunSummary {
  run_date: string
  hot_count: number
  warm_count: number
  cold_count: number
  total: number
}
