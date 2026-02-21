export default function DashboardLoading() {
  return (
      <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:py-14">
        {/* Hero */}
        <div className="mb-10 sm:mb-14">
          <div className="mb-3 h-3 w-16 animate-pulse rounded bg-zinc-800/60" />
          <div className="h-8 w-64 animate-pulse rounded bg-zinc-800/40" />
          <div className="mt-2 h-4 w-40 animate-pulse rounded bg-zinc-900/60" />
        </div>

        {/* Channel cards */}
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

        {/* Top matches */}
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
      </main>
  )
}
