export default function FullTimeLoading() {
  return (
      <main className="mx-auto w-full max-w-7xl px-4 py-5 sm:py-8">
        {/* Page header */}
        <div className="mb-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="h-7 w-28 animate-pulse rounded bg-zinc-800/40" />
            <div className="flex items-center gap-2">
              <div className="h-8 w-24 animate-pulse rounded-lg bg-zinc-800/30" />
              <div className="h-8 w-32 animate-pulse rounded-lg bg-zinc-800/30" />
            </div>
          </div>
        </div>

        {/* Status bar placeholder */}
        <div className="mb-4 h-10 w-full animate-pulse rounded-lg bg-zinc-900/40" />

        {/* Job grid skeleton */}
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
      </main>
  )
}
