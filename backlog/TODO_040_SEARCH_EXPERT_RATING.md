# TODO-040 — Ocena eksperta na kartach wyników wyszukiwania; usunięcie „Dopasowania”

**Branch:** `feature/040-search-expert-rating`
**Worktree:** `C:\Users\kamil_wolny\Projects\biker-wt\feature-039-search-expert-rating` (backend 8001, frontend 5174)
**Status:** TODO

## Potwierdzona intencja (wywiad 2026-09-30)

- **Rezultat:** karta wyniku wyszukiwania wygląda jak karta „Najpopularniejsze rowery” na stronie
  głównej: duża liczba = ocena eksperta z recenzji, pasek „Ocena eksperta”, a **„?”** (zamiast
  „—”/„Brak oceny”) gdy recenzji nie ma w cache. Strona główna też pokazuje „?” zamiast „—”/„Brak oceny”
  po ustaleniu braku oceny (spójny wygląd obu list).
- **„Dopasowanie” (`match_score`) znika wszędzie:** z karty wyniku, z nagłówka `BikeDetailsView`
  (blok „Dopasowanie”), z odpowiedzi `POST /v1/bike/search` i `GET /v1/bike/search-cache`, z promptu
  `bike_search.md`, z `bike_finder.py`, z `BikeResult`, z `Bike` (frontend) i z kolumny
  `search_bike_rating_cache.rating` w bazie.
- **Źródło oceny:** wyłącznie recenzje już zapisane w generic cache (`endpoint_req_to_body_cache`,
  endpoint `/v1/bike/review`) — przez **nowy tani endpoint odczytu**, bez żadnego wywołania AI.
  „?” nie odpala niczego.
- **Kolejność wyników:** po ocenie eksperta malejąco, rowery z „?” na końcu (a wśród nich kolejność
  z odpowiedzi backendu).
- **Wyjaśnienie** („Pasuje: …” / opis z AI) **zostaje** na karcie; `accessories` zostają.
- **Poza zakresem:** nowe wywołania `/v1/bike/review`; logika strony głównej (poza „?”); equipment;
  widok szczegółów poza usunięciem bloku „Dopasowanie”.

## Ograniczenia

- Kredyty Anthropic API są wyczerpane (od 2026-09-26): nie-cache'owane endpointy AI odpowiadają 400/500.
  QA na rowerach, które **mają** recenzję w cache (np. 3 rowery z `bike_popular`) i na takich, które nie mają.
- Migracja bazy: idempotentna, jedna transakcja, `--dry-run`, SQLite i PostgreSQL, uruchamiana **przed**
  deployem backendu (wzór: `scripts/migrate_photos_bike_id.py`). Stary backend zapisuje `rating` —
  po migracji jego `save_search` się wywali (rollback, WARNING, nic nie ginie) do czasu deployu nowego.

## Plan implementacji

### 1. Backend (Opus)

1. **Nowy endpoint (kontrakt ustalony, wiążący dla obu stron)** `POST /v1/bike/review/cached`
   — request `{ "bikes": [{ "company": "Trek", "model": "Marlin 5" }, …] }` (1–100 pozycji, każda
   `company`/`model` niepuste, ≤ 255 znaków; 422 inaczej), odpowiedź
   `{ "ratings": [{ "company", "model", "rating": float | null, "found": bool }, …] }` — **ta sama
   kolejność i te same wartości `company`/`model` co w żądaniu** (frontend dopasowuje po indeksie lub
   po kluczu brand+model).
   Dla każdej pozycji czyta **tylko** `cache.get_cached("/v1/bike/review", {company, model}, BikeReviewResponse)`
   (ta sama normalizacja kluczy co zapis w `/v1/bike/review`); `found=false, rating=null` gdy brak
   wpisu, gdy `rating <= 0` lub `sources_used < 1` (placeholder „brak recenzji”). Zero AI, zero zapisu
   (żadnego `set_cached`), błąd DB → 200 z `found: false` dla wszystkich + ERROR log. < 1 s.
2. **Usunąć `match_score`**: `schemas.BikeResult` (pole), `bike_finder.py` (parsowanie, clamp),
   `prompts/bike_search.md` (pole, reguła „4 lub mniej”, przykład — zostawić wymóg wyjaśnienia
   nazywającego niespełniony filtr), `repository.find_bikes_by_details` (`_latest_ratings` już bez
   ratingu; sortowanie po `brand`/`model`, bez `-match_score`), `repository.py` / `store.py`
   (`_row_to_bike`, `save_search`, `get_search_by_query`, `find_bikes_by_brand`),
   `schemas.CachedSearchResponse` jeśli zawiera score.
