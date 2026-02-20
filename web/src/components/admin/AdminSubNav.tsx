'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'

const ADMIN_TABS = [
  { href: '/admin/feedback', label: 'Feedback' },
  { href: '/admin/users', label: 'Users' },
  { href: '/admin/scans', label: 'Scans' },
  { href: '/admin/costs', label: 'Costs' },
]

export function AdminSubNav() {
  const pathname = usePathname()

  return (
    <div className="mb-6 flex items-center gap-1 border-b border-border pb-4">
      {ADMIN_TABS.map((tab) => (
        <Link
          key={tab.href}
          href={tab.href}
          className={cn(
            'rounded-md px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider transition-colors',
            pathname === tab.href
              ? 'bg-amber-950/40 text-amber-400'
              : 'text-zinc-600 hover:bg-surface-2 hover:text-zinc-400',
          )}
        >
          {tab.label}
        </Link>
      ))}
    </div>
  )
}
