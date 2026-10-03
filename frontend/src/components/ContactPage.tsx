// "Kontakt" tab (TODO-041). The "Napisz do nas" form sends POST /v1/contact, which stores
// the message in the database (contact_message); nobody is e-mailed.
import { useState, type FormEvent } from 'react'
import { sendContactMessage } from '../api'
import type { ContactMessageRequest, ContactTopic } from '../types'

const fieldClass =
  'w-full px-3.5 py-3 bg-parchment text-charcoal border border-border rounded-xl font-body text-base placeholder:text-muted disabled:opacity-60 disabled:cursor-not-allowed'

const labelClass = 'block mb-1.5 font-body text-sm text-ink'

// `value` is the slug the backend stores, `label` what the visitor reads.
const TOPICS: { value: ContactTopic; label: string }[] = [
  { value: 'missing_bike', label: 'Brakuje roweru w bazie' },
  { value: 'wrong_data',   label: 'Błędne dane roweru' },
  { value: 'feature_idea', label: 'Pomysł na nową funkcję' },
  { value: 'cooperation',  label: 'Współpraca' },
  { value: 'other',        label: 'Inna sprawa' },
]

// The backend's limits (app/schemas.py ContactMessageRequest) and its e-mail check.
const NAME_MAX = 100
const EMAIL_MAX = 254
const MESSAGE_MAX = 5000
const EMAIL_PATTERN = '[^@\\s]+@[^@\\s]+\\.[^@\\s]+'

const EMPTY_FORM: ContactMessageRequest = { name: '', email: '', topic: 'missing_bike', message: '', website: '' }

type Status = 'idle' | 'sending' | 'sent'

