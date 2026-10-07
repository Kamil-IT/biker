# TODO-045 — Kalkulator rozmiaru ramy w zakładce „Rower na Twoją miarę”

**Branch:** `feature/frame-size-calculator`
**Worktree:** `C:\Users\kamil_wolny\Projects\biker-wt\feature-frame-size-calculator`
**Status:** TODO — zaimplementowane i przetestowane ręcznie (3 rundy, 68/68 PASS, `docs/testing/TODO_045/TEST_PLAN.md`), niezacommitowane; do `backlog/done/` po merge'u PR
**Makieta:** `docs/mockups/zakladki/rower-na-twoja-miare-kalkulator.html` (w głównym checkoutcie, poza gitem; tu liczy JS — w aplikacji liczy backend)

## Cel (ustalone w /interview-me, 2026-10-06)

Zakładka **„Rower na Twoją miarę”** (`/bike-for-your-fit`) przestaje być teaserem „Wkrótce” i staje się
kalkulatorem: użytkownik podaje **wzrost**, **długość nogi** (inseam) i **typ roweru**, a dostaje
zalecany **rozmiar ramy** (liczba + zakres + litera S/M/L) i ewentualne ostrzeżenie o nietypowym pomiarze.

- **Liczy backend.** Front nic nie liczy: wysyła dane i pokazuje odpowiedź.
- **Na żywo**: front woła backend podczas wpisywania, z opóźnieniem (debounce) ~300 ms.
- **Kończy się na liczbie** — żadnego przycisku „pokaż rowery w tym rozmiarze”.
- Założenie: `bike.category` istnieje (praca równoległa, `cez/8e26c033`), ale **to zadanie z niej nie korzysta**.
  Klucze typów są wybrane tak, by były podzbiorem przyszłej listy `BIKE_CATEGORIES`
  (`Road`, `MTB`, `Gravel`, `Touring`, `Hybrid/Commuter`), więc dopasowanie do bazy w przyszłości obejdzie się bez tłumaczenia.

## Poza zakresem

- Dopasowanie do rowerów z bazy (wymaga parsera rozmiarów ram — dziś `Frame / Frame / Sizes` ma 197 z 723 rowerów w różnych formatach — i `bike.category`).
- Geometria (stack, reach, seat tube, standover).
- Tabele rozmiarów per marka; tułów, ramiona, elastyczność.
- Typy Folding, BMX, Cruiser (oraz pozostałe z `BIKE_CATEGORIES`).
- AI, baza danych, generic cache, zapisywanie pomiarów użytkownika.

## Algorytm (backend, `app/frame_size.py`, czysta funkcja)

### Wejście

| Pole | Typ | Walidacja |
|---|---|---|
| `height_cm` | float | 140 ≤ x ≤ 210 |
| `inseam_cm` | float | 60 ≤ x ≤ 110 |
| `bike_type` | enum | `Road`, `MTB`, `Gravel`, `Touring`, `Hybrid/Commuter` |

Cokolwiek innego → **422** (Pydantic).

### Wzory

| Typ | Rozmiar | Jednostka | Zakres | Pewność |
|---|---|---|---|---|
| `Road` | inseam × 0,66 | `cm` | ± 2 cm | `good` |
| `MTB` | inseam × 0,226 | `in` (cale) | ± 0,8 in | `good` |
| `Gravel` | inseam × 0,65 − 1 | `cm` | ± 2 cm | `medium` |
| `Touring` | inseam × 0,66 | `cm` | ± 2 cm | `medium` |
| `Hybrid/Commuter` | inseam × 0,66 | `cm` | ± 2 cm | `medium` |

### Litery (tabela ogólna, orientacyjna)

| Litera | cm (`Road`, `Gravel`, `Touring`, `Hybrid/Commuter`) | in (`MTB`) |
|---|---|---|
| XS | < 50 | < 15 |
| S | 50 – < 53 | 15 – < 17 |
| M | 53 – < 56 | 17 – < 19 |
| L | 56 – < 59 | 19 – < 21 |
| XL | ≥ 59 | ≥ 21 |

Najpierw zaokrąglenie `size`, `range_min`, `range_max` do 0,1, potem litery z wartości **zaokrąglonych** — użytkownik nigdy nie zobaczy „53,0 cm → S” (178 / 80,3 / Road → 53,0 cm, M).

### Kontrola pomiaru

`measurement_warning = true`, gdy `inseam_cm / height_cm` jest poza **0,40 – 0,50** (prawdopodobnie zły pomiar długości nogi).
Wynik i tak jest liczony.

### Wyjście (`FrameSizeResponse`)

```json
{
  "bike_type": "Road",
  "size": 52.8,
  "unit": "cm",
  "range_min": 50.8,
  "range_max": 54.8,
  "letter": "S",
  "letters": ["S", "M"],
  "confidence": "good",
  "measurement_warning": false
}
```

| Pole | Opis |
|---|---|
| `size` | wynik wzoru, 1 miejsce po przecinku |
| `unit` | `cm` albo `in` (MTB) |
| `range_min`, `range_max` | `size` ∓ 2 cm / 0,8 in |
| `letter` | litera dla `size` (główna rekomendacja) |
| `letters` | wszystkie litery od litery `range_min` do litery `range_max`, rosnąco (1–3 pozycje) |
| `confidence` | `good` / `medium` |
| `measurement_warning` | stosunek nogi do wzrostu poza 0,40–0,50 |

Przykład kontrolny: `178 / 80 / Road` → `52.8 cm`, zakres `50.8–54.8`, `S`, `["S","M"]`, `good`, `false`.

## Backend

1. `backend/app/frame_size.py` — stałe (mnożniki, progi liter, zakres, próg stosunku) i
   `compute_frame_size(height_cm, inseam_cm, bike_type) -> FrameSizeResponse`. Bez I/O.
