interface LoadingCardProps {
  delay?: number
}

export default function LoadingCard({ delay = 0 }: LoadingCardProps) {
  const style = (extraDelay = 0) => ({
    animationDelay: `${delay + extraDelay}ms`,
  })

  return (
    <div
      className="bg-card rounded-2xl border border-border p-6 md:p-8"
      aria-hidden="true"
    >
      <div className="flex gap-5 md:gap-8 items-start">
        {/* Score skeleton */}
        <div className="shrink-0">
          <div className="shimmer w-20 h-14 md:w-24 md:h-16 rounded-lg" style={style(0)} />
          <div className="shimmer w-8 h-3 rounded mt-2" style={style(60)} />
        </div>

        {/* Content skeleton */}
        <div className="flex-1 pt-1 min-w-0">
          {/* Brand */}
          <div className="shimmer h-6 w-36 rounded-lg" style={style(80)} />
          {/* Model */}
          <div className="shimmer h-4 w-24 rounded mt-2" style={style(110)} />
          {/* Accessories chips */}
          <div className="flex gap-1.5 mt-3">
            <div className="shimmer h-5 w-24 rounded-full" style={style(140)} />
            <div className="shimmer h-5 w-32 rounded-full" style={style(160)} />
            <div className="shimmer h-5 w-20 rounded-full" style={style(180)} />
          </div>
          {/* Explanation lines */}
          <div className="space-y-1.5 mt-3">
            <div className="shimmer h-4 w-full rounded" style={style(210)} />
            <div className="shimmer h-4 w-4/5 rounded" style={style(240)} />
          </div>
        </div>
      </div>

      {/* Bar skeleton */}
      <div className="mt-5">
        <div className="shimmer h-1.5 w-full rounded-full" style={style(270)} />
      </div>
    </div>
  )
}