export default function ContactPage() {
  const [form, setForm] = useState<ContactMessageRequest>(EMPTY_FORM)
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<string | null>(null)

  function update<K extends keyof ContactMessageRequest>(key: K, value: ContactMessageRequest[K]) {
    setForm(f => ({ ...f, [key]: value }))
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (status === 'sending') return
    // `required` lets a message of only spaces through; the backend would refuse it.
    if (!form.message.trim()) {
      setError('Wpisz treść wiadomości.')
      return
    }
    setError(null)
    setStatus('sending')
    try {
      await sendContactMessage(form)
      setStatus('sent')
      // Name and e-mail stay filled in for a follow-up message.
      setForm(f => ({ ...EMPTY_FORM, name: f.name, email: f.email }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nie udało się wysłać wiadomości.')
      setStatus('idle')
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 pb-20">
      <section className="pt-14 pb-10 md:pt-20 md:pb-14" aria-labelledby="contact-heading">
        <h1
          id="contact-heading"
          className="font-display font-bold leading-[0.92] tracking-tight text-charcoal text-[52px] sm:text-[68px] md:text-[80px] mb-4"
        >
          Napisz<br />do nas.
        </h1>
        <p className="font-body text-ink text-base md:text-[17px] leading-relaxed max-w-md">
          Brakuje roweru w bazie, dane się nie zgadzają albo masz pomysł? Napisz, a odpowiemy na podany adres e-mail.
        </p>
      </section>

      <div className="grid gap-8 sm:grid-cols-[1fr_13rem] sm:gap-10">
        {status === 'sent' ? (
          <div
            role="status"
            className="p-6 bg-parchment border border-border rounded-2xl"
            style={{ animation: 'slideUp 200ms ease-out' }}
          >
            <h2 className="font-display font-bold text-3xl text-charcoal mb-2">Dziękujemy!</h2>
            <p className="font-body text-base text-ink leading-relaxed mb-6">
              Wiadomość dotarła. Odpiszemy na adres <span className="font-semibold">{form.email}</span>.
            </p>
            <button
              type="button"
              onClick={() => setStatus('idle')}
              className="px-5 py-2.5 rounded-xl border border-terra text-terra font-display font-bold text-base tracking-[0.04em] hover:bg-terra hover:text-parchment transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/40"
            >
              Napisz kolejną wiadomość
            </button>
          </div>
        ) : (
          <form className="p-6 bg-parchment border border-border rounded-2xl" onSubmit={handleSubmit}>
            <fieldset disabled={status === 'sending'} className="grid gap-[1.1rem] m-0 p-0 border-0 min-w-0">
              <div className="grid gap-[1.1rem] min-[480px]:grid-cols-2">
                <div>
                  <label htmlFor="contact-name" className={labelClass}>
                    Imię <span className="text-muted">(opcjonalnie)</span>
                  </label>
                  <input
                    id="contact-name"
                    className={fieldClass}
                    autoComplete="given-name"
                    maxLength={NAME_MAX}
                    value={form.name}
                    onChange={e => update('name', e.target.value)}
                  />
                </div>
                <div>
                  <label htmlFor="contact-email" className={labelClass}>E-mail</label>
                  <input
                    id="contact-email"
                    type="email"
                    required
                    className={fieldClass}
                    autoComplete="email"
                    maxLength={EMAIL_MAX}
                    pattern={EMAIL_PATTERN}
                    title="Adres e-mail, np. jan@example.pl"
                    value={form.email}
                    onChange={e => update('email', e.target.value)}
                  />
                </div>
              </div>
              <div>
                <label htmlFor="contact-topic" className={labelClass}>W jakiej sprawie?</label>
                <select
                  id="contact-topic"
                  className={fieldClass}
                  value={form.topic}
                  onChange={e => update('topic', e.target.value as ContactTopic)}
                >
                  {TOPICS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="contact-message" className={labelClass}>Wiadomość</label>
                <textarea
                  id="contact-message"
                  rows={6}
                  required
                  maxLength={MESSAGE_MAX}
                  className={`${fieldClass} resize-y leading-normal`}
                  placeholder="np. Nie mogę znaleźć modelu Kross Esker 4.0 z 2025 roku."
                  value={form.message}
                  onChange={e => update('message', e.target.value)}
                />
              </div>
              {/* Honeypot: off-screen and out of the tab order, so only a bot fills it in. */}
              <div aria-hidden="true" className="absolute -left-[9999px] w-px h-px overflow-hidden">
                <label htmlFor="contact-website">Strona internetowa</label>
                <input
                  id="contact-website"
                  name="website"
                  tabIndex={-1}
                  autoComplete="off"
                  value={form.website}
                  onChange={e => update('website', e.target.value)}
                />
              </div>
              {error && (
                <p role="alert" className="flex items-start gap-2.5 font-body text-sm text-terra">
                  <span className="mt-[7px] w-[7px] h-[7px] rounded-full bg-terra shrink-0" aria-hidden="true" />
                  {error}
                </p>
              )}
              <div className="flex flex-wrap items-center justify-between gap-4">
                <small className="font-body text-[13px] text-muted max-w-72">
                  Adres e-mail wykorzystamy tylko do odpowiedzi na tę wiadomość.
                </small>
                <button
                  type="submit"
                  className="inline-flex items-center gap-2.5 px-6 py-3 rounded-xl bg-terra text-parchment font-display font-bold text-lg tracking-[0.04em] disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/50 focus-visible:ring-offset-2 focus-visible:ring-offset-parchment"
                >
                  {status === 'sending' && (
                    <span className="spin w-3 h-3 rounded-full border-2 border-parchment/30 border-t-parchment shrink-0" aria-hidden="true" />
                  )}
                  {status === 'sending' ? 'Wysyłam…' : 'Wyślij wiadomość'}
                </button>
              </div>
            </fieldset>
          </form>
        )}

        <aside aria-label="Wskazówka">
          <h2 className="font-display font-bold text-xl text-charcoal mb-1">Brakuje danych o rowerze?</h2>
          <p className="font-body text-[15px] text-ink leading-relaxed">
            W widoku szczegółów roweru kliknij „Poproś o dane” przy brakującej sekcji: zdjęciach, recenzji albo ofertach. To najszybsza droga, bo od razu uruchamia wyszukiwanie.
          </p>
        </aside>
      </div>
    </div>
  )
}
