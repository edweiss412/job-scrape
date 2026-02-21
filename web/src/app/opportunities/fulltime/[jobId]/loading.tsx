export default function JobDetailLoading() {
  return (
      <main className="mx-auto w-full max-w-4xl px-4 py-5 sm:py-8">
        {/* Back link */}
        <div className="mb-6 h-4 w-20 animate-pulse rounded bg-zinc-900/40" />

        {/* Job header card */}
        <div className="mb-4 rounded-xl border border-border bg-[#111] p-4 sm:p-5">
          <div className="flex items-start gap-4">
            <div className="min-w-0 flex-1">
              <div className="mb-2 h-6 w-3/4 animate-pulse rounded bg-zinc-800/40" />
              <div className="h-4 w-1/3 animate-pulse rounded bg-zinc-900/60" />
              <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5">
                <div className="h-3 w-24 animate-pulse rounded bg-zinc-900/40" />
                <div className="h-3 w-20 animate-pulse rounded bg-zinc-900/40" />
                <div className="h-3 w-16 animate-pulse rounded bg-zinc-900/40" />
              </div>
            </div>
            {/* Score ring placeholder */}
            <div className="h-14 w-14 shrink-0 animate-pulse rounded-full bg-zinc-800/30" />
          </div>

          {/* Summary */}
          <div className="mt-3 border-t border-[#ffffff06] pt-3">
            <div className="h-4 w-full animate-pulse rounded bg-zinc-900/30" />
            <div className="mt-1.5 h-4 w-2/3 animate-pulse rounded bg-zinc-900/30" />
          </div>

          {/* Actions row */}
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[#ffffff06] pt-3">
            <div className="h-8 w-20 animate-pulse rounded-lg bg-zinc-800/30" />
            <div className="h-8 w-24 animate-pulse rounded-lg bg-zinc-800/30" />
            <div className="flex-1" />
            <div className="h-8 w-28 animate-pulse rounded-lg bg-zinc-800/30" />
          </div>
        </div>

        {/* Evaluation skeleton */}
        <div className="mb-3 rounded-xl border border-border bg-[#111] p-4 sm:p-5">
          <div className="space-y-4">
            <div className="h-4 w-40 animate-pulse rounded bg-zinc-800/50" />
            <div className="space-y-2">
              <div className="h-3 w-full animate-pulse rounded bg-zinc-900/40" />
              <div className="h-3 w-full animate-pulse rounded bg-zinc-900/40" />
              <div className="h-3 w-5/6 animate-pulse rounded bg-zinc-900/40" />
              <div className="h-3 w-2/3 animate-pulse rounded bg-zinc-900/40" />
            </div>
            <div className="h-4 w-32 animate-pulse rounded bg-zinc-800/50" />
            <div className="space-y-2">
              <div className="h-3 w-full animate-pulse rounded bg-zinc-900/40" />
              <div className="h-3 w-4/5 animate-pulse rounded bg-zinc-900/40" />
              <div className="h-3 w-full animate-pulse rounded bg-zinc-900/40" />
            </div>
            <div className="h-4 w-36 animate-pulse rounded bg-zinc-800/50" />
            <div className="space-y-2">
              <div className="h-3 w-full animate-pulse rounded bg-zinc-900/40" />
              <div className="h-3 w-3/4 animate-pulse rounded bg-zinc-900/40" />
            </div>
          </div>
        </div>
      </main>
  )
}
