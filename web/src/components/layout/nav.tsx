'use client'

import Link from 'next/link'
import { useState, useEffect } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { ADMIN_EMAIL } from '@/lib/admin'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { label: 'Runs',      href: '/runs' },
  { label: 'All Jobs',  href: '/jobs' },
  { label: 'Freelance', href: '/freelance' },
  { label: 'Profile',   href: '/profile' },
]

export function Nav() {
  const pathname = usePathname()
  const router = useRouter()
  const [isAdmin, setIsAdmin] = useState(false)

  useEffect(() => {
    createClient()
      .auth.getUser()
      .then(({ data }) => setIsAdmin(data.user?.email === ADMIN_EMAIL))
  }, [])

  async function handleSignOut() {
    const supabase = createClient()
    await supabase.auth.signOut()
    router.push('/login')
    router.refresh()
  }

  return (
    <header className="sticky top-0 z-50 border-b border-[#1f1f1f] bg-[#0a0a0a]/90 backdrop-blur-sm">
      <div className="mx-auto flex h-12 max-w-7xl items-center justify-between px-4">
        {/* Logo */}
        <Link href="/runs" className="flex items-center gap-2">
          <span
            className="font-display text-sm font-700 tracking-tight text-white"
            style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700 }}
          >
            Job Scout
          </span>
        </Link>

        {/* Nav links */}
        <nav className="flex items-center gap-1">
          {NAV_ITEMS.map((item) => {
            const active = pathname === item.href || pathname.startsWith(item.href + '/')
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                  active
                    ? 'bg-[#1f1f1f] text-white'
                    : 'text-zinc-500 hover:text-zinc-300 hover:bg-[#161616]',
                )}
              >
                {item.label}
              </Link>
            )
          })}
          {isAdmin && (
            <Link
              href="/admin/feedback"
              className={cn(
                'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                pathname.startsWith('/admin')
                  ? 'bg-amber-950/40 text-amber-400'
                  : 'text-zinc-700 hover:bg-[#161616] hover:text-zinc-400',
              )}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
              Admin
            </Link>
          )}
        </nav>

        {/* Sign out */}
        <button
          onClick={handleSignOut}
          className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
        >
          Sign out
        </button>
      </div>
    </header>
  )
}
