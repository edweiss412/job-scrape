export const ADMIN_EMAIL = 'edweiss412@gmail.com'

export function isAdmin(email: string | null | undefined): boolean {
  return email === ADMIN_EMAIL
}

export function isBetaTester(user: { email?: string | null; app_metadata?: Record<string, unknown> } | null): boolean {
  if (!user || user.email === ADMIN_EMAIL) return false
  return user.app_metadata?.role === 'beta_tester'
}

export function canSubmitFeedback(user: { email?: string | null; app_metadata?: Record<string, unknown> } | null): boolean {
  if (!user) return false
  return isAdmin(user.email) || isBetaTester(user)
}
