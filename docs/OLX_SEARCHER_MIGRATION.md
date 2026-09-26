# Jak wyszukiwanie ofert OLX przeszło z endpointu backendu do serverlessowego searchera (TODO-031)

Zapis całego procesu — od stanu wyjściowego, przez decyzje, implementację, testy, aż po wdrożenie na Cloud Run —
z datą 2026-09-25/26. Branch `feature/031-searcher-olx`, PR [#97](https://github.com/Kamil-IT/biker/pull/97),
zadanie `backlog/done/DONE_031_SEARCHER_OLX_ON_DEMAND.md`, plan i wyniki testów `docs/testing/TODO_031/TEST_PLAN.md`.

## 1. Punkt wyjścia

`POST /v1/bike/used` w backendzie (`backend/app/main.py`) robił wszystko sam, przy każdym otwarciu widoku szczegółów
roweru, o ile odpowiedzi nie było w generycznym cache (`endpoint_req_to_body_cache`):

1. `bike_used_finder.py` — jedno wywołanie Anthropic SDK (`claude-haiku-4-5-20251001` + narzędzie `web_search_20250305`)
   z promptem `prompts/bike_offer_olx.md`; odpowiedź parsowana `extract_json()` (model często narrował przed JSON-em);
   do 5 ogłoszeń, kaskada exact → rodzina modelu → marka.
2. `olx_image_fetcher.py` — Playwright (patchright) wchodził na każde ogłoszenie i regexem wyciągał do 4 adresów
   `*.apollo.olxcdn.com`.
3. Wynik trafiał do generycznego cache tylko gdy lista ofert była niepusta.

Problemy, które uruchomiły zmianę (Notion, zadanie 18):
- każde nieskeszowane otwarcie roweru paliło tokeny API — a klucz API skończył kredyty (`credit balance is too low`);
- wyszukiwanie miało ruszać **tylko na prośbę użytkownika** albo z procesu w tle, nie automatycznie;
- miało korzystać z **subskrypcji Claude Code** (token z tej sesji), nie z klucza API;
- wynik miał być **naprawdę zapisany w bazie**, a użytkownik miał dostać prawdziwą ofertę po zakończeniu.

## 2. Wywiad i decyzje (`/interview-me`, 3 pytania)

| Pytanie | Decyzja |
|---|---|
| Co ma robić CLI w środku — to samo co endpoint, czy dodatkowo weryfikować ogłoszenia? | **Dokładnie to samo** (prompt → JSON → Playwright po zdjęcia); żadnej weryfikacji „czy ogłoszenie żyje” |
| `/v1/bike/used` ma robić fallback do searchera automatycznie? | Nie — to nic by nie zmieniło w zużyciu tokenów. `/v1/bike/used` = **czysty odczyt z bazy**; searcher rusza **dopiero po kliknięciu „Poproś o dane”** w karcie „Używane” (licznik `bike_missing_request` rośnie jak dotąd) |
| Auth | Jeden wspólny sekret w nagłówku `X-Searcher-Key`, env po obu stronach — tak, żeby `curl` z laptopa działał |
| Kolejność | implementacja → `/manual-tester` lokalnie na lokalnym Postgresie → **pytanie o zgodę** na deploy i o bazę na GCP → Cloud Run |

Decyzja projektowa podjęta samodzielnie: trigger searchera to **nowy** endpoint backendu `POST /v1/bike/used/search`
(proxy), a `/v1/bike/missing` zostaje nietknięty — żeby endpoint licznika nie stał się nagle wywołaniem trwającym minuty.

## 3. Sonda: czy `claude -p` w ogóle to udźwignie

Zanim powstała linijka kodu, jeden ręczny test z tym samym promptem:

```
claude -p "Find current used bike offers on OLX for: Trek Marlin 5" \
  --system-prompt "<bike_offer_olx.md>" --output-format json --json-schema '<schemat {info, offers[]}>' \
  --tools WebSearch,WebFetch --allowedTools WebSearch,WebFetch --permission-prompts none \
  --strict-mcp-config --setting-sources "" --no-session-persistence \
  --exclude-dynamic-system-prompt-sections --model claude-haiku-4-5-20251001 < /dev/null
```

Wynik: 34 s, 5 prawdziwych ogłoszeń (wszystkie URL-e odpowiadały 200), `structured_output` już zwalidowany schematem —
czyli **koniec z parsowaniem prozy**. Kluczowe ustalenia z sondy:
- `ANTHROPIC_API_KEY` trzeba **usunąć ze środowiska dziecka**, inaczej CLI może zbilować API zamiast subskrypcji;
- `stdin=DEVNULL`, bo CLI czeka 3 s na wejście z potoku;
- `--setting-sources ""` i `--strict-mcp-config` odcinają hooki, pluginy, CLAUDE.md i serwery MCP z maszyny dewelopera;
- na serwerze logowanie zastępuje `CLAUDE_CODE_OAUTH_TOKEN` z `claude setup-token`.

## 4. Kontrakt między modułami (spisany przed implementacją)

**Searcher** (`searcher/`, FastAPI, port 8100)
- `POST /v1/search/olx` `{company, model}` + `X-Searcher-Key` → `{offers, info, bike_id, saved}`; 401 bez/ze złym
  kluczem (fail closed, gdy `SEARCHER_API_KEY` nieustawiony), 422 dla pustych/za długich pól, 502 gdy CLI padnie,
  503 „searcher busy”, 500 gdy zapis do bazy padnie. `GET /health` otwarty.
- Zapis do **istniejących, dotąd nieużywanych** tabel `bike_offer` + `bike_offer_photos` (FK do `bike`, `source='olx.pl'`,
  zdjęcia jako wiersze z `display_order`). Rower szukany normalizacją w Pythonie (`strip().lower()`, nigdy SQL `lower()`),
  tworzony gdy go nie ma (bezpośredni `curl`). Semantyka *replace*: `INSERT … ON CONFLICT (url) DO UPDATE`, wiersze tego
  roweru spoza nowego zbioru kasowane.
- `DATABASE_URL` wymagany (bez fallbacku do SQLite — inaczej dane cicho lądowałyby w pliku, którego backend nie czyta).

**Backend**
- `POST /v1/bike/used` → `offers_repository.get_used_offers()` — tylko baza, `{offers, info: ""}`, pusta lista gdy nic nie ma.
- `POST /v1/bike/used/search` → `searcher_client.search_olx()` (httpx, `SEARCHER_URL`, `SEARCHER_TIMEOUT` 600 s) →
  ta sama odpowiedź `{offers, info}`; 503 brak konfiguracji/niedostępny, 502 z `detail` searchera. Nigdy nie keszowany.
- `bike_used_finder.py`, `olx_image_fetcher.py`, `prompts/bike_offer_olx.md` **przeniesione** (usunięte z backendu).

**Frontend**
- `RequestDataButton` dostaje `onRequested` + `pendingLabel`; w karcie „Używane” klik → `/v1/bike/missing` **i**
  `/v1/bike/used/search`; „Szukam na OLX…” → wiersze zastępują przycisk / „Nie znaleziono ofert” / po błędzie znów klikalny.
- `App.tsx` `searchUsedBikes` nie przełącza `usedBikeState` na `loading` (inaczej restartowałby 5-sekundowy skeleton).

## 5. Implementacja: trzech agentów równolegle + dwie rundy przeglądu

Implementację rozdzieliłem na trzy równoległe zadania z rozłącznymi plikami (searcher / backend / frontend) i wspólnym
kontraktem z §4, a po nich trzy niezależne przeglądy: integracja, bezpieczeństwo/odporność, konwencje/dokumentacja.
Pierwsza runda ruszyła bez searchera (literówka `${PORT}` w szablonie skryptu workflow wywaliła tego agenta), więc
przeglądy najpierw zgłosiły „searchera nie ma”; po naprawie skryptu i wznowieniu workflow (backend/frontend z cache,
searcher na żywo) druga runda przeglądów oceniła komplet. Co przeglądy znalazły i co z tym zrobiłem:

| Znalezisko | Poprawka |
|---|---|
| Anonimowy `POST /v1/bike/used/search` z dowolnym `company/model` tworzyłby wiersze `bike` (searcher robi get-or-create) i palił runy subskrypcji | backend sprawdza `bike_exists()` **przed** wywołaniem searchera → **404** |
| `url` w `bike_offer` jest globalnie unikalny, a kaskada promptu zwraca ogłoszenia z rodziny modelu → upsert „przepinał” ogłoszenie między rowerami (Marlin 4 ↔ Marlin 5 kradłyby sobie wiersz) | `DO UPDATE … WHERE bike_id = ten rower`; ogłoszenie należące do innego roweru zostaje tam, nie jest raportowane jako zapisane |
| Pusty wynik (np. czkawka OLX) kasował wszystkie zapisane wiersze roweru | przy 0 ofertach **nic nie kasujemy** |
| Backend przepuszczał 2 wyszukiwania, searcher kolejkował za semaforem 1 → drugie przeżywało timeout backendu i kończyło drugim płatnym runem | searcher odpowiada **503 „busy” natychmiast**, backend `SEARCHER_MAX_INFLIGHT=1`, single-flight na ten sam rower, nginx 660 s (margines nad 600 s backendu), Playwright 20 s na ogłoszenie zamiast 60 s |
| Wynik wyszukiwania startowanego na rowerze A mógł nadpisać kartę roweru B otwartego w międzyczasie | `selectedBikeRef` w `App.tsx` odrzuca spóźniony wynik |
| Dziecko `claude` dziedziczyło `SEARCHER_API_KEY`, `DATABASE_URL`, `PGPASSWORD` | usuwane ze środowiska dziecka |
| Pola z modelu (`price`, `city`, `url`) mogły przekroczyć szerokości kolumn → Postgres 500 po opłaconym runie | przycięcie do szerokości kolumn, za długi URL pomijany, `photos` zawsze puste do czasu scrape’u |
| Nieprzypięta wersja CLI w obrazie, a argv zależy od konkretnych flag | `ARG CLAUDE_CODE_VERSION=2.1.283`, `DISABLE_AUTOUPDATER=1` |
| Backend i searcher robiły `create_all()` naraz na świeżej bazie (wyścig) | searcher tylko **sprawdza**, czy tabele są (`SEARCHER_CREATE_TABLES=true` jako furtka); compose: `depends_on: backend` + `restart: on-failure` |
| `detail` z 503 relacjonował surowy wyjątek httpx (mógłby ujawnić wewnętrzny URL) | stałe komunikaty, wyjątek tylko w logu |
| `repository.py` rósł dalej ponad 500 linii | odczyt ofert w nowym `backend/app/offers_repository.py` |
| Brak długości pól w `UsedBikeRequest` | `max_length=255` (szerokość `bike.brand/model`) |

## 6. Weryfikacja lokalna — co się naprawdę okazało

Stack: searcher :8100, backend :8001, frontend :5174 (8000/8080 zajmował compose z innego worktree, podpięty pod
produkcyjną Cloud SQL — celowo nietknięty), lokalny Postgres `biker-pg`.

1. **Smoke test searchera** (`searcher/scripts/test_searcher.py`): health, 401×2, 422, prawdziwe wyszukiwanie — 5 ofert
   w 85 s, wiersze w bazie. ALL OK.
2. **Smoke testy backendu** (`test_search.py`): pełny plik **nie mógł przejść** — sekcja Ceneo dostała 500, bo klucz API
   Anthropic ma zero kredytów; każdy nieskeszowany endpoint AI backendu tak odpowiada. Sekcja TODO-031 (TC-30/31/32)
   uruchomiona osobno: odczyt z fixturą, nieznany rower, 404, live search przez proxy (91 s) + round-trip z bazy — OK.
3. **Zdjęcia były puste** mimo 200 ze stron ogłoszeń. Sonda Playwrightem na jednym ogłoszeniu: OLX podaje linki jako
   `https://ireland.apollo.olxcdn.com:443/v1/files/…` — stary regex wymagał `/` zaraz po `.com`, więc **nigdy** ich nie
   łapał (ten sam kod w starym backendzie też by nic nie wyciągnął). Nowy ekstraktor: opcjonalny port, jedno zdjęcie na
   plik (największa rendycja) w kolejności galerii. Po restarcie: 5 ofert × 4 zdjęcia.
4. **`/manual-tester`**: plan ISTQB (7 przypadków, traceability R1–R8 + trzy „extra” X1–X3), Playwright headless, dwa
   stacki — prawdziwy i drugi z **fałszywym searcherem** (`http.server` na 8199), bo prawdziwego CLI nie da się zmusić
   do „0 ofert” ani do 502 na żądanie. Trzy rundy; każda porażka w rundach 1–2 była błędem *skryptu testowego*
   (locator łapał strzałki galerii `‹ ›`, karta „Używane” zawiera też używane oferty z Allegro, `time.sleep` nie pompuje
   zdarzeń Playwrighta, `Trek FX 3 Disc` ma używaną ofertę Allegro więc jego karta nigdy nie jest pusta…), nie aplikacji.
   **Finał 7/7**: wiersze z bazy, skeleton → przycisk po 5 s, klik → „Szukam na OLX…” → po ~3 min 5 ogłoszeń ze zdjęciami,
   drugi rower w trakcie → 503 i przycisk znów aktywny, „Nie znaleziono ofert”, 502 → klikalny, regresja karty „Nowe”.
5. `docker compose build searcher` — obraz 2.7 GB, w kontenerze `claude --version` = 2.1.283, użytkownik `searcher`,
   aplikacja importuje się.

## 7. Merge z `main` i commit

W międzyczasie na `main` wylądowały TODO-030 (deploy na Cloud Run, compose z `cloudsql-proxy`, `scripts/deploy.ps1`,
`nginx.conf.template`) i limit równoległych przeglądarek (`BROWSER_SLOTS`). Konflikty: `docker-compose.yml` (searcher
dostał ten sam montaż pgpass i proxy co backend), `nginx.conf` skasowany na main → 660 s przeniesione do szablonu,
`browser_config.py` z main skopiowany do searchera (git sam zaaplikował `BROWSER_SLOTS` do przeniesionego fetchera),
dokumentacja scalona ręcznie. `scripts/deploy.ps1` dostał `-Only searcher` i automatyczne wpięcie `SEARCHER_URL` +
sekretu do backendu. Commity: `45bfddb` (feature), `fb97c04` (merge), `854b5e5` (ignorowany `backend/claude.token`),
`f1d98e8`, `d1b5395`; niezwiązane lokalne zmiany (`backend/cache.db`) zostały poza commitami.

## 8. Wdrożenie na GCP

| Krok | Kto | Co |
|---|---|---|
| Obraz | ja | `docker build` + push `europe-central2-docker.pkg.dev/biker-engine-prod/biker/searcher:f9f7c6f` |
| Sekrety | użytkownik (zapis do Secret Managera jest zablokowany dla auto mode) | `claude setup-token` → plik `backend/claude.token` (gitignored, nigdy nie czytany) → sekret `claude-code-oauth-token`; losowy `searcher-api-key` (`secrets.token_hex(24)`); `secretAccessor` dla `biker-run` na obu |
| Cloud Run | ja | `gcloud run deploy biker-searcher … --add-cloudsql-instances biker-pg --set-env-vars DATABASE_URL=…/cloudsql/…,PLAYWRIGHT_HEADLESS=true --set-secrets PGPASSWORD,SEARCHER_API_KEY,CLAUDE_CODE_OAUTH_TOKEN --port 8100 --cpu 2 --memory 2Gi --concurrency 1 --timeout 900 --min-instances 0 --max-instances 1 --cpu-boost` |
| Pierwszy test | ja | z tokenem tożsamości (usługa jeszcze zamknięta): Trek Marlin 5 → 5 ofert × 4 zdjęcia w 89 s, zapisane w Cloud SQL |
| Backend + frontend | ja | `scripts/deploy.ps1 -Only backend/-Only frontend -Tag 854b5e5` — backend dostał `SEARCHER_URL` i sekret |
| Dostęp publiczny | użytkownik | `roles/run.invoker` dla `allUsers` na `biker-searcher` (endpoint chroni wspólny sekret) |
| Weryfikacja końcowa | ja | anonimowe `/health` 200; bez klucza 401; nieznany rower 404; Romet Aspre: przed — pusto, `/v1/bike/used/search` → 5 ogłoszeń ze zdjęciami w 78 s, potem `/v1/bike/used` czyta te same wiersze z Cloud SQL |

Baza na GCP: **ta sama Cloud SQL `biker-pg` co backend** — jedyny wariant, w którym `/v1/bike/used` widzi to, co zapisał
searcher (oba czytają/piszą `bike_offer` w jednej bazie).

## 9. Architektura po zmianie

```
przeglądarka ──klik „Poproś o dane” (karta Używane)──► frontend (nginx / Vite)
   │                                                        │ /v1/*
   │  POST /v1/bike/missing  (licznik, jak dotąd)           ▼
   │  POST /v1/bike/used/search ─────────────────► backend (Cloud Run biker-backend)
   │                                                 │ bike_exists? → 404
   │                                                 │ single-flight, max 1 w locie, 600 s
   │                                                 ▼  POST /v1/search/olx  +  X-Searcher-Key
   │                                          searcher (Cloud Run biker-searcher, scale-to-zero, concurrency 1)
   │                                                 │ claude -p --json-schema  (CLAUDE_CODE_OAUTH_TOKEN, subskrypcja)
   │                                                 │ Playwright → ≤4 zdjęć / ogłoszenie (olxcdn.com:443 → :443 obcięte)
   │                                                 ▼
   │                                          Cloud SQL biker-pg: bike_offer + bike_offer_photos (source='olx.pl')
   │                                                 ▲
   └── automatycznie przy otwarciu roweru: POST /v1/bike/used ── czysty odczyt ───┘
```

Pliki: `searcher/app/{main,config,claude_cli,olx_finder,olx_image_fetcher,browser_config,models,repository,schemas}.py`,
`searcher/app/prompts/bike_offer_olx.md`, `searcher/{Dockerfile,requirements.txt,.env.example,README.md}`,
`searcher/scripts/test_searcher.py`; backend `app/offers_repository.py`, `app/searcher_client.py`, zmiany w `main.py`,
`schemas.py`, `repository.py`; frontend `RequestDataButton.tsx`, `BikeDetailsView.tsx`, `App.tsx`; `docker-compose.yml`,
`scripts/deploy.ps1`; dokumentacja `CLAUDE.md`, `README.md`, `backend/README.md`, `frontend/README.md`,
`backend/app/DB_MIGRATION.md`.

## 10. Jak tego używać

```bash
# ręcznie (lokalnie: klucz z searcher/.env; na GCP: gcloud secrets versions access latest --secret=searcher-api-key)
curl -X POST https://biker-searcher-919806073640.europe-central2.run.app/v1/search/olx \
  -H "Content-Type: application/json" -H "X-Searcher-Key: <sekret>" -d '{"company":"Trek","model":"Marlin 5"}'

# lokalnie
cd searcher && ..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8100
# backend/.env: SEARCHER_URL=http://localhost:8100, SEARCHER_API_KEY=<to samo co w searcher/.env>

# deploy
.\scripts\deploy.ps1 -Only searcher      # albo bez -Only: searcher → backend → frontend
```

## 11. Czego nie ma (świadomie) i co dalej

- Brak TTL/odświeżania zapisanych ofert: dopóki wiersze są, przycisk się nie pokazuje, więc nic nie uruchomi ponownego
  wyszukiwania. Zaplanować „odśwież” albo TTL, gdy będzie potrzebne.
- Brak weryfikacji, czy ogłoszenie jest nadal aktywne (zgodnie z decyzją z wywiadu).
- Brak schedulera — „proces w tle” to po prostu publiczny endpoint searchera, w który może uderzyć cron/curl.
- Allegro/Ceneo/Decathlon nadal żyją w generycznym cache, nie w `bike_offer` (TODO-021 pozostaje otwarte).
- `brand`/`model` na ofercie z bazy pochodzą z wiersza `bike`, nie z tytułu ogłoszenia (`bike_offer` nie ma kolumny tytułu).
- Rate limit per IP na endpointach AI (TODO-030 krok 2) objąłby też `/v1/bike/used/search`.
- Klucz API Anthropic nadal bez kredytów — reszta backendu na cache-miss zwraca 500; searcher tego nie dotyczy.
- Commit `f1d98e8` (ładniejszy `detail` przy nie-JSON-owym błędzie searchera) trafi na prod przy deployu po merge.

## 12. Lekcje

1. **Sonda przed kodem** — jedno wywołanie `claude -p` z produkcyjnym promptem od razu pokazało, że `--json-schema`
   eliminuje całą warstwę parsowania prozy i że trzeba wyciąć `ANTHROPIC_API_KEY` ze środowiska dziecka.
2. **Kontrakt spisany przed fan-outem** pozwolił trzem agentom pisać równolegle bez uzgadniania kształtów w locie; przeglądy
   z różnymi „soczewkami” złapały realne wady (przepinanie ogłoszeń, mintowanie rowerów, kolejkowanie za timeoutem),
   których jednoosobowa implementacja by nie zauważyła.
3. **Testy manualne wykrywają błędy testów** — trzy rundy, sześć poprawek w skryptach, zero w aplikacji; warto rozróżniać
   jedno od drugiego w raporcie zamiast „naprawiać” aplikację pod źle napisany test.
4. **Zewnętrzne serwisy dryfują** — `olxcdn.com:443` unieważnił regex, który „kiedyś działał”; logowanie statusu strony
   i liczby trafień od razu wskazałoby przyczynę.
5. **Granica auto mode**: zapis sekretów i publiczny IAM idą do użytkownika jako gotowe komendy `!` — cała reszta
   (obrazy, `gcloud run deploy`, weryfikacja) może iść automatycznie.
