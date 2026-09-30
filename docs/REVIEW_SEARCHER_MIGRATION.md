# Jak recenzja eksperta przeszła z endpointu backendu do searchera (TODO-037)

Zapis całego procesu — od stanu wyjściowego, przez wywiad, sondy, implementację, przeglądy, testy, aż po wdrożenie — z
datami 2026-09-29/30. Piąta powtórka schematu z `docs/OLX_SEARCHER_MIGRATION.md` (TODO-031),
`docs/DECATHLON_SEARCHER_MIGRATION.md` (TODO-032), `docs/ALLEGRO_SEARCHER_MIGRATION.md` (TODO-033) i
`docs/PHOTOS_SEARCHER_MIGRATION.md` (TODO-035). Branch `feature/036-review-searcher` (worktree
`biker-wt/feature-035-review-searcher` — numeracja rozjechała się dwa razy, § 7), zadanie
`backlog/done/DONE_037_REVIEW_SEARCHER.md`, plan i wyniki testów `docs/testing/TODO_037/TEST_PLAN.md` +
`docs/testing/TODO_037/REAL_STACK_RESULTS.md`. PR #118 zmergowany i wdrożony na GCP 2026-09-30 — patrz § 8.

## 1. Punkt wyjścia

`POST /v1/bike/review` w backendzie przy każdym nieskeszowanym rowerze sam wołał model:

1. `backend/app/bike_review_finder.py` — jedno wywołanie Anthropic SDK (`claude-haiku-4-5-20251001` +
   `web_search_20250305`) z promptem `prompts/bike_review.md`; model zwracał oceny per źródło, a backend liczył z nich
   ważony `rating` (3/2/1), kotwiczenie przy rozjeździe źródeł (`DISAGREEMENT_THRESHOLD` 3.0), kolejność `ref` wg tierów;
   gdy w odpowiedzi nie było JSON-a — dodatkowe wywołanie „naprawcze” bez narzędzi z prefillem `{`.
2. Wynik jako blob JSON w generycznym cache `endpoint_req_to_body_cache` pod kluczem `'/v1/bike/review'` (tylko gdy `ref`
   niepuste i `sources_used >= 1`), bez TTL.
3. Endpoint był wołany **automatycznie**: przy każdym otwarciu szczegółów roweru i przez stronę główną (TODO-034 — jedna
   recenzja na kartę popularnego roweru).

Problem: klucz API nie ma kredytów od 2026-09-25/26, więc każdy rower bez recenzji w cache dostawał **400** (handler
`anthropic.BadRequestError`) — na stronie głównej i w szczegółach. Cel: zrobić z recenzją to, co TODO-033 zrobiło z
Allegro — szybki odczyt z bazy przy otwarciu roweru, a płatne wyszukiwanie (`claude -p` na subskrypcji) dopiero po
kliknięciu **Poproś o dane**.

## 2. Wywiad i decyzje

