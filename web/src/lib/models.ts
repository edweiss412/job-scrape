// Centralized model IDs for web API routes.
// Override via env vars (set in Vercel / .env.local) or edit config.yaml models section.

export const MODEL_RESUME_EVAL =
  process.env.MODEL_RESUME_EVAL || 'arcee-ai/trinity-large-preview:free'

export const MODEL_INTERVIEW_QA =
  process.env.MODEL_INTERVIEW_QA || 'arcee-ai/trinity-large-preview:free'

export const MODEL_FEEDBACK_TEXT =
  process.env.MODEL_FEEDBACK_TEXT || 'arcee-ai/trinity-large-preview:free'

export const MODEL_FEEDBACK_VISION =
  process.env.MODEL_FEEDBACK_VISION || 'google/gemini-2.5-flash-lite'
