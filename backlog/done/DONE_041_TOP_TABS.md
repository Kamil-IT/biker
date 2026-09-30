# TODO-041 — Pasek zakładek na górze + strony „Rower na Twoją miarę” i „Kontakt”

## Cel

Nawigacja między trzema częściami serwisu z paska zakładek pod logo BIKER.

| Zakładka | Adres | Zawartość |
|---|---|---|
| Szukanie rowerów | `/` | Obecna strona główna (wyszukiwarka, najpopularniejsze rowery, widok szczegółów, widok sprzętu) — **bez zmian** |
| Rower na Twoją miarę | `/rower-na-twoja-miare` | Zapowiedź „Wkrótce”: AI dobierze rower do użytkownika |
| Kontakt | `/kontakt` | Formularz kontaktowy — **wysyłanie „wkrótce”** (brak backendu) |

Zatwierdzone makiety: `docs/mockups/zakladki/` (`szukanie-rowerow.html`, `rower-na-twoja-miare.html`, `kontakt.html`).

## Wymagania

- Strona główna nie zmienia wyglądu ani działania — dochodzi tylko pasek zakładek w nagłówku (pod wierszem z logo). Nagłówek, stopka, hero, wyszukiwarka, popularne rowery, szczegóły i sprzęt zostają jak są.
- Każda zakładka ma własny adres URL; działa przycisk „wstecz/dalej”, odświeżenie strony i wejście z linku (nginx ma już SPA fallback, Vite też).
- Aktywna zakładka: `aria-current="page"` i terakotowa kreska na dolnej krawędzi nagłówka. „Szukanie rowerów” jest aktywna też w widoku szczegółów roweru i sprzętu.
- Klik w „Szukanie rowerów” z innej zakładki wraca na `/` z zachowanym stanem wyszukiwania (wyniki nie giną). Klik w nią w widoku szczegółów/sprzętu wraca do listy wyników.
- Klik w logo BIKER: jak dotąd reset wyszukiwania, a z innej zakładki dodatkowo przejście na `/`.
- Nieznany adres → `/` (bez strony 404).
- Ctrl/⌘/Shift/środkowy klik w zakładkę otwiera ją w nowej karcie (to zwykłe linki `<a href>`).
- Tytuł karty przeglądarki zmienia się z zakładką.
- „Rower na Twoją miarę”: hero „Rower na Twoją miarę.”, ciemna karta ze szkicem roweru (linie pomiarów z „?”, punkty podparcia, powolna linia skanu — wyłączona przy `prefers-reduced-motion`), znaczek „Wkrótce”, nagłówek „AI dopasuje rower do Ciebie”, 3 kroki, przycisk „Szukaj rowerów” → `/`.
- „Kontakt”: hero „Napisz do nas.”, formularz (imię, e-mail, temat, wiadomość) nieaktywny, z informacją, że wysyłanie ruszy wkrótce; obok wskazówka o przycisku „Poproś o dane”. Bez adresu e-mail na stronie.
- Mobile 375 px: trzy zakładki mieszczą się w jednym wierszu, brak poziomego przewijania strony.
- Bez nowych zależności (bez react-router) — mały hook do adresów.

## Poza zakresem

- Backend formularza kontaktowego, właściwy dobór roweru przez AI.
- Refaktoryzacja `App.tsx` (już > 500 linii).
