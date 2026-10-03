interface LoadingCardProps {
  delay?: number
}

export default function LoadingCard({ delay = 0 }: LoadingCardProps) {
  const style = (extraDelay = 0) => ({
    animationDelay: `${delay + extraDelay}ms`,
  })

  return (
    <div
      className="flex flex-col h-full bg-card rounded-2xl border border-border overflow-hidden"
      aria-hidden="true"
    >
      {/* Photo stage + rating plate */}
      <div className="relative aspect-[4/3] overflow-hidden">
        <div className="shimmer absolute inset-0" style={style(0)} />
        <div className="absolute top-3 left-3 flex items-baseline gap-1.5 px-2.5 pt-1.5 pb-1 bg-parchment border border-charcoal/10 rounded-[0.55rem]">
          <b className="font-display font-extrabold text-[1.9rem] leading-[0.9] text-muted">—</b>
          <span className="font-display font-semibold text-[0.95rem] text-muted">/ 10</span>
        </div>
      </div>

      <div className="flex flex-col gap-2 flex-1 p-4 pb-5">
        <div className="shimmer h-4 w-20 rounded" style={style(80)} />
        <div className="shimmer h-7 w-44 rounded-lg" style={style(110)} />
        <div className="space-y-1.5 mt-1">
          <div className="shimmer h-4 w-full rounded" style={style(210)} />
          <div className="shimmer h-4 w-4/5 rounded" style={style(240)} />
        </div>
      </div>
    </div>
  )
}
