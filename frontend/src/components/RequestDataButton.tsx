import { useState } from 'react'
import type { MissingDataRequest, MissingType } from '../types'

type RequestStatus = 'idle' | 'sending' | 'requested'

interface RequestDataButtonProps {
  company: string
  model: string
  missingType: MissingType
  // Section label shown above the line, matching the eyebrow of the section it stands in for.
  title?: string
  // 'card' stands alone in the page flow; 'inline' sits inside an existing card (offer Used / New).
  variant?: 'card' | 'inline'
  // Top spacing of the 'card' variant; the spec-tree slot sits right under a divider.
  spacing?: string
}

// Stands in for a bike-details section that has no data yet (TODO-027). The click
// is recorded by POST /v1/bike/missing; the state lives only in this component, so
// a page refresh lets the user request again.
export default function RequestDataButton({
  company,
  model,
  missingType,
  title,
  variant = 'card',
  spacing = 'mt-5',
}: RequestDataButtonProps) {
  const [status, setStatus] = useState<RequestStatus>('idle')

  const request = async () => {
    setStatus('sending')
    try {
      const body: MissingDataRequest = { company, model, missing_type: missingType }
      const res = await fetch('/v1/bike/missing', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(body),
      })
      if (!res.ok) throw new Error(`Błąd serwera ${res.status}`)
      setStatus('requested')
    } catch {
      // Let the user try again.
      setStatus('idle')
    }
  }

  const requested = status === 'requested'

  const content = (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="font-body italic text-ink text-[13px] leading-relaxed">
        Nie mamy jeszcze tych danych
      </p>
      <button
        type="button"
        onClick={request}
        disabled={status !== 'idle'}
        aria-live="polite"
        className={`
          self-start sm:self-auto shrink-0 inline-flex items-center gap-2
          px-4 py-2 rounded-full border
          font-mono text-[11px] tracking-wide
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/40 focus-visible:ring-offset-2 focus-visible:ring-offset-card
          transition-colors duration-150
          ${requested
            ? 'bg-transparent border-terra/40 text-terra cursor-default'
            : 'bg-terra border-terra text-parchment hover:bg-terra-dark hover:border-terra-dark disabled:opacity-70 disabled:cursor-wait'}
        `}
      >
        {status === 'sending' && (
          <span
            className="spin w-3 h-3 rounded-full border-2 border-parchment/30 border-t-parchment shrink-0"
            aria-hidden="true"
          />
        )}
        {requested ? 'Zgłoszono ✓' : 'Poproś o dane'}
      </button>
    </div>
  )

  if (variant === 'inline') {
    return <div className="px-5 py-4 md:px-6 md:py-5">{content}</div>
  }

  return (
    <div className={`${spacing} bg-card rounded-2xl border border-dashed border-border px-5 py-4 md:px-6 md:py-5`}>
      {title && (
        <span className="font-mono text-[10px] text-muted uppercase tracking-widest block mb-2">
          {title}
        </span>
      )}
      {content}
    </div>
  )
}
