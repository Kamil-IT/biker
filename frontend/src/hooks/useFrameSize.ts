import { useEffect, useState } from 'react'
import { ApiError, postJson } from '../api'
import { FIT_BIKE_TYPES, FRAME_SIZE_LETTERS } from '../types'
import type { FitBikeType, FrameSizeRequest, FrameSizeResponse } from '../types'

export type FrameSizeState = 'idle' | 'loading' | 'loaded' | 'invalid' | 'error'

interface FrameSize {
  state:   FrameSizeState
  // The last answer: kept while the next one is loading, null in every other state.
  result:  FrameSizeResponse | null
  // Polish text for 'invalid' and 'error', null otherwise.
  message: string | null
  // Asks again after an 'error' (the same input would not trigger a request by itself).
  retry:   () => void
}

const DEBOUNCE_MS = 300

const INVALID_MESSAGE = 'Podaj wzrost od 140 do 210 cm i długość nogi od 60 do 110 cm.'
const ERROR_MESSAGE   = 'Nie udało się policzyć rozmiaru. Sprawdź połączenie z internetem i spróbuj ponownie.'

// "178", "178,5" and "178.5" are numbers; "", "abc", "1e3" and "17 8" are not. The accepted
// range is the backend's to judge (422), not this page's.
function parseNumber(text: string): number | null {
  const t = text.trim().replace(',', '.')
  return /^\d+(\.\d+)?$/.test(t) ? Number(t) : null
}

const isFiniteNumber = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

// A 200 whose body is not a frame size (a proxy's error page, a newer backend) would crash
// the result card, so the answer is checked before it is trusted.
function isFrameSizeResponse(data: unknown): data is FrameSizeResponse {
  if (typeof data !== 'object' || data === null) return false
  const d = data as Record<string, unknown>
  const isLetter = (v: unknown) => (FRAME_SIZE_LETTERS as readonly unknown[]).includes(v)
  return (
    (FIT_BIKE_TYPES as readonly unknown[]).includes(d.bike_type) &&
    isFiniteNumber(d.size) && isFiniteNumber(d.range_min) && isFiniteNumber(d.range_max) &&
    (d.unit === 'cm' || d.unit === 'in') &&
    isLetter(d.letter) &&
    Array.isArray(d.letters) && d.letters.length > 0 && d.letters.every(isLetter) &&
    (d.confidence === 'good' || d.confidence === 'medium') &&
    typeof d.measurement_warning === 'boolean'
  )
}

// What one finished request left behind; `key` names the input it answered.
interface Entry {
  key:     string
  state:   'loaded' | 'invalid' | 'error'
  result:  FrameSizeResponse | null
  message: string | null
}

// "Rower na Twoją miarę" calculator (TODO-045): the raw field texts and the bike type go
// in, the backend's frame size comes out. Once both fields are numbers and 300 ms pass
// without a change, POST /v1/fit/frame-size is sent; typing on aborts the request in flight,
// so only the last input is answered. Nothing is computed here. While the next answer is
// pending the previous result stays on screen ('loading'); `idle` = nothing to ask yet.
export default function useFrameSize(height: string, inseam: string, bikeType: FitBikeType): FrameSize {
  const h = parseNumber(height)
  const i = parseNumber(inseam)
  const ready = h !== null && i !== null
  const [attempt, setAttempt] = useState(0)
  const [entry, setEntry] = useState<Entry | null>(null)

  // Fields emptied or no longer numbers: forget the old answer now, so typing again does
  // not flash a result that belongs to something else.
  if (!ready && entry !== null) setEntry(null)

  const key = `${h}|${i}|${bikeType}|${attempt}`

  useEffect(() => {
    if (h === null || i === null) return
    // The cleanup runs on the next change and on unmount — also StrictMode's first mount.
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      const body: FrameSizeRequest = { height_cm: h, inseam_cm: i, bike_type: bikeType }
      let next: Entry
      try {
        const result = await postJson<unknown>('/v1/fit/frame-size', body, controller.signal)
        // Same as a server error: the error state with its retry button.
        if (!isFrameSizeResponse(result)) throw new Error('Unexpected frame-size answer')
        next = { key, state: 'loaded', result, message: null }
      } catch (err) {
        if (controller.signal.aborted) return
        const invalid = err instanceof ApiError && err.status === 422
        next = { key, state: invalid ? 'invalid' : 'error', result: null, message: invalid ? INVALID_MESSAGE : ERROR_MESSAGE }
      }
      if (!controller.signal.aborted) setEntry(next)
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [h, i, bikeType, key])

  const retry = () => setAttempt(n => n + 1)

  if (!ready) return { state: 'idle', result: null, message: null, retry }
  if (entry === null) return { state: 'loading', result: null, message: null, retry }
  if (entry.key !== key) {
    return { state: 'loading', result: entry.state === 'loaded' ? entry.result : null, message: null, retry }
  }
  return { state: entry.state, result: entry.result, message: entry.message, retry }
}
