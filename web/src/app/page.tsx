import { Suspense } from 'react'
import { createClient } from '@/lib/supabase/server'
import { DashboardHero } from '@/components/dashboard/DashboardHero'
import { DashboardCards } from '@/components/dashboard/DashboardCards'
import { DashboardTopMatches } from '@/components/dashboard/DashboardTopMatches'
import { HeroSkeleton, CardsSkeleton, TopMatchesSkeleton } from '@/components/dashboard/skeletons'

export default async function DashboardPage() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const userId = user?.id ?? null

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:py-14">
      <Suspense fallback={<HeroSkeleton />}>
        <DashboardHero userId={userId} userEmail={user?.email ?? null} />
      </Suspense>

      <Suspense fallback={<CardsSkeleton />}>
        <DashboardCards userId={userId} />
      </Suspense>

      <Suspense fallback={<TopMatchesSkeleton />}>
        <DashboardTopMatches />
      </Suspense>
    </main>
  )
}
