import { Verdict, FitTier, JobAction } from './types'

export const VERDICT_STYLES: Record<Verdict, { bg: string; border: string; text: string; dot: string }> = {
  STRONG:   { bg: 'bg-emerald-950/60', border: 'border-emerald-800',  text: 'text-emerald-400',  dot: 'bg-emerald-400' },
  MODERATE: { bg: 'bg-amber-950/60',   border: 'border-amber-800',    text: 'text-amber-400',    dot: 'bg-amber-400'   },
  STRETCH:  { bg: 'bg-orange-950/60',  border: 'border-orange-800',   text: 'text-orange-400',   dot: 'bg-orange-400'  },
  WEAK:     { bg: 'bg-red-950/60',     border: 'border-red-900',      text: 'text-red-500',      dot: 'bg-red-500'     },
}

export const ACTION_STYLES: Record<JobAction, { bg: string; border: string; text: string; label: string }> = {
  saved:    { bg: 'bg-blue-950/60',    border: 'border-blue-800',    text: 'text-blue-400',    label: 'Saved'    },
  applied:  { bg: 'bg-emerald-950/60', border: 'border-emerald-800', text: 'text-emerald-400', label: 'Applied'  },
  dismissed:{ bg: 'bg-zinc-900/60',    border: 'border-zinc-700',    text: 'text-zinc-500',    label: 'Dismissed'},
}

export const TIER_STYLES: Record<FitTier, { bg: string; border: string; text: string }> = {
  HOT:  { bg: 'bg-emerald-950/60', border: 'border-emerald-800', text: 'text-emerald-400' },
  WARM: { bg: 'bg-amber-950/60',   border: 'border-amber-800',   text: 'text-amber-400'   },
  COLD: { bg: 'bg-zinc-900/60',    border: 'border-zinc-700',    text: 'text-zinc-400'    },
  SKIP: { bg: 'bg-zinc-950/60',    border: 'border-zinc-800',    text: 'text-zinc-600'    },
}

function parseDate(dateStr: string): Date {
  // Full ISO timestamps already have a 'T'; date-only strings need one to avoid UTC midnight shift
  return new Date(dateStr.includes('T') ? dateStr : dateStr + 'T12:00:00')
}

export function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  return parseDate(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function formatRunDate(dateStr: string): string {
  if (!dateStr) return ''
  return parseDate(dateStr).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
}

export function daysAgo(dateStr: string): string {
  const d = parseDate(dateStr)
  const now = new Date()
  const diff = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24))
  if (diff === 0) return 'Today'
  if (diff === 1) return '1 day ago'
  if (diff < 30) return `${diff} days ago`
  if (diff < 60) return '1 month ago'
  return `${Math.floor(diff / 30)} months ago`
}

export function formatFileSize(bytes: number | null): string {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function normalizeLocation(loc: string): string {
  // Match TARGET_CITIES from build_site.py for consistent display
  const lower = loc.toLowerCase()
  if (lower.includes('new york') || lower.includes('nyc') || lower.includes('brooklyn')) return 'NYC'
  if (lower.includes('chicago')) return 'Chicago'
  if (lower.includes('san francisco') || lower.match(/\bsf\b/)) return 'SF'
  if (lower.includes('seattle') || lower.includes('bellevue')) return 'Seattle'
  if (lower.includes('boston') || lower.includes('cambridge')) return 'Boston'
  if (lower.includes('los angeles') || lower.includes('burbank') || lower.includes('hollywood')) return 'LA'
  if (lower.includes('washington') || lower.match(/\bdc\b/) || lower.includes('arlington')) return 'DC'
  if (lower.includes('remote') || lower.includes('anywhere')) return 'Remote'
  return loc
}

export function getSourceLabel(source: string): string {
  const labels: Record<string, string> = {
    serpapi_google_jobs: 'Google Jobs',
    serpapi: 'Google Jobs',
    indeed_rss: 'Indeed RSS',
    indeed: 'Indeed',
    avixa: 'AVIXA',
    career_page: 'Career Page',
    jobspy: 'JobSpy',
    glassdoor: 'Glassdoor',
    google: 'Google',
    zip_recruiter: 'ZipRecruiter',
    linkedin: 'LinkedIn',
  }
  return labels[source] ?? ''
}

export function cn(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(' ')
}

/** Names that are job boards, directories, or marketplaces — not real freelance prospects. */
const JUNK_COMPANY_NAMES = new Set([
  'n/a',
  'none',
  'reddit',
  'productionhub',
  'productionhub.com',
  'upwork',
  'fiverr pro',
  'fiverr',
  'freelancer.com',
  'guru.com',
  'soundbetter',
  'stagelync',
  'airgigs',
  'airgigs.com',
  'creativepool',
  'twine',
  'gigheaven.com',
  'last minute musicians',
  'soundgirls.org',
  'builtin.com',
  'builtinnyc',
  'entertainmentcareers.net',
  'backstage.com',
  'partyslate',
  'clutch.co',
  'spotme',
  'eventective',
  'sharegrid',
  'rent a camera',
])

/** Returns true if a freelance company name looks like junk (job board, directory, marketplace, or placeholder). */
export function isJunkFreelanceCompany(name: string): boolean {
  const lower = name.toLowerCase().trim()
  if (JUNK_COMPANY_NAMES.has(lower)) return true
  // Catch long LLM refusal strings like "The evaluation text does not provide..."
  if (lower.length > 60) return true
  return false
}
