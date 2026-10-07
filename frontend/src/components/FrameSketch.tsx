import { useEffect, useRef, useState, useSyncExternalStore } from 'react'

interface Props {
  // The calculated frame size in `unit`; null = nothing calculated yet (empty sketch).
  size:  number | null
  unit:  'cm' | 'in'
  // Text next to the dimension line ("≈ 52,8 cm"); null = none, the line is drawn dashed.
  label: string | null
}

type Pt = [number, number]

// ── Drawing ─────────────────────────────────────────────────────────────────────────────
// A side view of a bike on fixed 700c wheels. Only the seat tube length follows the result;
// the head tube and the wheelbase grow with it the way a real frame does, so a bigger size
// reads as a bigger frame instead of a stretched one. Points are built in millimetres from
// the bottom bracket (x forward, y up) and mapped to viewBox pixels at the end.
const VIEW_X   = 50     // the viewBox is cropped to the bike, so it fills a narrow card
const VIEW_Y   = 20
const VIEW_W   = 510
const VIEW_H   = 320
const GROUND_Y = 318
const WHEEL_R  = 88
const MM       = WHEEL_R / 340                         // px per mm: a 700c wheel is 340 mm in radius
const BB_X     = 277
const BB_Y     = GROUND_Y - WHEEL_R + 70 * MM         // the bottom bracket hangs 70 mm below the hubs

const ANGLE = (73 * Math.PI) / 180                     // seat tube and head tube angle
const UP:   Pt = [-Math.cos(ANGLE), Math.sin(ANGLE)]   // along the seat tube / steering axis (mm, y up)
const BACK: Pt = [-Math.sin(ANGLE), -Math.cos(ANGLE)]  // perpendicular to it, towards the rear wheel

// Seat tube length (cm) the drawing is limited to, and the one shown before any result.
const MIN_CM     = 40
const MAX_CM     = 70
const DEFAULT_CM = 52

const DIM_OFFSET = 40   // px between the seat tube and its dimension line
const LABEL_MAX_Y = 130  // lowest the label's bottom edge goes: the rear wheel's rim starts at 142
const TICK       = 7    // px, half the length of an end tick

