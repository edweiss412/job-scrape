export const ADMIN_EMAIL = 'edweiss412@gmail.com'

export function isAdmin(email: string | null | undefined): boolean {
  return email === ADMIN_EMAIL
}
