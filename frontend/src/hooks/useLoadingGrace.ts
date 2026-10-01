import { useEffect, useState } from 'react'

// How long a section shows its loading state before the "Request data" button
// takes its place (TODO-027). The request itself keeps running.
export const REQUEST_BUTTON_DELAY_MS = 5000

// True while `loading` has been on for less than `ms`. Restarts whenever
// `loading` turns on again (e.g. a details retry).
export function useLoadingGrace(loading: boolean, ms = REQUEST_BUTTON_DELAY_MS): boolean {
  const [elapsed, setElapsed] = useState(false)
  const [prevLoading, setPrevLoading] = useState(loading)
  if (loading !== prevLoading) {
    setPrevLoading(loading)
    if (loading) setElapsed(false)
  }
  useEffect(() => {
    if (!loading) return
    const t = setTimeout(() => setElapsed(true), ms)
    return () => clearTimeout(t)
  }, [loading, ms])
  return loading && !elapsed
}
