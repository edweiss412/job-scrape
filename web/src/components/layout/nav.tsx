'use client'

import Link from 'next/link'
import { useState, useEffect, useRef } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { ADMIN_EMAIL } from '@/lib/admin'
import { cn } from '@/lib/utils'

const OPPORTUNITIES_ITEMS = [
  { label: 'Full Time',  href: '/opportunities/fulltime' },
  { label: 'Freelance',  href: '/opportunities/freelance' },
]

const OTHER_NAV_ITEMS = [
  { label: 'Profile', href: '/profile' },
]

export function Nav() {
  const pathname = usePathname()
  const router = useRouter()
  const [isAdmin, setIsAdmin] = useState(false)
  const [oppsOpen, setOppsOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    createClient()
      .auth.getUser()
      .then(({ data }) => setIsAdmin(data.user?.email === ADMIN_EMAIL))
  }, [])

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOppsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // Close dropdown on route change
  useEffect(() => { setOppsOpen(false) }, [pathname])

  async function handleSignOut() {
    const supabase = createClient()
    await supabase.auth.signOut()
    router.push('/login')
    router.refresh()
  }

  const oppsActive = pathname.startsWith('/opportunities')

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/90 backdrop-blur-sm">
      <div className="mx-auto flex h-12 max-w-7xl items-center justify-between px-4">
        {/* Logo */}
        <Link href="/opportunities/fulltime" className="flex items-center gap-2">
          <span
            className="font-display text-sm font-700 tracking-tight text-white"
            style={{ fontFamily: 'Syne, sans-serif', fontWeight: 700 }}
          >
            Job Scout
          </span>
        </Link>

        {/* Nav links */}
        <nav className="flex items-center gap-1">
          {/* Opportunities dropdown */}
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setOppsOpen((o) => !o)}
              className={cn(
                'flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                oppsActive
                  ? 'bg-border text-white'
                  : 'text-zinc-500 hover:text-zinc-300 hover:bg-surface-2',
              )}
            >
              Opportunities
              <svg
                className={cn('h-3 w-3 transition-transform', oppsOpen && 'rotate-180')}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {oppsOpen && (
              <div className="absolute left-0 top-full mt-1 min-w-[140px] rounded-lg border border-border bg-[#111] py-1 shadow-xl">
                {OPPORTUNITIES_ITEMS.map((item) => {
                  const active = pathname.startsWith(item.href)
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={cn(
                        'block px-3 py-1.5 text-xs font-medium transition-colors',
                        active
                          ? 'text-white bg-border'
                          : 'text-zinc-500 hover:text-zinc-300 hover:bg-surface-2',
                      )}
                    >
                      {item.label}
                    </Link>
                  )
                })}
              </div>
            )}
          </div>

          {OTHER_NAV_ITEMS.map((item) => {
            const active = pathname === item.href || pathname.startsWith(item.href + '/')
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                  active
                    ? 'bg-border text-white'
                    : 'text-zinc-500 hover:text-zinc-300 hover:bg-surface-2',
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
                  : 'text-zinc-700 hover:bg-surface-2 hover:text-zinc-400',
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