2. `backend/app/schemas.py` — `FrameSizeRequest` (walidacja zakresów, `bike_type` jako `Literal`), `FrameSizeResponse`.
3. `backend/app/fit_routes.py` — `APIRouter`, `POST /v1/fit/frame-size` (wzór: `contact_routes.py`);
   `main.py` tylko `include_router` (plik ma już ~600 linii). Log INFO z typem i wynikiem (bez danych osobowych poza liczbami).
4. Testy:
   - `backend/scripts/test_frame_size.py` (pytest, czysta funkcja): każdy typ, przykład kontrolny, granice liter
     (np. dokładnie 53,0 cm → M), MTB w calach, `letters` z 1 / 2 / 3 pozycjami, ostrzeżenie poniżej 0,40 i powyżej 0,50,
     brak ostrzeżenia na granicach 0,40 i 0,50.
   - Smoke `case_fit_frame_size` w `backend/scripts/test_search.py` (reguła projektu dla nowego endpointu): 200 i wartości
     przykładu kontrolnego, MTB → `unit == "in"`, 422 dla wzrostu 139, inseam 111 i typu `BMX`, brak wiersza w generic cache, < 5 s.

## Frontend

1. `frontend/src/components/FitPage.tsx` zastępuje `FitComingSoonPage.tsx` (teaser usunięty); `App.tsx` renderuje `FitPage` dla `route.name === 'fit'`.
2. `frontend/src/hooks/useFrameSize.ts` — przyjmuje surowe wartości pól; parsuje liczby (przecinek → kropka);
   gdy oba pola są liczbami, po **300 ms** bez zmian wysyła `POST /v1/fit/frame-size`; poprzednie zapytanie przerywa
   `AbortController` (także przy odmontowaniu — StrictMode). Stany: `idle` (puste / nie-liczby, bez zapytania),
   `loading` (poprzedni wynik zostaje na ekranie), `loaded`, `invalid` (422 → komunikat z zakresami), `error` (sieć / 5xx).
   **Żadnych wzorów ani progów we froncie.**
3. `frontend/src/types.ts` — `FitBikeType`, `FrameSizeRequest`, `FrameSizeResponse`.
4. UI według makiety, system „Café Rider” (tokeny z `src/index.css`):
   - pola **Wzrost** i **Długość nogi** (`cm`, `inputmode="decimal"`), pod nimi instrukcja pomiaru (książka między nogami, boso, do górnej krawędzi);
   - **Typ roweru**: pigułki-radio, etykiety jak w `SearchInput.tsx` `BIKE_TYPES` (Szosowy, Górski (MTB), Gravel, Miejski / crossowy, Trekkingowy); domyślnie Szosowy;
   - wynik na ciemnej karcie: szkic ramy, duża liczba z jednostką (`cm` / `cale`), litera, skala XS–XL z podświetlonymi `letters`
     (`letter` wyróżniona mocniej), „Zakres: 50,8–54,8 cm”, polskie przecinki dziesiętne;
   - `confidence: medium` → krótka uwaga, że dla tego typu wynik jest przybliżony;
   - `measurement_warning` → „Długość nogi wydaje się nietypowa przy tym wzroście. Zmierz ją jeszcze raz — od tego zależy wynik.”;
   - stan pusty: zaproszenie do wpisania danych; błąd: jasny komunikat, co zrobić;
   - `aria-live="polite"` na wyniku, widoczny focus, `prefers-reduced-motion` szanowany, działa na 360 px szerokości.
5. **Szkic ramy — poprawiony względem makiety** (w makiecie wymiar był schematyczny):
   - koła stałe, wysokość rury podsiodłowej rośnie **wyraźnie** z wynikiem (MTB przeliczone cale → cm tylko do rysunku);
   - linia wymiarowa **równoległa do rury podsiodłowej**, od osi suportu do górnej krawędzi rury, z **kreskami końcowymi**;
   - etykieta przy linii: „≈ 52,8 cm” (z „≈” — to rozmiar nominalny, nie zmierzona długość);
   - płynne przejście przy zmianie wyniku (bez animacji przy `prefers-reduced-motion`).

## Dokumentacja

`backend/README.md` (§ Endpoints: przykład HTTP + **Flow: none**), `frontend/README.md`, `README.md`, `CLAUDE.md`
(wiersze architektury backendu i frontendu, opis endpointu, lista integracji API).

## Kryteria akceptacji

- [x] `POST /v1/fit/frame-size` zwraca wartości zgodne z tabelą wzorów; 422 dla danych spoza zakresów i nieznanego typu.
- [x] Testy pytest `test_frame_size.py` i smoke `case_fit_frame_size` przechodzą.
- [x] `npm run build` przechodzi.
- [x] Zakładka pokazuje kalkulator; wpisanie 178 / 80 / Szosowy daje 52,8 cm, S, zakres 50,8–54,8 cm, skala S–M.
- [x] Zmiana typu na Górski (MTB) daje 18,1 cala, M (etykieta jednostki „cala” — dopełniacz po ułamku).
- [x] Wynik pojawia się bez klikania, a szybkie pisanie nie wysyła zapytania po każdym znaku (debounce).
- [x] Ostrzeżenie pojawia się dla 178 / 95 (stosunek 0,53).
- [x] Wymiar na szkicu ma kreski końcowe, leży wzdłuż rury podsiodłowej i ma „≈”.
- [x] Brak błędów w konsoli; widok działa na telefonie (360 px).

## Wdrożenie

Bez migracji i bez nowych tabel. Backend przed frontendem (nowy frontend na starym backendzie dostanie 404 z kalkulatora).
Deploy tylko na wyraźne polecenie użytkownika.
