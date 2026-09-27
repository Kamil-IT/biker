# Jak wyszukiwanie ofert Decathlonu przeszło z endpointu backendu do searchera (TODO-032)

Zapis całego procesu — od stanu wyjściowego, przez decyzje, implementację, testy, merge z konfliktem, aż po wdrożenie
na Cloud Run — z datą 2026-09-26. Powtórka schematu z `docs/OLX_SEARCHER_MIGRATION.md` (TODO-031) dla drugiego źródła.
Branch `feature/032-searcher-decathlon`, PR [#99](https://github.com/Kamil-IT/biker/pull/99) (+ [#101](https://github.com/Kamil-IT/biker/pull/101)
przeniesienie do `backlog/done/`, [#102](https://github.com/Kamil-IT/biker/pull/102) odchudzenie płatnych testów), zadanie
`backlog/done/DONE_032_SEARCHER_DECATHLON_ON_DEMAND.md`, plan i wyniki testów `docs/testing/TODO_032/TEST_PLAN.md`.

## 1. Punkt wyjścia

`POST /v1/bike/decathlon` w backendzie (`backend/app/main.py`) działał jak stare `/v1/bike/used`, tylko prościej:

1. `bike_offer_decathlon_finder.py` — jedno wywołanie Anthropic SDK (`claude-haiku-4-5-20251001` + `web_search_20250305`)
   z promptem `prompts/bike_offer_decathlon.md`; odpowiedź parsowana `extract_json()`; do 3 ofert (`data[:3]`), bez zdjęć
   (`photos: []` z założenia — strony Decathlonu wymagają JS).
2. Wynik do generycznego cache tylko gdy lista ofert niepusta.

Problemy:
- każde nieskeszowane otwarcie roweru paliło tokeny **klucza API**, który od 2026-09-26 ma zero kredytów — endpoint
  odpowiadał 500;
- Decathlon sprzedaje praktycznie tylko własne marki, więc dla Treka czy Canyona wywołanie było z góry zmarnowane —
  otwarte `TODO_ISSUE_010` („Decathlon offers always empty for non-Decathlon brands”);
- w Notion **nie było** zadania na tę zmianę (sprawdzone; nic tam nie odhaczano).

Prośba użytkownika brzmiała dosłownie: „`docs/OLX_SEARCHER_MIGRATION.md`, tylko teraz dla `/v1/bike/decathlon`” +
`/interview-me` + `/manual-tester`.

## 2. Wywiad i decyzje (`/interview-me`, 3 pytania)

Hipoteza startowa (pewność ~65 %): DB-only `/v1/bike/decathlon` + drugi endpoint w tym samym searcherze + przycisk w
karcie „Nowe”. Pytania zadawane pojedynczo, każde z własnym strzałem:

| Pytanie | Decyzja |
|---|---|
| Ten sam serwis `searcher` czy osobna usługa serverless dla Decathlonu? | **Ten sam searcher** („usługa serverless tak jak dla OLX”) — jeden obraz, jeden sekret, jeden slot CLI |
| Klik „Poproś o dane” w karcie „Nowe” ma odpalać tylko Decathlon (Allegro/Ceneo bez zmian)? | **Tylko Decathlon, tak samo jak OLX** |
| Pomijać obce marki bez runu CLI (zamyka ISSUE-010), czy 1:1 jak dziś? | **Pomiń obce, znajdź wszystkie marki Decathlonu** — allowlista w backendzie |

Restate (wynik / użytkownik / sukces / ograniczenia / poza zakresem) potwierdzone „tak”. Kolejność jak przy OLX:
plik backlogu → implementacja → smoke testy → `/manual-tester` lokalnie → **pytanie o zgodę** na deploy → Cloud Run
(ta sama Cloud SQL, bez pytania — zdecydowane przy TODO-031).

Lista marek własnych zweryfikowana w sieci (decathlon.pl odpowiadał 503 na fetch, więc z wtórnych źródeł):
Rockrider (MTB), Btwin/B'Twin (dzieci, składaki), Triban (szosa rekreacyjna), Van Rysel (szosa/gravel), Elops (miasto),
Riverside (trekking), Stilus (e-bike), Tilt (składaki) + token `decathlon` (część rowerów w bazie ma markę „Decathlon”).

## 3. Sonda: czy `claude -p` udźwignie prompt Decathlonu

Jeden run skryptem w scratchpadzie, który zaimportował **niezmieniony** `searcher/app/claude_cli.run_structured` ze
starym promptem backendu i schematem OLX (`{info, offers[]}`):

```
Find current offers on decathlon.pl for: Rockrider ST 100
→ 64 s, structured_output: 1 oferta, https://www.decathlon.pl/p/rower-gorski-mtb-27-5-cala-rockrider-st-100/_/R-p-192872, 1249 zł
```

Wniosek: wrapper CLI i schemat są wspólne dla obu źródeł — nowy moduł to tylko prompt, komunikat użytkownika i koercja
ofert (bez Playwrighta).

## 4. Kontrakt między modułami (spisany w `backlog/TODO_032_…` przed implementacją)

**Searcher**
- `POST /v1/search/decathlon` `{company, model}` + `X-Searcher-Key` → `{offers, info, bike_id, saved}`; 401/422/502/503/500
  jak `/v1/search/olx`; **wspólny semafor** (jeden run CLI na instancję niezależnie od źródła).
- `app/decathlon_finder.py` — `find_decathlon_offers()`: ≤ 3 ofert, URL musi zaczynać się od `https://www.decathlon.pl/`,
  dedupe, przycięcie do szerokości kolumn, `photos=[]`, `city=None`, `is_new` z modelu (domyślnie `true`), `source='decathlon.pl'`.
- `app/repository.py` — `save_used_offers` uogólnione do `save_offers(company, model, offers, source)`: upsert
  `ON CONFLICT (url) DO UPDATE … WHERE bike_id = ten rower AND source = to źródło`, kasowanie stale-rows w obrębie
  (rower, źródło), pusty wynik nic nie kasuje, `is_new` z oferty.

**Backend**
- `/v1/bike/decathlon` → `offers_repository.get_decathlon_offers()` (czysty odczyt, `_get_stored_offers(company, model, source)`
  z `is_new` z wiersza).
- `POST /v1/bike/decathlon/search`: **404** nieznany rower → **200 `{offers: [], info: "Decathlon nie sprzedaje marki X — …"}`**
  natychmiast dla obcej marki (`decathlon_brands.is_decathlon_brand`, normalizacja: lower-case bez apostrofów, myślników,
  kropek i spacji — „B'Twin”, „B-TWIN”, „VAN RYSEL” przechodzą) → proxy `searcher_client.search_decathlon()` (503 brak
  konfiguracji / niedostępny / zajęty, 502 z `detail`). Klient uogólniony: `SEARCH_PATHS`, klucz single-flight
  `(ścieżka, company, model)`, jeden semafor na oba źródła.
- `BikeOfferRequest` z `max_length=255`; stary finder i prompt **usunięte** z backendu (prompt `git mv` do searchera,
  byte-identyczny).

**Frontend**
- `App.tsx` `searchDecathlon` obok `searchUsedBikes` (bez przełączania stanu na `loading`, guard `selectedBikeRef`);
  `BikeDetailsView` prop `onSearchNew` → karta „Nowe” dostaje `onRequested` + `pendingLabel="Szukam na Decathlon…"`.
  `RequestDataButton` bez zmian.

## 5. Implementacja: workflow z trzema agentami, docs i trzema przeglądami

Jeden skrypt `Workflow`: faza *Implement* (searcher / backend / frontend równolegle, rozłączne pliki, wspólny kontrakt),
faza *Docs* (CLAUDE.md + README.md z podsumowań implementacji), faza *Review* (trzy soczewki: integracja, bezpieczeństwo
i koszty, konwencje i dokumentacja). 7 agentów, ~25 min, 0 błędów. Z poprzedniej rundy pamiętałem pułapkę `${PORT}` w
szablonie skryptu — tym razem prompty były zwykłymi stringami. Co przeglądy znalazły i co z tym zrobiłem:

| Znalezisko | Poprawka |
|---|---|
| **high** — test TC-35 tworzył świeżą tożsamość `Rockrider / ST 100`, a rower w bazie to `Decathlon / Rockrider ST 100`; URL produktu jest globalnie unikalny w `bike_offer`, więc test „ukradłby” ofertę rowerowi otwieranemu w UI | oba live testy (backend i searcher) używają tożsamości, którą aplikacja już ma; wiersz tworzony tylko gdy brak |
| **medium** ×2 — jeden URL produktu Decathlonu vs zduplikowane tożsamości tego samego roweru (`Decathlon / Rockrider ST 100`, trzy warianty `Van Rysel … GRVL GRX AF`): pierwszy zapisuje, sąsiad płaci run i dostaje „Nie znaleziono ofert” | świadomie **zostawione** (decyzja „tak samo jak OLX”), udokumentowane jako K1 w planie testów; naprawa to punkt 2 otwartego TODO-021 (zdjąć globalne `unique=True` z `url`, zostawić `(bike_id, url)`) |
| karta „Nowe” oferowała ponowne (płatne) wyszukiwanie, gdy zapisana oferta ma `is_new: false` (outlet → ląduje w „Używane”) | `onRequested` tylko gdy brak wierszy decathlon.pl (`hasDecathlonRows`); z wierszem przycisk to zwykły licznik |
| 502 przy zniekształconej odpowiedzi searchera relacjonował cały tekst błędu pydantic (kilobajty) | stałe zdanie w `detail`, pełny błąd w logu (dług z TODO-031) |
| TC-9 searchera i TC-35 backendu padały / milczały przy 0 ofert (searcher celowo zostawia stare wiersze) | tolerancja 0 ofert + WARNING; README bez nadinterpretacji |
| `DB_MIGRATION.md` mówił, że Decathlon idzie przez generyczny cache; komentarze compose/deploy „OLX searcher” | poprawione |
| dokumentacja obiecywała `is_new: true`, a wartość jest z modelu | „`is_new` jak podała strona sklepu, zwykle `true`” |
| `App.tsx` 683 linii (658 przed zmianą) — reguła 500 linii łamana już na `main` | dwa duplikaty `searchUsedBikes`/`searchDecathlon` zwinięte w `postOnDemandSearch` (674 linii); pełne wydzielenie API do osobnego modułu = osobne zadanie |
| martwy wrapper `save_used_offers`, nieużywana stała `OLX_SOURCE` w repozytorium searchera | usunięte |

## 6. Weryfikacja lokalna — co się naprawdę okazało

Stack: searcher :8100, backend :8001, frontend :5174 (8000/8080 nadal zajęte przez compose innego worktree na
produkcyjnej Cloud SQL), lokalny Postgres `biker-pg`. Rowery do testów dobrane z bazy: marki Decathlonu **bez** cache
Allegro/Ceneo (karta „Nowe” pusta) — Rockrider ST 100 (id 28), Riverside 500 (34), Triban RC 520 (33), Van Rysel EDR
Easy/Speed/Gravel (633/635/636), GRVL GRX AF (621); Trek Marlin 5 jako obca marka i regresja OLX.

1. **Smoke searchera** (`test_searcher.py`, wtedy TC-1..9): ALL OK — OLX 5 ofert × 4 zdjęcia w 75 s, Decathlon
   `Decathlon / Rockrider ST 100` → 1 oferta 1199 zł w 136 s (CLI zrobiło 23 tury), wiersz bez zdjęć.
2. **Smoke backendu** (`test_search.py` TC-30..35 przez runner z podmienionym portem): odczyty z fixtur 0,3–0,4 s bez
   wiersza cache, nieznany rower 200/404, Trek → `info` w 0,29 s bez searchera, live OLX 80 s i live Decathlon 78 s
   z round-tripem z bazy.
3. **`/manual-tester`**: plan ISTQB, 8 przypadków, dwa stacki (prawdziwy + fałszywy searcher na 8199 dla „0 ofert” i 502).
   Wynik **8/8** w dwóch rundach; jedyna porażka w rundzie 1 to harness — kryterium „brak błędów w konsoli” łapało
   przeglądarkowe `Failed to load resource: 500` z nieskeszowanych endpointów AI (brak kredytów). Po filtrze
   (`NetLog.app_errors`) TC-03 powtórzony na innym rowerze (Van Rysel GRVL GRX AF, 133 s, oferta 5 099 zł). Pozostałe:
   pusta karta → przycisk po 5 s → oferta Riverside 500 (1599 zł) zastępuje przycisk → po ponownym otwarciu z bazy w
   5,1 s; Trek → „Nie znaleziono ofert” w 0,53 s bez runu; drugi rower w trakcie → 503 i przycisk aktywny (pierwszy,
   EDR Speed, skończył pusto — takiego modelu nie ma na decathlon.pl, nic nie skasowano); fake 0 ofert / 502; regresja
   karty „Używane”.
4. **Incydent środowiskowy**: w połowie testów Claude Code ubił wszystkie procesy w tle (searcher, backendy, Vite,
   trwający smoke) z powodu niskiej pamięci — Chrome ≈ 9 GB przy 4,4 GB wolnych z 31,5. Harness zabrania samodzielnego
   restartu, więc poszło pytanie do użytkownika; `docker stop n8n` zwolnił 9 GB, „wznów” i smoke od nowa. Drugie
   potknięcie: `backend/.venv` ma `patchright`, nie `playwright` — skrypty Playwright chodzą na globalnym `python`.
5. Użytkownik zauważył okna Chromium podczas testów — to regresja OLX (TC-32/TC-5) w trybie widocznym
   (`PLAYWRIGHT_HEADLESS` nieustawione lokalnie); Decathlon nie otwiera przeglądarki. Searcher zrestartowany headless.

## 7. Merge z `main` — konflikt w smoke testach

Podczas prac na `main` wylądował PR #100 („Reduce backend smoke tests to one happy path per endpoint”): `test_search.py`
z 1200-linijkowego skryptu „od góry do dołu” stał się 414-linijkowym plikiem z funkcjami `case_*`, `CASES` i flagą
`--ai`. Mój branch dopisał do starej struktury TC-33..35 → konflikt. Rozwiązanie: wersja `main` jako baza, a moje
przypadki przeniesione jako `case_decathlon` (fixtura + nieznany rower) i `case_decathlon_search` (404 → obca marka
bez runu → live `Decathlon / Rockrider ST 100` z round-tripem, `SKIP` bez searchera); stary AI-owy `case_decathlon`
z listy `--ai` usunięty; `_require_searcher()` wydzielone dla obu live'ów. Dokumentacja przepisana z numerów TC na nazwy
przypadków. Ponowny run: 7 passed / 0 failed / 3 skipped (`--ai`). Commity: `3334dc2` (feature), `91c71ee` (zapis
deployu), `db49291` (merge) → PR #99 zmergowany `ff44e8e`; PR #101 przeniósł `TODO_032` i `TODO_ISSUE_010` (z sekcją
„Resolution”) do `backlog/done/`.

## 8. Wdrożenie na GCP

| Krok | Kto | Co |
|---|---|---|
| Zgoda | użytkownik | „Tak, wdrażaj” po lokalnym 8/8 |
| Obrazy + Cloud Run | ja | `scripts/deploy.ps1 -Tag 3334dc2` (tag jawnie, bo niezacommitowany `backend/cache.db` dawałby `-dirty`); cache Dockera nie zadziałał, obraz searchera zbudowany od warstw systemowych; rewizje `biker-searcher-00002-q99`, `biker-backend-00004-2vf`, `biker-frontend-00003-hc8` |
| Sekrety / IAM | nikt | **nic nowego** — ten sam serwis, te same `searcher-api-key`, `claude-code-oauth-token`, `db-password`, ta sama Cloud SQL `biker-pg`, publiczny `run.invoker` już był |
| Weryfikacja końcowa | ja | skrypt `curl` na publicznych URL-ach (9 kroków): frontend 200; searcher `/health` ok; bez klucza 401; Riverside 500 przed — pusto; nieznany rower 404; Trek → `info` natychmiast bez runu; **Riverside 500 → 1 prawdziwa oferta 1599 zł** (run CLI na Cloud Run); potem `/v1/bike/decathlon` czyta ten sam wiersz z Cloud SQL; regresja `/v1/bike/used` Trek Marlin 5 z OLX |

Przy okazji na produkcji widać niezwiązany z tą zmianą błąd ścieżki AI wyszukiwania (`AsyncMessages.create() got an
unexpected keyword argument 'temperature'` → 500 dla roweru spoza bazy) — do osobnego zgłoszenia.

## 9. Architektura po zmianie

```
przeglądarka ──klik „Poproś o dane” (karta Nowe)──► frontend (nginx / Vite)
   │                                                     │ /v1/*
   │  POST /v1/bike/missing  (licznik offers_new)        ▼
   │  POST /v1/bike/decathlon/search ───────────► backend (Cloud Run biker-backend)
   │                                              │ bike_exists? → 404
   │                                              │ is_decathlon_brand? → nie: 200 {offers: [], info} (0 runów)
   │                                              │ single-flight (ścieżka, rower), max 1 w locie, 600 s
   │                                              ▼  POST /v1/search/decathlon  +  X-Searcher-Key
   │                                       searcher (Cloud Run biker-searcher — ten sam co OLX, 1 slot CLI)
   │                                              │ claude -p --json-schema  (subskrypcja), BEZ Playwrighta
   │                                              ▼
   │                                       Cloud SQL biker-pg: bike_offer (source='decathlon.pl', is_new wg sklepu)
   │                                              ▲
   └── automatycznie przy otwarciu roweru: POST /v1/bike/decathlon ── czysty odczyt ──┘
```

Pliki: `searcher/app/decathlon_finder.py` (nowy), `searcher/app/{main,repository,schemas}.py`,
`searcher/app/prompts/bike_offer_decathlon.md` (przeniesiony), `searcher/scripts/test_searcher.py`, `searcher/README.md`;
backend `app/decathlon_brands.py` (nowy), `app/{main,offers_repository,searcher_client,schemas}.py`, `app/DB_MIGRATION.md`,
`scripts/test_search.py`, `scripts/test_e2e_ui_db.py`, `.env.example`, `README.md`; frontend `App.tsx`,
`BikeDetailsView.tsx`, `types.ts`, `README.md`; `CLAUDE.md`, `README.md`, `docker-compose.yml`, `scripts/deploy.ps1`
(tylko komentarze); `docs/testing/TODO_032/` (plan + 11 zrzutów). Usunięte z backendu: `bike_offer_decathlon_finder.py`,
`prompts/bike_offer_decathlon.md`.

## 10. Jak tego używać

```bash
# ręcznie na searcherze (lokalnie: klucz z searcher/.env; na GCP: gcloud secrets versions access latest --secret=searcher-api-key)
curl -X POST https://biker-searcher-919806073640.europe-central2.run.app/v1/search/decathlon \
  -H "Content-Type: application/json" -H "X-Searcher-Key: <sekret>" -d '{"company":"Decathlon","model":"Rockrider ST 100"}'

# przez backend (to, co robi przycisk w karcie „Nowe”)
curl -X POST https://biker-backend-919806073640.europe-central2.run.app/v1/bike/decathlon/search \
  -H "Content-Type: application/json" -d '{"company":"Riverside","model":"Riverside 500"}'
# obca marka → od razu {"offers":[],"info":"Decathlon nie sprzedaje marki Trek — …"}, bez runu

# smoke testy — jedyny płatny run w całym zestawie to case_decathlon_search (SKIP bez searchera)
cd backend && python scripts/test_search.py          # bez --ai: zero wywołań API; 1 run subskrypcji gdy searcher działa
cd searcher && python scripts/test_searcher.py       # darmowe: health, 401/422 na obu trasach

# deploy
.\scripts\deploy.ps1 -Only searcher      # albo bez -Only: searcher → backend → frontend
```

Uwaga do tożsamości roweru: w `bike` ten sam model potrafi występować kilka razy (`Decathlon / Rockrider ST 100`,
`Rockrider / ST 100`…). Wyszukiwanie należy uruchamiać z tożsamością, którą aplikacja już ma — inaczej duplikat
przechwyci jedyny URL produktu (patrz §11).

## 11. Czego nie ma (świadomie) i co dalej

- **K1 — kolizja URL-u produktu**: `bike_offer.url` jest globalnie unikalny, a Decathlon ma jeden URL na model. Przy
  zduplikowanych tożsamościach roweru pierwsza zapisuje ofertę, każda następna płaci run i kończy na „Nie znaleziono
  ofert”. Naprawa = TODO-021 pkt 2 (unikalność `(bike_id, url)` zamiast globalnej, z migracją indeksu w Postgresie).
- Brak TTL/odświeżania zapisanych ofert; brak zdjęć Decathlonu (nie było ich i przed zmianą); brak weryfikacji, czy
  oferta jest nadal dostępna; Allegro/Ceneo nadal w generycznym cache na kluczu API bez kredytów (TODO-021).
- `is_new` pochodzi z modelu — oferta outletowa ląduje w karcie „Używane”; karta „Nowe” nie proponuje wtedy drugiego
  płatnego runu.
- Run Decathlonu bywa długi (41–160 s; CLI robi 8–23 tur `WebFetch`) — timeout CLI 300 s daje zapas, ale to warte
  obserwacji.
- `App.tsx` ma 674 linie — wydzielenie wywołań API do osobnego modułu to osobne zadanie.
- Po PR #102 płatny jest dokładnie jeden test (`case_decathlon_search`); reszta zestawu jest darmowa — świadoma decyzja,
  żeby nie wydawać runów subskrypcji na regresję OLX przy każdym uruchomieniu.

## 12. Lekcje

1. **Drugi raz ten sam schemat idzie o klasę szybciej** — kontrakt, workflow z rozłącznymi plikami i trzy soczewki
   przeglądu dały komplet w jednym przebiegu; jedyne „high” było w teście, nie w kodzie.
2. **Uogólniaj przy drugim przypadku, nie przy pierwszym**: `save_offers(source)`, `_get_stored_offers(source)`,
   `SEARCH_PATHS` i `postOnDemandSearch` powstały dopiero teraz i od razu zamknęły trzy duplikaty.
3. **Tożsamość roweru jest częścią danych testowych** — test, który „tylko dodaje wiersz `bike`”, może ukraść jedyny
   URL produktu rowerowi używanemu w UI. Sprawdzaj, pod jaką tożsamością aplikacja naprawdę pyta.
4. **Harness łapie własne błędy**: przeglądarkowe `Failed to load resource` z endpointów bez kredytów nie są błędem
   testowanej zmiany — filtruj świadomie i zapisz dlaczego, zamiast poluzować kryterium.
5. **Konflikt merge'a może być strukturalny, nie tekstowy** — gdy `main` przebudował plik testów, właściwym ruchem było
   przenieść przypadki do nowej struktury, a nie sklejać dwa światy.
6. **Środowisko też się psuje**: procesy w tle giną przy niskim RAM-ie, a harness zabrania ich wskrzeszać bez zgody —
   trzeba wiedzieć, co zwolnić (`n8n`, karty Chrome) i mieć runner, który powtórzy przerwany smoke od zera.
7. **Koszt testów to decyzja produktowa** — użytkownik wybrał jeden płatny run w całym zestawie; reszta musi być
   darmowa i dalej sensowna (404/401/422 zamiast „nie testujemy”).