| Kwestia | Decyzja |
|---|---|
| Co odpala wyszukiwanie? | **Tylko przycisk „Poproś o dane”** w sekcji „Recenzja eksperta”, dokładnie jak karty ofert Allegro; nigdy automatycznie |
| Gdzie trzymać recenzje? | Najpierw „obecny cache” (generyczny), **potem użytkownik zmienił zdanie: „Stwórz nową tabelę”** — dwie tabele: `bike_review` (`bike_id` UNIQUE FK → `bike.id` ON DELETE CASCADE, `score`, `explanation`, `rating`, `sources_used`, `created_at` / `updated_at`, bez TTL) + `bike_review_source` (`review_id` FK CASCADE, `url` String(2048), `display_order`) |
| Istniejące recenzje w cache | **Skrypt kopiujący** `backend/scripts/copy_review_cache_to_table.py`; stare wiersze cache zostają jako martwe (nic ich nie czyta) |
| `/v1/equipment/review` | **Bez zmian** — dalej SDK i generyczny cache |
| Gdzie żyje wyszukiwanie? | Nowa trasa `POST /v1/search/review` w istniejącym `biker-searcher` (ten sam obraz, sekrety, IAM) |
| Baza brancha | Na prośbę użytkownika **od `feature/photos-searcher` (PR #115)**, żeby nie konfliktować; po merge'u #115 rebase na `main` (stąd limit searchera 10, nie 2) |

Zmiana decyzji o tabeli przyszła w trakcie wywiadu, przed pierwszą linijką kodu — kosztowała jedną poprawkę pliku zadania.
Poza zakresem: recenzja sprzętu, ocena eksperta w wynikach wyszukiwania (osobny pomysł), TTL/odświeżanie, kasowanie starych
wierszy cache, deploy bez zgody.

## 3. Sondy — przed kodem

Jak poprzednio: zanim powstała linijka kodu, `claude -p` przez argv searchera (`claude-haiku-4-5`, WebSearch + WebFetch,
`--json-schema`), rowery Trek Marlin 5 i Kross Level 3.0.

| Sonda | Wynik |
|---|---|
| 1. Prompt SDK skopiowany 1:1, Trek Marlin 5 | **154,6 s, 42 tury, $0,85**; poprawny JSON, rating 7,8 / 4 źródła — ale cytował **zakazany** `escapecollective.com`, blog afiliacyjny bestbikeselect oznaczył jako `pro_numeric`, a wątek mtbr, którego fetch był przekierowany, i tak zacytował |
| 2. Ten sam prompt, Kross Level 3.0 | 71,1 s, 23 tury, $0,51, rating 6,2 / 3 źródła |
| Osiągalność (WebFetch) | bike-test, bikeradar, bikexchange, singletracks, cyclistshub, polskie fora — OK; `mtbr.com` przekierowuje (tylko snippety); **nic nie odpowiada 403 jak allegro.pl** — Playwright ani tryb „tylko snippety” niepotrzebne |
| 3. Szkic v1: 8 WebSearch / 4 WebFetch, cytuj tylko pobrane strony | **199,5 s, 14 tur, $0,32, 1 źródło** (yescycling, 8,0) — odrzucony: za ciasny, za mało źródeł |
| 4. **Prompt końcowy** | **70,2 s, 12 tur, $0,24**, rating 7,4 / 3 źródła (mtbinsider `pro_qualitative` 8, cyclistshub `pro_qualitative` 7, wątek mtbr `community` 7) |

Prompt końcowy (`searcher/app/prompts/bike_review.md`, już nie byte-identyczny z SDK-owym): maks. 6 WebSearch / 3 WebFetch;
celuj w 2–4 źródła; wynik wyszukiwania można cytować, gdy tytuł + snippet jasno pokazują recenzję **tego** modelu; nigdy nie
cytuj przekierowanego ani nieudanego fetcha; `pro_numeric` tylko dla wymienionych redakcji; blogi afiliacyjne/SEO najwyżej
`pro_qualitative`; modele pokrewne się nie liczą; lista zakazanych domen. Wynik: **koszt ÷3,5, czas ×2 szybciej** wobec
kopii 1:1. Polszczyzna Haiku ma literówki (tak samo jak w wersji SDK).

Konsekwencje dla kodu: strażnik `BANNED_REVIEW_DOMAINS` = {escapecollective.com, velominati.com} w kodzie (prompt to nie
gwarancja); przebieg naprawczy SDK usunięty — `--json-schema` daje zwalidowany obiekt albo błąd CLI (→ 502);
`SEARCHER_CLI_TIMEOUT` zostaje 300 s (runy 70–200 s).

## 4. Kontrakt między modułami (spisany w pliku zadania przed implementacją)

**Searcher**
- `POST /v1/search/review` `{company, model}` + `X-Searcher-Key` → `{review: {score, explanation, ref, rating,
  sources_used}, bike_id, saved}`; 401/422/502/503/500 jak pozostałe trasy, **wspólny semafor** `SEARCHER_MAX_CONCURRENT`
  (10). Rower z zapisaną używalną recenzją dostaje ją z bazy z `saved: 0` — **przed** sprawdzeniem zajętości i bez CLI;
  po zajęciu slotu jeszcze raz sprawdzane (inne żądanie mogło właśnie zapłacić).
- `app/review_finder.py` — `find_bike_review()` przez `run_structured` (`claude -p --json-schema`); pomocnicze funkcje
  agregacji przeniesione z `bike_review_finder.py` (wagi 3/2/1, ≥ 1 źródło pro dla niezerowego ratingu, kotwiczenie +
  polskie zdanie o rozjeździe, `ref` Tier 1 → 3, usuwanie `<cite>`), `is_safe_review_url`, `EXPLANATION_MAX_LEN` 4000.
  Bez Playwrighta.
- `app/repository.py` — `save_review` (upsert `bike_review` + podmiana `bike_review_source`, jedna transakcja, wiersz
  roweru tworzony gdy brak; zapis **tylko** gdy `ref` niepuste i `sources_used >= 1`), `get_stored_review`.
- `app/models.py` — dosłowna kopia DDL obu tabel, obie w `REQUIRED_TABLES` (searcher bez nich nie wstaje).

**Backend**
- `POST /v1/bike/review` → `reviews_repository.get_review()` — czysty odczyt (`ORDER BY display_order, id`), bez AI, bez
  cache, bez TTL; nieznany rower / brak recenzji / błąd bazy → **200** z pustą recenzją `{0, "", [], 0.0, 0}` (błąd bazy
  dodatkowo ERROR w logu). Kształt odpowiedzi bez zmian.
- `POST /v1/bike/review/search` → **404** „Bike not found” przed czymkolwiek; zapisana używalna recenzja → zwracana bez
  wywołania searchera; inaczej proxy `searcher_client.search_review()` (single-flight, wspólny limit „w locie”, 429 = busy);
  503 „Review searcher is not configured / unavailable / is busy — try again in a moment”, 502 z `detail` searchera.
- `scripts/copy_review_cache_to_table.py` (SQLite i PostgreSQL, `--dry-run`, `--force`, `--db` / `--url`, idempotentny);
  `scripts/seed_popular_bikes.py` czyta rating z `bike_review`.
- Usunięte: `app/bike_review_finder.py`, `app/prompts/bike_review.md` (→ searcher, przepisany), `scripts/test_review.py`.

**Frontend**
- `App.tsx` — `searchReview(bike)` → `POST /v1/bike/review/search`, wynik do `review` bez przełączania na `'loading'`,
  `selectedBikeRef` odrzuca spóźnione wyniki; `BikeDetailsView` dostaje `onSearchReview`.
- Sekcja recenzji: `RequestDataButton` z `onRequested`, `pendingLabel="Szukam recenzji…"`,
  `emptyLabel="Nie znaleziono recenzji"`; błąd → przycisk znów klikalny. Strona główna (`usePopularBikes`) bez zmian —
  `/v1/bike/review` odpowiada teraz natychmiast z bazy, rating 0 dalej czyta się jako „Brak oceny”.

## 5. Implementacja i przeglądy

Agenci równolegle, rozłączne pliki: Opus — searcher, backend-db (modele, repozytorium, skrypt kopiujący, seed),
backend-api (trasy, klient), frontend; Sonnet — plik zadania i dokumentacja. Potem dwa przeglądy (bezpieczeństwo,
poprawność). W trakcie sesji pojawiła się allowlista powłoki (lean-ctx), która blokowała `python.exe` i `netstat`, dopóki
użytkownik jej nie dopuścił/usunął.

| Waga | Znalezisko | Poprawka |
|---|---|---|
| **HIGH** (bezp.) | `/v1/bike/review/search` puszczał płatny run także dla roweru, który ma już recenzję, i ją nadpisywał — pętla `curl` = nieograniczony koszt subskrypcji i podmiana dobrych danych | **backend i searcher** zwracają zapisaną recenzję bez uruchamiania CLI (searcher sprawdza jeszcze raz po zajęciu slotu) |
| MEDIUM (bezp.) | URL-e w `ref` niewalidowane — pośrednie wstrzyknięcie promptu przez stronę z wyników mogło podsunąć link phishingowy do tabeli źródeł | `is_safe_review_url` (http/https + host, ≤ 2048, poza zakazanymi domenami) w searcherze **i** w skrypcie kopiującym; frontend renderuje tylko `isWebUrl` |
| LOW (bezp.) | `explanation` bez limitu | przycięcie do 4000 znaków (razem ze zdaniem o rozjeździe) |
| LOW (bezp.) | trasa searchera bez single-flight | **nie naprawione** — backend ma single-flight, a searcher i tak odda zapisaną recenzję po pierwszym runie |
| MEDIUM (popr.) | kolejność wdrożenia: nowy searcher nie wstaje bez tabel, a `deploy.ps1` wdraża searcher pierwszy | udokumentowane — tabele muszą powstać przed deployem (§ 8) |
| LOW (popr.) | nieaktualne odwołania w skillach do usuniętych plików | poprawione |
| LOW (popr.) | `copy --force` cofał `updated_at` | `max()` starej i nowej daty |
| LOW (popr.) | przy kilku wierszach cache dla jednego roweru wygrywał przypadkowy | wygrywa najnowszy (`ORDER BY time_stored DESC`) |

Poza tym: logika ratingu porównana ze starym finderem na **300 losowych wejściach — identyczna**; testy agregacji
przeniesione (19).

## 6. Weryfikacja

- Testy automatyczne (po rebase): backend `pytest` **44 passed**, searcher **19 passed**, webscraper **160 passed**,
  `npm run build` OK.
- **Stack z fałszywym searcherem** (`qa-fake`, kopia SQLite, fałszywy searcher na 8112 wybierający odpowiedź po nazwie
  modelu: Empty / Fail / Busy / Slow / sukces): **28/28** — odczyt z bazy, normalizacja nazw, pusta recenzja, 422, 404
  przed searcherem, 502/503 → przycisk znów klikalny, „Nie znaleziono recenzji”, spóźniony wynik po zmianie roweru
  odrzucony, strona główna, regresja recenzji sprzętu.
- **Prawdziwy stack** (`qa-real`, kopia `cache.db`, prawdziwy CLI 2.1.285): **9/9**.
  - M1 skrypt kopiujący: dry-run „26 wierszy → skopiowałby 17, 9 zdegenerowanych, 0 nieznanych rowerów”; run: 17
    `bike_review` / 57 `bike_review_source`; drugi run: 0 zmian; 17/17 zgodnych z blobami (w tym kolejność `ref`).
  - R3 płatny run z UI, podejście 1: **limit sesji subskrypcji** — CLI 429 → 502 „claude CLI failed: exit 1” po 11,6 s,
    przycisk znów klikalny, nic nie zapisane. Podejście 2 (po resecie limitu), Trek Marlin 5: **105 s** od kliknięcia (CLI
    104 s, 10 tur, $0,20), rating 6,7, 2 źródła (mtbinsider, mtbr), polskie wyjaśnienie; potem karta na stronie głównej
    6,7.
  - R4 strażnik kosztów: rower z recenzją → backend 200 w **0,012 s** bez wywołania searchera; searcher z kluczem → 200,
    `saved: 0`, bez nowego `claude CLI start`.
  - R6 nieznany rower → 404 bez wiersza `bike`; R7 seed dry-run → 11 kwalifikujących się rowerów; R8 searcher bez tabel
    odmawia startu.

## 7. Commit i PR

PR #118, po rebase jeden commit `d7f08d2`, merge `87c1105`. Branch był oparty na `feature/photos-searcher` i przebazowany,
gdy #115 wszedł do `main`; potem `main` dostał kolejkę odkrywania rowerów (TODO-036, #119/#120), która zajęła numer 036,
więc przy ostatnim rebase zadanie przemianowano na **TODO-037** (nazwa brancha `feature/036-review-searcher` i katalog
worktree `feature-035-review-searcher` zostały). Pierwsza próba merge'a miała konflikty po #116/#117/#119/#120. Merge
zrobił użytkownik — `gh pr merge` był dla Claude zablokowany przez klasyfikator trybu auto.

## 8. Wdrożenie na GCP (2026-09-30)

**Kolejność:** `deploy.ps1` wdraża searcher pierwszy, a nowy searcher odmawia startu bez `bike_review` /
`bike_review_source` — więc tabele muszą powstać na Cloud SQL **przed** deployem (skrypt kopiujący tworzy je przez
`init_db()`; alternatywnie najpierw `-Only backend`).

| Krok | Kto | Co |
|---|---|---|
| Kopia zapasowa | ja | Cloud SQL on-demand „before review tables (PR 118)” |
| Dry-run kopiowania | ja | `copy_review_cache_to_table.py --dry-run` na Cloud SQL przez proxy: 26 wierszy → skopiowałby 17, 9 zdegenerowanych, 0 nieznanych rowerów, 0 odrzuconych URL-i |
| Właściwe kopiowanie | **użytkownik** (`!` w prompcie) | zablokowane dla Claude przez klasyfikator („Production Deploy”); `!` to Git Bash — forma PowerShell nie zadziałała. Wynik: **skopiowano 17** |
| Obrazy + Cloud Run | ja | `scripts/deploy.ps1` z czystego worktree `biker-wt/deploy-87c1105` → `biker-searcher-00005-94r`, `biker-backend-00010-56r`, `biker-frontend-00008-hrk` |
| Sekrety / IAM | nikt | nic nowego |
| Weryfikacja | ja | `/v1/bike/review` Trek Madone SL 6 z tabeli; `/v1/bike/popular` OK; `/v1/bike/review/search` z zapisaną recenzją → 200 w **0,13 s**; nieznany rower → 404; searcher `/health`: `claude_cli` 2.1.283, `database: true`. **Bez płatnego runu na produkcji** |

## 9. Architektura po zmianie

```
przeglądarka ──klik „Poproś o dane” (sekcja Recenzja eksperta)──► frontend (nginx / Vite)
   │                                                                  │ /v1/*
   │  POST /v1/bike/missing  (licznik review)                         ▼
   │  POST /v1/bike/review/search ──────────────────────► backend (Cloud Run biker-backend)
   │                                                        │ bike_exists? → nie: 404
   │                                                        │ zapisana recenzja z źródłami? → tak: 200 z bazy (0 runów)
   │                                                        │ single-flight (rower), max 10 w locie, 600 s, 429 = busy
   │                                                        ▼  POST /v1/search/review  +  X-Searcher-Key
   │                                                 searcher (Cloud Run biker-searcher, --concurrency 1)
   │                                                        │ zapisana? → saved 0, bez CLI (przed i po zajęciu slotu)
   │                                                        │ claude -p --json-schema (subskrypcja), WebSearch ≤ 6 / WebFetch ≤ 3
   │                                                        │ agregacja 3/2/1, kotwiczenie, zakazane domeny, is_safe_review_url
   │                                                        ▼
   │                                                 Cloud SQL biker-pg: bike_review + bike_review_source
   │                                                        ▲   (zapis tylko gdy ref niepuste i sources_used >= 1)
   ├── automatycznie przy otwarciu roweru: POST /v1/bike/review ── czysty odczyt ──┤
   └── strona główna (usePopularBikes): POST /v1/bike/review × karta ─────────────┘
```

Pliki: searcher `app/review_finder.py` (nowy), `app/prompts/bike_review.md` (przeniesiony, przepisany pod CLI),
`app/{main,models,repository,schemas}.py`, testy agregacji, `scripts/test_searcher.py`, `README.md`; backend
`app/{main,models,searcher_client}.py`, `app/reviews_repository.py` (nowy), `scripts/copy_review_cache_to_table.py`
(nowy), `scripts/{seed_popular_bikes,test_search}.py`, `app/DB_MIGRATION.md`, `README.md`; frontend `App.tsx`,
`BikeDetailsView.tsx`, `BikeDetailsShared.tsx`, `RequestDataButton.tsx`, `README.md`; `CLAUDE.md`, `README.md`,
`docs/testing/TODO_037/`. Usunięte z backendu: `app/bike_review_finder.py`, `app/prompts/bike_review.md`,
`scripts/test_review.py`.

## 10. Jak tego używać

```bash
# kopia recenzji z generycznego cache (raz na każdej bazie; tworzy tabele)
cd backend && python scripts/copy_review_cache_to_table.py --dry-run && python scripts/copy_review_cache_to_table.py

# ręcznie na searcherze (lokalnie: klucz z searcher/.env)
curl -X POST http://localhost:8100/v1/search/review \
  -H "Content-Type: application/json" -H "X-Searcher-Key: dev-local-searcher-key" -d '{"company":"Trek","model":"Marlin 5"}'

# przez backend (to, co robi przycisk w sekcji recenzji)
curl -X POST http://localhost:8000/v1/bike/review/search -H "Content-Type: application/json" -d '{"company":"Trek","model":"Marlin 5"}'
curl -X POST http://localhost:8000/v1/bike/review        -H "Content-Type: application/json" -d '{"company":"Trek","model":"Marlin 5"}'
# nieznany rower → 404; rower z recenzją → zapisana recenzja, bez runu

# smoke testy (darmowe)
cd backend && python scripts/test_search.py        # case_review + case_review_search (404)
cd searcher && python scripts/test_searcher.py     # 401/422 na /v1/search/review
```

## 11. Czego nie ma (świadomie) i co dalej

- **Recenzje przeniesione na produkcji są w starym formacie** (angielskie wyjaśnienie, znaczniki `<cite>`), dopóki ktoś
  ich nie wyszuka ponownie — a zapisana recenzja **blokuje** ponowne wyszukiwanie (poprawka HIGH), więc zostaną, dopóki
  wiersz nie zostanie ręcznie usunięty z `bike_review`.
- **Limit sesji subskrypcji** (CLI 429) wychodzi jako ogólne 502 „claude CLI failed: exit 1” na każdej trasie searchera;
  lepszy byłby 503 z jasnym komunikatem „spróbuj później” — osobne zadanie.
- `/v1/equipment/review` dalej na Anthropic SDK i kluczu bez kredytów.
- Brak limitu żądań na IP dla anonimowych wyszukiwań (rower bez recenzji, dla którego run nic nie znalazł, można szukać
  bez końca przez `curl`).
- Trasa searchera bez single-flight (LOW z przeglądu, świadomie).
- Ocena eksperta w wynikach wyszukiwania — osobny pomysł; brak TTL/odświeżania recenzji; stare wiersze cache
  `'/v1/bike/review'` zostają martwe.

## 12. Lekcje

1. **Sonda przed kodem po raz kolejny się opłaciła**: kopia promptu 1:1 działała technicznie, ale kosztowała $0,85 i
   cytowała zakazane źródła; strojenie przed implementacją dało koszt ÷3,5 i czas ×2 szybciej. Pierwsza „poprawa” (tylko
   pobrane strony) była gorsza — sonda odrzuciła ją w 3 minuty, zanim trafiła do kodu.
2. **Decyzja z wywiadu może się zmienić w połowie** (cache → nowa tabela) — i jest wtedy tania, bo przed kodem. Warto
   robić restate przed startem implementacji, nie po.
3. **Numeracja backlogu koliduje między równoległymi worktree** (035 zdjęcia, 036 kolejka odkrywania) — numer zadania
   sprawdzać na `main` tuż przed założeniem pliku, a nie na początku sesji.
4. **Granice klasyfikatora** (merge PR-a, zapis do produkcyjnej bazy) trzeba zaplanować: kroki dla użytkownika przez `!`
   pisać w składni Git Bash, bo tak jest wykonywany `!`.
5. **Trasa „szukaj na żądanie” musi najpierw sprawdzić, czy już nie ma wyniku** — bez tego przycisk w UI jest bezpieczny,
   a `curl` w pętli już nie. Sprawdzenie po obu stronach (backend i searcher, także po zajęciu slotu) kosztuje jeden odczyt.
