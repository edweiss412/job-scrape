export function HeroSkeleton() {
  return (
    <div className="mb-10 sm:mb-14">
      <div className="mb-3 h-3 w-16 animate-pulse rounded bg-zinc-800/60" />
      <div className="h-8 w-64 animate-pulse rounded bg-zinc-800/40" />
      <div className="mt-2 h-4 w-40 animate-pulse rounded bg-zinc-900/60" />
    </div>
  )
}

export function CardsSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-3 sm:gap-5">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="relative overflow-hidden rounded-xl border border-border bg-[#111] p-6"
        >
          <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-zinc-700/40 to-transparent" />
          <div className="mb-5 flex items-center justify-between">
            <div className="h-3 w-16 animate-pulse rounded bg-zinc-800/60" />
            <div className="h-4 w-4 animate-pulse rounded bg-zinc-900" />
          </div>
          <div className="mb-4">
            <div className="h-10 w-12 animate-pulse rounded bg-zinc-800/40" />
          </div>
          <div className="space-y-2">
            <div className="h-3 w-full animate-pulse rounded bg-zinc-900/60" />
            <div className="h-3 w-3/4 animate-pulse rounded bg-zinc-900/60" />
            <div className="h-3 w-1/2 animate-pulse rounded bg-zinc-900/60" />
          </div>
          <div className="mt-4 h-1 w-full animate-pulse rounded-full bg-zinc-900" />
        </div>
      ))}
    </div>
  )
}

export function TopMatchesSkeleton() {
  return (
    <div className="mt-10 sm:mt-14">
      <div className="mb-5 flex items-center justify-between">
        <div className="h-3 w-24 animate-pulse rounded bg-zinc-800/60" />
        <div className="h-3 w-16 animate-pulse rounded bg-zinc-900/60" />
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="rounded-xl border border-border bg-[#111] p-5"
          >
            <div className="mb-3 flex items-center gap-2">
              <div className="h-5 w-5 animate-pulse rounded-full bg-zinc-800/60" />
              <div className="h-4 w-10 animate-pulse rounded-full bg-zinc-800/40" />
            </div>
            <div className="mb-1 h-4 w-3/4 animate-pulse rounded bg-zinc-800/40" />
            <div className="mb-2 h-3 w-1/2 animate-pulse rounded bg-zinc-900/60" />
            <div className="h-3 w-full animate-pulse rounded bg-zinc-900/40" />
          </div>
        ))}
      </div>
    </div>
  )
}

export function JobGridSkeleton() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 9 }).map((_, i) => (
        <div
          key={i}
          className="rounded-xl border border-border bg-[#111] p-4"
          style={{ animationDelay: `${i * 50}ms` }}
        >
          <div className="mb-3 flex items-center justify-between">
            <div className="h-5 w-14 animate-pulse rounded-full bg-zinc-800/50" />
            <div className="h-4 w-8 animate-pulse rounded bg-zinc-900/60" />
          </div>
          <div className="mb-1.5 h-4 w-4/5 animate-pulse rounded bg-zinc-800/40" />
          <div className="mb-3 h-3 w-1/2 animate-pulse rounded bg-zinc-900/60" />
          <div className="flex items-center gap-3 text-xs">
            <div className="h-3 w-20 animate-pulse rounded bg-zinc-900/40" />
            <div className="h-3 w-16 animate-pulse rounded bg-zinc-900/40" />
          </div>
          <div className="mt-3 space-y-1.5">
            <div className="h-3 w-full animate-pulse rounded bg-zinc-900/30" />
            <div className="h-3 w-2/3 animate-pulse rounded bg-zinc-900/30" />
          </div>
        </div>
      ))}
    </div>
  )
}

export function FreelanceGridSkeleton() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 9 }).map((_, i) => (
        <div
          key={i}
          className="rounded-xl border border-border bg-[#111] p-4"
          style={{ animationDelay: `${i * 50}ms` }}
        >
          <div className="mb-3 flex items-center justify-between">
            <div className="h-5 w-12 animate-pulse rounded-full bg-zinc-800/50" />
            <div className="h-4 w-10 animate-pulse rounded bg-zinc-900/60" />
          </div>
          <div className="mb-2 flex items-center gap-2.5">
            <div className="h-8 w-8 animate-pulse rounded-lg bg-zinc-800/40" />
            <div>
              <div className="mb-1 h-4 w-32 animate-pulse rounded bg-zinc-800/40" />
              <div className="h-3 w-20 animate-pulse rounded bg-zinc-900/60" />
            </div>
          </div>
          <div className="mt-3 space-y-1.5">
            <div className="h-3 w-full animate-pulse rounded bg-zinc-900/30" />
            <div className="h-3 w-3/4 animate-pulse rounded bg-zinc-900/30" />
          </div>
        </div>
      ))}
    </div>
  )
}
