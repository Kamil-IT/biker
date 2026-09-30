# TODO-041 — Plan testów: pasek zakładek, „Rower na Twoją miarę”, „Kontakt”

Podstawa testów: `backlog/TODO_041_TOP_TABS.md`, makiety `docs/mockups/zakladki/`.
Gałąź `feature/041-top-tabs` (zmiany niezacommitowane). Środowisko: Vite `http://localhost:5173` → backend `:8002` → lokalny `biker-pg`. Playwright (Chromium, headless), 1280×900 i 375×800.

Zakres: tylko frontend. Bez płatnych wyszukiwań searchera. Dane testowe: wyszukiwanie po filtrze marki `Cannondale` (trafienie w bazie, bez AI), rower z listy popularnych. `/v1/bike/details` odpowiada 400 (brak kredytów Anthropic, znane) — widok szczegółów otwiera się z błędem, co nie przeszkadza w testach nawigacji.

## Śledzenie wymagań

| Wymaganie | Gdzie | Status |
|---|---|---|
| R1 Strona główna bez zmian, dochodzi tylko pasek | `App.tsx` (nagłówek + warunek `route === ROUTES.search`) | Zaimplementowane |
| R2 Własny URL każdej zakładki, wstecz/dalej, odświeżenie, deep link | `hooks/useRoute.ts` | Zaimplementowane |
| R3 Aktywna zakładka `aria-current` + kreska; aktywna też w szczegółach | `components/TopTabs.tsx` | Zaimplementowane |
| R4 Powrót do „Szukanie rowerów” zachowuje stan; w szczegółach wraca do listy | `App.tsx` `handleNavigate` | Zaimplementowane |
| R5 Logo BIKER: reset + przejście na `/` | `App.tsx` `handleWordmark` | Zaimplementowane |
| R6 Nieznany adres → `/` | `useRoute.ts` `readRoute` + `replaceState` | Zaimplementowane |
| R7 Modyfikowany klik = nowa karta | `TopTabs.tsx` `handleClick` | Zaimplementowane |
| R8 Tytuł karty zmienia się | `useRoute.ts` `TITLES` | Zaimplementowane |
| R9 Strona „Wkrótce” wg makiety, animacja wyłączana przy reduced motion | `components/FitComingSoonPage.tsx`, `index.css` `.scan` | Zaimplementowane |
| R10 Kontakt: formularz nieaktywny, informacja „wkrótce”, brak adresu e-mail | `components/ContactPage.tsx` | Zaimplementowane |
| R11 375 px: zakładki w jednym wierszu, brak poziomego przewijania | `TopTabs.tsx` | Zaimplementowane |
| Extra | Treść wskazówki na Kontakcie zmieniona na „Brakuje danych o rowerze?” (stara sugerowała, że „Poproś o dane” dodaje brakujący rower — to nieprawda) | Do akceptacji użytkownika |

## Przypadki testowe

| ID | Wym. | Prio | Kroki | Oczekiwany wynik |
|---|---|---|---|---|
| TC01 | R1 R3 | P1 | Otwórz `/` | 3 zakładki w kolejności; „Szukanie rowerów” ma `aria-current="page"`; hero „Znajdź swój idealny rower.”, pole wyszukiwania, „Najpopularniejsze rowery” |
| TC02 | R2 R3 R8 R9 | P1 | Klik „Rower na Twoją miarę” | URL `/rower-na-twoja-miare`; h1 „Rower na Twoją miarę.”; „Wkrótce”; „AI dopasuje rower do Ciebie”; 3 kroki; tytuł „Rower na Twoją miarę — Biker”; `aria-current` na tej zakładce |
| TC03 | R2 R8 R10 | P1 | Klik „Kontakt” | URL `/kontakt`; h1 „Napisz do nas.”; wszystkie pola i przycisk `disabled`; tekst „uruchomimy wkrótce”; brak „@” na stronie; tytuł „Kontakt — Biker” |
| TC04 | R2 | P1 | `/` → Twoja miara → Kontakt → wstecz → wstecz → dalej | Kolejno: Twoja miara, `/`, Twoja miara; treść i `aria-current` zgodne z URL |
| TC05 | R2 | P1 | Wejdź wprost na `/kontakt`, odśwież | Strona Kontakt przed i po odświeżeniu |
| TC06 | R6 | P2 | Wejdź na `/nie-ma-takiej` | Strona główna, URL `/` |
| TC07 | R2 | P3 | Wejdź na `/kontakt/` | Strona Kontakt |
| TC08 | R4 | P1 | Filtry → marka `Cannondale` → Szukaj; Kontakt; „Szukanie rowerów” | Te same wyniki co przed wyjściem, bez nowego żądania `/v1/bike/search` |
| TC09 | R3 R4 | P1 | Otwórz rower z popularnych (widok szczegółów); klik „Szukanie rowerów” | W szczegółach aktywna jest „Szukanie rowerów”; po kliku lista (hero + popularne) |
| TC10 | R4 | P2 | Szczegóły roweru → Kontakt → „Szukanie rowerów” | Wraca widok szczegółów tego samego roweru |
| TC11 | R5 | P1 | Na `/kontakt` klik BIKER | URL `/`, strona główna w stanie początkowym |
| TC12 | R7 | P2 | Ctrl+klik „Kontakt” na `/` | Nowa karta z `/kontakt`; bieżąca zostaje na `/` |
| TC13 | R11 | P1 | 375×800, wszystkie 3 adresy | Zakładki w jednym wierszu (ta sama współrzędna Y), `scrollWidth` = 375 |
| TC14 | R3 | P2 | Klawiatura: Tab do zakładki „Kontakt”, Enter | Widoczny focus (ring), przejście na `/kontakt` |
| TC15 | R9 | P2 | `reduced_motion=reduce`, `/rower-na-twoja-miare` | Element `.scan` niewidoczny |
| TC16 | — | P2 | Przejście po wszystkich zakładkach | Brak błędów w konsoli (poza znanym 400 z `/v1/bike/details`) |
| TC17 | R9 | P3 | Twoja miara → „Szukaj rowerów” | URL `/`, strona główna |

## Regresja

| ID | Obszar | Oczekiwany wynik |
|---|---|---|
| RG1 | Wyszukiwanie z filtrem marki | Wyniki z bazy (część TC08) |
| RG2 | Szczegóły → „Wróć do wyników” | Powrót do listy wyników |
| RG3 | Popularne rowery na `/` | Sekcja widoczna z ocenami |
| RG4 | Logo BIKER na `/` z wynikami | Reset do stanu początkowego |

## Wyniki — runda 1 (2026-09-30)

18 zaliczonych · 0 niezaliczonych · 0 zablokowanych · runda 1 (TC16 i RG1/RG3 pokryte przez TC01/TC08 i zbiór błędów konsoli).

| ID | Wynik | Uwagi |
|---|---|---|
| TC01–TC15, TC17 | Pass | Zrzuty: `TC01-home`, `TC02-fit`, `TC03-contact`, `TC08-results-kept`, `TC13-*-375`, `TC14-focus` |
| TC16 | Pass | Jedyne błędy konsoli: 400 z `/v1/bike/details` w TC10 i RG2 (brak kredytów Anthropic, znane, niezwiązane) |
| RG1–RG4 | Pass | |

Skrypt: Playwright (Python, Chromium headless), poza repozytorium.