const at   = (from: Pt, dir: Pt, mm: number): Pt => [from[0] + dir[0] * mm, from[1] + dir[1] * mm]
const toPx = (p: Pt): Pt => [BB_X + p[0] * MM, BB_Y - p[1] * MM]
const path = (...pts: Pt[]) => pts.map((p, n) => `${n ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ')

function build(seatCm: number) {
  const rearHub: Pt  = [-409, 70]
  const frontHub: Pt = [-409 + 985 + 2.5 * (seatCm - 52), 70]
  const headMm = 70 + 4.5 * (seatCm - 44)

  const seatTop     = at([0, 0], UP, seatCm * 10)
  const seatStay    = at([0, 0], UP, seatCm * 10 - 35)
  const crown       = at(at(frontHub, BACK, 45), UP, 375)   // 45 mm fork offset, 375 mm fork
  const headBottom  = at(crown, UP, 15)
  const headTop     = at(headBottom, UP, headMm)
  const topTubeEnd  = at(headTop, UP, -14)
  const downTubeEnd = at(headBottom, UP, 20)
  const steerer     = at(headTop, UP, 25)
  const stemEnd: Pt = [steerer[0] + 95, steerer[1] + 6]
  const post        = at(seatTop, UP, 150)

  const bb  = toPx([0, 0])
  const top = toPx(seatTop)
  const bar = toPx(stemEnd)

  // The dimension line runs parallel to the seat tube, `DIM_OFFSET` px towards the rear,
  // from the bottom bracket axis to the top of the tube; extension lines and end ticks lie
  // perpendicular to it.
  const n: Pt = [BACK[0], -BACK[1]]
  const shift = (p: Pt, dist: number): Pt => [p[0] + n[0] * dist, p[1] + n[1] * dist]
  const a = shift(bb, DIM_OFFSET)
  const b = shift(top, DIM_OFFSET)

  return {
    rear:   toPx(rearHub),
    front:  toPx(frontHub),
    frame:  path(top, bb, toPx(rearHub), toPx(seatStay)) + path(bb, toPx(downTubeEnd)) + path(top, toPx(topTubeEnd)),
    head:   path(toPx(headBottom), toPx(headTop)),
    fork:   path(toPx(crown), toPx(frontHub)),
    stem:   path(toPx(headTop), toPx(steerer), bar),
    bars:   `M${bar[0].toFixed(1)} ${bar[1].toFixed(1)} h16 c14 0 20 8 20 22 c0 14 -8 22 -22 22`,
    post:   path(top, toPx(post)),
    saddle: path(toPx([post[0] - 75, post[1] + 10]), toPx([post[0] + 70, post[1] + 10])),
    crank:  path(bb, [bb[0] + 19, bb[1] + 40]) + path([bb[0] + 8, bb[1] + 40], [bb[0] + 30, bb[1] + 40]),
    extensions: path(shift(bb, 8), shift(bb, DIM_OFFSET + 8)) + path(shift(top, 8), shift(top, DIM_OFFSET + 8)),
    line:   path(a, b),
    ticks:  path(shift(a, -TICK), shift(a, TICK)) + path(shift(b, -TICK), shift(b, TICK)),
    // The label sits above the upper end of the line, in the free corner over the rear wheel,
    // on a short leader: low enough to stay with the line, high enough to clear the rim and,
    // in a tall frame, the saddle. `labelX` is its right edge, `labelY` its bottom edge.
    labelX: b[0] + 2,
    labelY: Math.min(b[1] - 16, LABEL_MAX_Y),
    leader: path([b[0] - 6, Math.min(b[1] - 16, LABEL_MAX_Y)], b),
  }
}

// ── Motion ──────────────────────────────────────────────────────────────────────────────
const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'

function subscribeReducedMotion(onChange: () => void) {
  const query = window.matchMedia(REDUCED_MOTION)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribeReducedMotion, () => window.matchMedia(REDUCED_MOTION).matches, () => false)
}

const TWEEN_MS = 450

// Glides the drawn size to its new value; the `d` attribute cannot be transitioned in
// every browser, so the geometry is recomputed per frame instead. A change that arrives
// mid-glide continues from where the drawing is. Disabled: follows the target at once.
function useTween(target: number, enabled: boolean): number {
  const [value, setValue] = useState(target)
  const shown = useRef(target)

  useEffect(() => {
    let frame = 0
    if (!enabled) {
      shown.current = target
      frame = requestAnimationFrame(() => setValue(target))
      return () => cancelAnimationFrame(frame)
    }
    const from = shown.current
    if (from === target) return
    const start = performance.now()
    const step = (now: number) => {
      const t = Math.min(1, Math.max(0, (now - start) / TWEEN_MS))
      shown.current = from + (target - from) * (1 - (1 - t) ** 3)
      setValue(shown.current)
      if (t < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [target, enabled])

  return enabled ? value : target
}

// The sketch on the result card: the frame drawn at the calculated size, its seat tube
// dimensioned. MTB sizes are inches; they are converted to centimetres for the drawing only.
export default function FrameSketch({ size, unit, label }: Props) {
  const reduced = usePrefersReducedMotion()
  const cm = size === null ? DEFAULT_CM : unit === 'in' ? size * 2.54 : size
  const g = build(useTween(Math.min(MAX_CM, Math.max(MIN_CM, cm)), !reduced))
  const dim = label === null ? 'var(--color-muted)' : 'var(--color-terra)'

  return (
    <div className="relative">
      <svg
        viewBox={`${VIEW_X} ${VIEW_Y} ${VIEW_W} ${VIEW_H}`}
        className="block w-full h-auto"
        role="img"
        aria-label="Szkic roweru z zaznaczoną długością rury podsiodłowej"
      >
        <defs>
          <pattern id="fit-dots" width="20" height="20" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" fill="var(--color-ink)" />
          </pattern>
        </defs>
        <rect x={VIEW_X} y={VIEW_Y} width={VIEW_W} height={VIEW_H} fill="url(#fit-dots)" />
        <path d={`M${VIEW_X} ${GROUND_Y} H${VIEW_X + VIEW_W}`} stroke="var(--color-ink)" strokeWidth="2" />

        {/* Wheels: fixed size whatever the result */}
        <g fill="none" stroke="var(--color-parchment)">
          {[g.rear, g.front].map(([x, y], n) => (
            <g key={n}>
              <circle cx={x} cy={y} r={WHEEL_R} strokeWidth="2.5" opacity="0.7" />
              <circle cx={x} cy={y} r={WHEEL_R - 9} strokeWidth="1.5" opacity="0.3" />
              <circle cx={x} cy={y} r="4.5" fill="var(--color-parchment)" stroke="none" opacity="0.8" />
            </g>
          ))}
          <circle cx={BB_X} cy={BB_Y} r="24" strokeWidth="1.5" opacity="0.4" />
        </g>

        {/* Frame, fork, cockpit, saddle */}
        <g fill="none" stroke="var(--color-parchment)" strokeLinecap="round" strokeLinejoin="round">
          <path d={g.frame} strokeWidth="4" />
          <path d={g.head} strokeWidth="7" />
          <path d={g.fork} strokeWidth="3.5" />
          <path d={g.stem} strokeWidth="3.5" />
          <path d={g.bars} strokeWidth="3.5" />
          <path d={g.post} strokeWidth="3.5" />
          <path d={g.saddle} strokeWidth="7" />
          <path d={g.crank} strokeWidth="3" />
        </g>

        {/* Seat tube dimension: parallel to the tube, a tick at each end */}
        <g fill="none" stroke={dim} strokeLinecap="round">
          <path d={g.extensions} strokeWidth="1" strokeDasharray="3 3" opacity="0.8" />
          <path d={g.line} strokeWidth="2" strokeDasharray={label === null ? '5 5' : undefined} />
          <path d={g.ticks} strokeWidth="2.5" />
          {label !== null && <path d={g.leader} strokeWidth="1.5" />}
        </g>
      </svg>

      {/* The label's box ends at the anchor and starts 6 px inside the card; the auto margin
          keeps the chip against its right end and, when it is wider than the box (a narrow
          card), lets it spill to the right instead of out of the card. */}
      {label !== null && (
        <div
          aria-hidden="true"
          className="absolute flex -translate-y-full pointer-events-none"
          style={{
            left:  6,
            width: `calc(${((g.labelX - VIEW_X) / VIEW_W) * 100}% - 6px)`,
            top:   `${((g.labelY - VIEW_Y) / VIEW_H) * 100}%`,
          }}
        >
          <span className="ml-auto px-1 min-[420px]:px-2 py-0.5 rounded-md border border-terra/70 bg-charcoal/90 font-mono text-[11px] sm:text-sm text-parchment whitespace-nowrap">
            {label}
          </span>
        </div>
      )}
    </div>
  )
}
