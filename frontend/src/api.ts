import type { MissingDataRequest } from './types'

// A non-OK answer; `status` lets a caller tell "not found" (404) from a failure.
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

// POST a JSON body and parse the JSON answer. A non-OK status throws an ApiError carrying
// the backend's `detail` (or "Błąd serwera <status>"), so a caller can show it or let a
// "Poproś o dane" button become clickable again.
export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    const detail = (data as { detail?: unknown }).detail
    throw new ApiError(typeof detail === 'string' ? detail : `Błąd serwera ${res.status}`, res.status)
  }
  return await res.json() as T
}

export const errorMessage = (err: unknown): string =>
  err instanceof Error ? err.message : 'Coś poszło nie tak. Spróbuj ponownie.'

// Record a "Request data" click (POST /v1/bike/missing, TODO-026). Throws on a non-OK
// status so a caller can decide whether the failure matters.
export async function recordMissing(body: MissingDataRequest): Promise<void> {
  const res = await fetch('/v1/bike/missing', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`Błąd serwera ${res.status}`)
}
