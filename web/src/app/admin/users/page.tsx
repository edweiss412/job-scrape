'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Nav } from '@/components/layout/nav'
import { cn } from '@/lib/utils'
import { ADMIN_EMAIL } from '@/lib/admin'

interface AdminUser {
  id: string
  email: string
  created_at: string
  last_sign_in_at: string | null
  role: string | null
}

export default function AdminUsersPage() {
  const pathname = usePathname()
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState<string | null>(null)

  async function fetchUsers() {
    const res = await fetch('/api/admin/users')
    const data = await res.json()
    setUsers(Array.isArray(data) ? data : [])
    setLoading(false)
  }

  useEffect(() => { fetchUsers() }, [])

  async function toggleRole(userId: string, currentRole: string | null) {
    setToggling(userId)
    const newRole = currentRole === 'beta_tester' ? null : 'beta_tester'
    const res = await fetch(`/api/admin/users/${userId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: newRole }),
    })
    const updated = await res.json()
    setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, role: updated.role } : u))
    setToggling(null)
  }

  function formatDate(dateStr: string | null) {
    if (!dateStr) return '—'
    return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-4xl px-4 py-8">

        {/* Sub-nav */}
        <div className="mb-6 flex items-center gap-1 border-b border-border pb-4">
          <Link href="/admin/feedback" className={cn('rounded-md px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider transition-colors', pathname === '/admin/feedback' ? 'bg-amber-950/40 text-amber-400' : 'text-zinc-600 hover:bg-surface-2 hover:text-zinc-400')}>Feedback</Link>
          <Link href="/admin/users" className={cn('rounded-md px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider transition-colors', pathname === '/admin/users' ? 'bg-amber-950/40 text-amber-400' : 'text-zinc-600 hover:bg-surface-2 hover:text-zinc-400')}>Users</Link>
        </div>

        {/* Header */}
        <div className="mb-6">
          <div className="mb-1 flex items-center gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-widest text-amber-500">Admin</span>
            <span className="font-mono text-[10px] text-zinc-700">/</span>
            <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">Users</span>
          </div>
          <h1 className="text-xl font-bold text-white" style={{ fontFamily: 'Syne, sans-serif' }}>
            User Management
          </h1>
          <p className="mt-0.5 text-sm text-zinc-600">{users.length} users total</p>
        </div>

        {loading ? (
          <div className="py-16 text-center font-mono text-xs text-zinc-700">Loading…</div>
        ) : !users.length ? (
          <div className="rounded-xl border border-border bg-[#111] p-12 text-center text-sm text-zinc-600">
            No users found.
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border bg-[#111]">
            {/* Table header */}
            <div className="grid grid-cols-[1fr_auto_auto_auto] gap-4 border-b border-border px-4 py-2.5">
              <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Email</span>
              <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Joined</span>
              <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Last sign-in</span>
              <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">Role</span>
            </div>

            {/* Rows */}
            {users.map((u, i) => {
              const isAdminRow = u.email === ADMIN_EMAIL
              const isBeta = u.role === 'beta_tester'
              const isTogglingThis = toggling === u.id

              return (
                <div
                  key={u.id}
                  className={cn(
                    'grid grid-cols-[1fr_auto_auto_auto] items-center gap-4 px-4 py-3 transition-colors',
                    i !== users.length - 1 && 'border-b border-border',
                    'hover:bg-[#141414]',
                  )}
                >
                  {/* Email */}
                  <span className="truncate text-sm text-zinc-300">{u.email}</span>

                  {/* Joined */}
                  <span className="shrink-0 font-mono text-[10px] text-zinc-600">{formatDate(u.created_at)}</span>

                  {/* Last sign-in */}
                  <span className="shrink-0 font-mono text-[10px] text-zinc-600">{formatDate(u.last_sign_in_at)}</span>

                  {/* Role + action */}
                  <div className="flex shrink-0 items-center gap-2">
                    {isAdminRow ? (
                      <span className="rounded-full border border-amber-900/50 bg-amber-950/30 px-2 py-0.5 font-mono text-[10px] font-semibold uppercase text-amber-500">
                        admin
                      </span>
                    ) : isBeta ? (
                      <>
                        <span className="rounded-full border border-violet-900/50 bg-violet-950/30 px-2 py-0.5 font-mono text-[10px] font-semibold uppercase text-violet-400">
                          beta
                        </span>
                        <button
                          onClick={() => toggleRole(u.id, u.role)}
                          disabled={isTogglingThis}
                          className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-red-400 disabled:opacity-40"
                        >
                          {isTogglingThis ? '…' : 'Remove'}
                        </button>
                      </>
                    ) : (
                      <>
                        <span className="rounded-full border border-border px-2 py-0.5 font-mono text-[10px] text-zinc-700">
                          —
                        </span>
                        <button
                          onClick={() => toggleRole(u.id, u.role)}
                          disabled={isTogglingThis}
                          className="font-mono text-[10px] text-zinc-600 transition-colors hover:text-violet-400 disabled:opacity-40"
                        >
                          {isTogglingThis ? '…' : 'Make beta'}
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </main>
    </div>
  )
}
