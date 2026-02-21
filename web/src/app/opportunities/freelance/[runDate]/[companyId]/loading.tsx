export default function CompanyDetailLoading() {
  return (
      <main className="mx-auto w-full max-w-4xl px-4 py-8">
        {/* Back link */}
        <div className="mb-6 h-4 w-24 animate-pulse rounded bg-zinc-900/40" />

        {/* Company header card */}
        <div className="mb-6 rounded-xl border border-border bg-[#111] p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="mb-2 flex items-center gap-2">
                <div className="h-5 w-12 animate-pulse rounded-full bg-zinc-800/50" />
                <div className="h-4 w-10 animate-pulse rounded bg-zinc-900/60" />
              </div>
              <div className="flex items-center gap-3">
                <div className="h-12 w-12 animate-pulse rounded-xl bg-zinc-800/40" />
                <div>
                  <div className="mb-1 h-6 w-48 animate-pulse rounded bg-zinc-800/40" />
                  <div className="h-4 w-32 animate-pulse rounded bg-zinc-900/60" />
                </div>
              </div>
            </div>
            <div className="h-9 w-24 animate-pulse rounded-lg bg-zinc-800/30" />
          </div>
        </div>

        {/* Info cards */}
        <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="rounded-xl border border-border bg-[#111] p-4">
              <div className="mb-2 h-3 w-24 animate-pulse rounded bg-zinc-800/60" />
              <div className="flex flex-wrap gap-1.5">
                <div className="h-5 w-16 animate-pulse rounded-md bg-zinc-900/50" />
                <div className="h-5 w-20 animate-pulse rounded-md bg-zinc-900/50" />
                <div className="h-5 w-14 animate-pulse rounded-md bg-zinc-900/50" />
              </div>
            </div>
          ))}
        </div>

        {/* Evaluation skeleton */}
        <div className="mb-4 rounded-xl border border-border bg-[#111] p-6">
          <div className="space-y-4">
            <div className="h-4 w-40 animate-pulse rounded bg-zinc-800/50" />
            <div className="space-y-2">
              <div className="h-3 w-full animate-pulse rounded bg-zinc-900/40" />
              <div className="h-3 w-full animate-pulse rounded bg-zinc-900/40" />
              <div className="h-3 w-5/6 animate-pulse rounded bg-zinc-900/40" />
              <div className="h-3 w-2/3 animate-pulse rounded bg-zinc-900/40" />
            </div>
          </div>
        </div>
      </main>
  )
}
