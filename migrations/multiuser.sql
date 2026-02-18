-- Multi-user architecture migrations
-- Run each section in order in the Supabase SQL editor.
-- After running migrate_to_multiuser.py, apply the UNIQUE constraint at the bottom.

-- ============================================================
-- 1A: user_profiles table
-- ============================================================
CREATE TABLE IF NOT EXISTS user_profiles (
  user_id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  target_roles     TEXT[] NOT NULL DEFAULT ARRAY['audio engineer', 'av technician'],
  target_locations TEXT[] NOT NULL DEFAULT ARRAY['Chicago, IL', 'Remote'],
  candidate_context TEXT,
  notify_email     TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own profile" ON user_profiles
  FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- ============================================================
-- 1B: user_evaluations table
-- ============================================================
CREATE TABLE IF NOT EXISTS user_evaluations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  job_id          VARCHAR(12) NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
  match_score     FLOAT,
  match_verdict   VARCHAR(20),
  match_reasoning TEXT,
  job_summary     TEXT,
  full_evaluation TEXT,
  deep_evaluation TEXT,
  evaluated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_ue_user ON user_evaluations(user_id);
CREATE INDEX IF NOT EXISTS idx_ue_job  ON user_evaluations(job_id);
ALTER TABLE user_evaluations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own evals" ON user_evaluations
  FOR SELECT USING (auth.uid() = user_id);
-- Service role needs INSERT/UPDATE from the scraper
CREATE POLICY "service insert evals" ON user_evaluations
  FOR INSERT WITH CHECK (true);
CREATE POLICY "service update evals" ON user_evaluations
  FOR UPDATE USING (true);

-- ============================================================
-- 1C: Add user_id to runs (nullable first)
-- ============================================================
ALTER TABLE runs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_runs_user ON runs(user_id);
ALTER TABLE runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own runs" ON runs
  FOR SELECT USING (auth.uid() = user_id);
-- Service role needs full access for the scraper
CREATE POLICY "service all runs" ON runs
  FOR ALL USING (auth.role() = 'service_role');

-- ============================================================
-- 1D: Add user_id to interview_qa
-- ============================================================
ALTER TABLE interview_qa ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_qa_user ON interview_qa(user_id);
ALTER TABLE interview_qa ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own qa" ON interview_qa
  FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- ============================================================
-- 1E: RLS on jobs (shared read-only catalog for all authenticated users)
-- ============================================================
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "auth users read jobs" ON jobs
  FOR SELECT USING (auth.role() = 'authenticated');
-- Service role needs INSERT/UPDATE from scraper
CREATE POLICY "service all jobs" ON jobs
  FOR ALL USING (auth.role() = 'service_role');

-- ============================================================
-- 1F: RLS on run_jobs (access via runs.user_id)
-- ============================================================
ALTER TABLE run_jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own run_jobs" ON run_jobs
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM runs r
      WHERE r.id = run_jobs.run_id AND r.user_id = auth.uid()
    )
  );
-- Service role needs INSERT from scraper
CREATE POLICY "service all run_jobs" ON run_jobs
  FOR ALL USING (auth.role() = 'service_role');

-- ============================================================
-- POST-MIGRATION: Apply UNIQUE constraint on runs
-- Run this AFTER running migrate_to_multiuser.py
-- ============================================================
-- ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_run_date_key;
-- ALTER TABLE runs ADD CONSTRAINT runs_user_run_date_key UNIQUE (user_id, run_date);
