import { useRef, useState } from 'react'

// Two "Poproś o dane" buttons (Opis + Komponenty) share ONE search run: a click while the
// run is in flight joins it instead of starting another, and the buttons that did not
// start it `watch` the returned `run` promise (spinner, no second request).
export function useSharedRun(start: () => Promise<void>) {
  const runRef = useRef<Promise<void> | null>(null)
  const [run, setRun] = useState<Promise<void> | null>(null)
  const trigger = () => {
    if (runRef.current) return runRef.current
    const p = start()
    runRef.current = p
    setRun(p)
    const clear = () => { runRef.current = null; setRun(null) }
    p.then(clear, clear)
    return p
  }
  return { run, trigger }
}
