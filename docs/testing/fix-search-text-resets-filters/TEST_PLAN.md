# Test plan — reset filtrów po zmianie tekstu wyszukiwania

Branch: `fix/search-text-resets-filters` · Stack testowy: backend `:8003`, frontend `:5176`
(porty niedomyślne — `BIKER_API_URL=http://localhost:8003`).

## Wymaganie (z wywiadu)

> Za każdym razem, gdy w polu `bike-search` pojawi się zmiana tekstu, po naciśnięciu
> „Znajdź mój rower” filtry mają się wyczyścić i ma zostać wykonane ponowne wywołanie
> API konwertującego tekst na filtry (`/v1/bike/parse`).

## Traceability

| Wymaganie | Implementacja | Status |
|---|---|---|
| Zmiana tekstu → czyszczenie wszystkich filtrów przy submicie | `frontend/src/App.tsx:95-107` (`textChanged` → `setFilters(EMPTY_FILTERS)`) | Implemented |
| Zmiana tekstu → ponowny call `/v1/bike/parse` | `App.tsx:102` (warunek `textChanged \|\| !hasStructured`) | Implemented |
| Nowe filtry pochodzą wyłącznie z nowego tekstu | `App.tsx:104-107` (`payload = { search }`) + merge do wyczyszczonego stanu | Implemented |
| Brak zmiany tekstu → bez parse'a, zwykłe wyszukiwanie z filtrami | `App.tsx:102` (warunek fałszywy) | Implemented |
| Reset aplikacji czyści pamięć sparsowanego tekstu | `App.tsx:400` (`parsedQueryRef.current = ''`) | Implemented |

## Ograniczenie kosztowe

Kredyty Anthropic API wyczerpane → tylko teksty z cache: `trek marlin 5`,
`kross esker eco`, `merida silex 200`, `kross`, `merida`.

## Przypadki testowe

| ID | Warunek / partycja | Kroki | Oczekiwany rezultat | Prio |
|---|---|---|---|---|
| TC-01 | Pierwszy submit samego tekstu | wpisz `trek marlin 5` → Znajdź | 1× `POST /v1/bike/parse` → panel filtrów otwarty, Marka `Trek`, Model `Marlin 5`, brak wyników (czeka na 2. submit) | High |
| TC-02 | **Zmiana tekstu** (rdzeń zmiany) | zmień tekst na `kross esker eco` → Znajdź | kolejny `POST /v1/bike/parse`; filtry = `KROSS` / `ESKER ECO`; **żadnego śladu** `Trek`/`Marlin`; brak `/v1/bike/search` w tym kroku | Critical |
| TC-03 | Tekst niezmieniony | Znajdź ponownie | **brak** nowego `/v1/bike/parse`; `POST /v1/bike/search` z brandem i modelem z filtrów; sekcja wyników widoczna | High |
| TC-04 | Ręczny filtr + niezmieniony tekst | ustaw Rozmiar ramy `M` → Znajdź | brak parse'a, `/v1/bike/search` zawiera `frame_size: "M"` oraz filtry z parse'a | Medium |
| TC-05 | Zmiana tekstu po ręcznym filtrze | zmień tekst na `merida silex 200` → Znajdź | parse wołany; ręcznie ustawiony `frame_size` też wyczyszczony; filtry = `MERIDA` / `SILEX 200` | High |
| TC-06 | Reset i powtórka tego samego tekstu (regresja) | klik `BIKER` → wpisz `merida silex 200` → Znajdź | filtry po resecie puste; parse wołany ponownie mimo tego samego tekstu co przed resetem | Medium |
| TC-07 | Regresja: brak błędów w konsoli | cały przebieg | brak błędów JS, brak odpowiedzi 5xx | Medium |

## Wyniki — runda 1 (2026-09-28, Playwright headless, :5176 → :8003)

**6 passed · 0 failed · 1 blocked (środowisko)**

| ID | Wynik | Dowód |
|---|---|---|
| TC-01 | Pass | 1× `POST /v1/bike/parse` → 200; Marka `Trek`, Model `Marlin 5` |
| TC-02 | **Pass** | 1× parse → 200, **0×** `/v1/bike/search`; Marka `KROSS`, Model `ESKER ECO`, zero `Trek`/`Marlin` |
| TC-03 | Pass | 0× parse, 1× `/v1/bike/search` → 200, sekcja wyników widoczna |
| TC-04 | Pass | 0× parse, 1× `/v1/bike/search`, `frame_size` pozostał `M` |
| TC-05 | Pass | 1× parse; `MERIDA` / `SILEX 200`, ręczny `frame_size` wyczyszczony na `""` |
| TC-06 | Pass | po resecie pole puste; ten sam tekst sparsowany ponownie → `MERIDA` |
| TC-07 | Blocked | jedyny błąd w konsoli i jedyne 5xx to `POST /v1/bike/search → 502` z TC-04: backend log `Your credit balance is too low to access the Anthropic API` (zapytanie z `frame_size: M` nie trafiło w DB i poszło do AI). Niezależne od tej zmiany — kredyty API wyczerpane od 2026-09-26; brak jakichkolwiek błędów JS aplikacji |