3. **Model + migracja**: usunąć kolumnę `SearchBikeRating.rating` z `app/models.py`; dodać
   `scripts/migrate_drop_search_rating.py` (`--dry-run`, `--db`, `--url`; SQLite: rebuild tabeli lub
   `ALTER TABLE DROP COLUMN`, PostgreSQL: `ALTER TABLE search_bike_rating_cache DROP COLUMN rating`
   pod `LOCK TABLE … SHARE ROW EXCLUSIVE`; idempotentny — brak kolumny = nic do zrobienia; weryfikacja
   liczby wierszy przed/po). Wpis w `backend/app/DB_MIGRATION.md`. `display_order` **zostaje**
   (to kolejność z odpowiedzi AI, nie wynik dopasowania).
4. **Smoke testy** w `backend/scripts/test_search.py`: `case_review_cached` (fixture: wpis w generic
   cache pod `/v1/bike/review` z `rating` 8.4 → `{rating: 8.4, found: true}`; nieznany rower →
   `{rating: null, found: false}`; wpis z `rating: 0` → `found: false`; < 5 s, brak nowego wiersza w
   cache), istniejące case'y search bez `match_score` w asercjach. Uruchomić `python scripts/test_search.py`
   na lokalnym Postgresie (port 8001).
5. **Dokumentacja**: `backend/README.md` § Endpoints (nowy endpoint z raw HTTP + Flow „brak wywołań
   wychodzących”; `/v1/bike/search` bez `match_score`), `CLAUDE.md`, `README.md`,
   `backend/app/DB_MIGRATION.md`, Backend Setup (kolejność deployu: migracja → backend → frontend).

### 2. Frontend (Sonnet) — równolegle z backendem, według kontraktu z pkt 1.1

1. `types.ts`: `Bike` bez `match_score`; nowy typ odpowiedzi endpointu cache; `ExpertRating` bez zmian.
2. Wyciągnąć z `usePopularBikes.ts` klucz i typ ratingu do współdzielonego modułu (np.
   `src/ratings.ts`: `bikeKey`, `PENDING_RATING`, `NO_RATING`); nowy hook `useCachedRatings(bikes)`
   — po każdym nowym wyniku wyszukiwania woła endpoint cache (jeden batch albo N równoległych POST),
   z `ignore`/`AbortController` jak w `usePopularBikes`, wynik do `Record<key, ExpertRating>`.
3. `App.tsx`: sekcja wyników renderuje `ResultCard` z `expertRating` (pending → loaded/error),
   `isTop={false}` (bez odznaki „najlepsze dopasowanie” — nie ma już dopasowania), sortowanie
   posortowanych ocen malejąco, „?” na końcu w kolejności backendu; sortowanie stabilne, dopiero gdy
   wszystkie oceny się rozstrzygną (żeby karty nie skakały) — do czasu: kolejność backendu.
4. `ResultCard.tsx`: usunąć gałąź `match_score` (numeral, `%`, `scoreLabel`, aria „dopasowanie”);
   `expertRating` staje się wymagany; stan `error` (brak oceny) pokazuje **„?”** jako numeral i
   etykietę „Brak oceny”; pending — „—” zostaje tylko na czas ładowania. Strona główna dziedziczy „?”.
5. `BikeDetailsView.tsx`: usunąć blok „Dopasowanie” i warunek `match_score > 0`;
   `PopularBikesSection.tsx` bez `match_score: 0`.
6. `npm run build` + `npx tsc --noEmit` bez błędów. Dokumentacja: `frontend/README.md`, `CLAUDE.md`
   (tabela Frontend, API integration), `README.md`.

### 3. QA — `/manual-tester` (Sonnet) — po obu etapach

- Porównać diff z tym plikiem, zbudować plan ISTQB (`qa-manual-istqb`) w `docs/testing/TODO_040/TEST_PLAN.md`,
  wykonać w przeglądarce (`webapp-testing`, frontend 5174 → backend 8001, lokalny Postgres `biker-pg`).
- Przypadki minimum: (a) wyszukiwanie zwracające rower z recenzją w cache → liczba i pasek jak na
  stronie głównej; (b) rower bez recenzji → „?”, pasek pusty, aria „brak oceny”, **zero** żądań
  `/v1/bike/review` w sieci; (c) kolejność: oceny malejąco, „?” na końcu; (d) brak „Dopasowanie”
  i „%” na karcie i w nagłówku szczegółów; (e) strona główna nadal działa, „?” zamiast „—” po błędzie;
  (f) `GET /v1/bike/search-cache?query=…` bez `match_score`; (g) migracja `--dry-run` i realna na
  kopii SQLite + lokalnym Postgresie, drugie uruchomienie = no-op; (h) smoke testy zielone.
- Pętla fix → retest do zielonego; błędy wracają do koordynatora.

### 4. Zamknięcie

- PR na `main` (opis: co usunięto, nowy endpoint, kolejność deployu: migracja na Cloud SQL → backend →
  frontend). Po merge: `DONE_040_…` do `backlog/done/` + wpis w `backlog/done/README.md`.
- **Deploy tylko na wyraźną decyzję użytkownika** (migracja usuwa kolumnę na produkcji).
