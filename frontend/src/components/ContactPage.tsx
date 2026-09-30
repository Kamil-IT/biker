// TODO-041: "Kontakt" tab. There is no contact backend yet, so the form is shown
// disabled with a "wkrótce" notice — nothing is sent anywhere.

const fieldClass =
  'w-full px-3.5 py-3 bg-parchment text-charcoal border border-border rounded-xl font-body text-base placeholder:text-muted disabled:opacity-60 disabled:cursor-not-allowed'

const labelClass = 'block mb-1.5 font-body text-sm text-ink'

const TOPICS = [
  'Brakuje roweru w bazie',
  'Błędne dane roweru',
  'Pomysł na nową funkcję',
  'Współpraca',
  'Inna sprawa',
]

export default function ContactPage() {
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
          Brakuje roweru w bazie, dane się nie zgadzają albo masz pomysł? Formularz ruszy już wkrótce.
        </p>
      </section>

      <div className="grid gap-8 sm:grid-cols-[1fr_13rem] sm:gap-10">
        <form
          className="p-6 bg-parchment border border-border rounded-2xl"
          onSubmit={e => e.preventDefault()}
          aria-describedby="contact-soon"
        >
          <p
            id="contact-soon"
            className="mb-5 flex items-start gap-2.5 font-body text-sm text-ink"
          >
            <span className="mt-[7px] w-[7px] h-[7px] rounded-full bg-terra shrink-0" aria-hidden="true" />
            Wysyłanie wiadomości uruchomimy wkrótce. Na razie formularz jest nieaktywny.
          </p>

          <fieldset disabled className="grid gap-[1.1rem] m-0 p-0 border-0 min-w-0">
            <div className="grid gap-[1.1rem] min-[480px]:grid-cols-2">
              <div>
                <label htmlFor="contact-name" className={labelClass}>Imię</label>
                <input id="contact-name" className={fieldClass} autoComplete="given-name" />
              </div>
              <div>
                <label htmlFor="contact-email" className={labelClass}>E-mail</label>
                <input id="contact-email" type="email" className={fieldClass} autoComplete="email" />
              </div>
            </div>
            <div>
              <label htmlFor="contact-topic" className={labelClass}>W jakiej sprawie?</label>
              <select id="contact-topic" className={fieldClass}>
                {TOPICS.map(t => <option key={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="contact-message" className={labelClass}>Wiadomość</label>
              <textarea
                id="contact-message"
                rows={6}
                className={`${fieldClass} resize-y leading-normal`}
                placeholder="np. Nie mogę znaleźć modelu Kross Esker 4.0 z 2025 roku."
              />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <small className="font-body text-[13px] text-muted max-w-72">
                Adres e-mail wykorzystamy tylko do odpowiedzi na tę wiadomość.
              </small>
              <button
                type="submit"
                className="px-6 py-3 rounded-xl bg-terra text-parchment font-display font-bold text-lg tracking-[0.04em] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Wyślij wiadomość
              </button>
            </div>
          </fieldset>
        </form>

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
