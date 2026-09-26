# Jak wyszukiwanie ofert Allegro przeszło z endpointu backendu do searchera (TODO-033)

Zapis całego procesu — od stanu wyjściowego, przez wywiad, sondy (które zmieniły plan), implementację, testy, aż po
wdrożenie — z datą 2026-09-26. Trzecia powtórka schematu z `docs/OLX_SEARCHER_MIGRATION.md` (TODO-031) i
`docs/DECATHLON_SEARCHER_MIGRATION.md` (TODO-032). Branch `feature/033-searcher-allegro`, zadanie
`backlog/TODO_033_SEARCHER_ALLEGRO_ON_DEMAND.md`, plan i wyniki testów `docs/testing/TODO_033/TEST_PLAN.md`, zadanie w
Notion: „8. Allegro search na serverless i na callu na UI” (Zadania Q4 2026).

## 1. Punkt wyjścia

`POST /v1/bike/allegro` w backendzie (`backend/app/main.py`) był ostatnim endpointem ofert, który przy każdym
nieskeszowanym otwarciu roweru sam wołał model:

1. `bike_offer_finder.py` — jedno wywołanie Anthropic SDK (`claude-haiku-4-5-20251001` + `web_search_20250305`) z promptem
   `prompts/bike_offer_allegro.md` („wejdź na listing, otwórz ofertę, odczytaj cenę i stan”); odpowiedź parsowana
   `extract_json()`; do 3 ofert.
2. `allegro_image_fetcher.py` — Playwright (patchright) z rozgrzewką na `allegro.pl` (żeby DataDome wydał ciasteczko),
   potem regex po `a.allegroimg.com` na stronie oferty. Bez limitu i bez kolejności: w cache siedziały odpowiedzi z 49–257
   „zdjęciami” na ofertę (kafle polecanych rowerów włącznie), a 6 z 11 rowerów miało 0 zdjęć.
3. Wynik do generycznego cache pod **starym** kluczem `/v1/bike/offer` (trasa była przemianowana w PR #103, klucz nie).

Problemy: klucz API od 2026-09-26 ma zero kredytów, więc każde nieskeszowane otwarcie roweru kończyło się 500 na tej
trasie; zadanie 8 w Notion prosiło o „Allegro search na serverless i na callu na UI”. Prośba brzmiała dosłownie:
„Weź za przykład migracje DECATHLON_SEARCHER_MIGRATION.md OLX_SEARCHER_MIGRATION.md i zrób tak samo do v1/bike/allegro”
+ `/interview-me` + `/manual-tester`.

## 2. Wywiad i decyzje (`/interview-me`, 3 pytania)

Hipoteza startowa (pewność ~70 %): DB-only `/v1/bike/allegro` + trzecia trasa w tym samym searcherze + przycisk w UI.
Pytania zadawane pojedynczo, każde ze strzałem:

| Pytanie | Decyzja |
|---|---|
| Który przycisk odpala Allegro? Strzał: karta „Nowe”, Decathlon i Allegro **jeden po drugim** (searcher ma jeden slot) | **Karta „Nowe”, ale oba naraz** („Mają działać się równolegle”) — stąd dwa sloty po obu stronach: backend `SEARCHER_MAX_INFLIGHT=2`, searcher `SEARCHER_MAX_CONCURRENT=2`, Cloud Run `--max-instances 2` przy `--concurrency 1` |
| Zdjęcia dalej Playwrightem (rozgrzewka DataDome + regex)? | **Tak**, „dokładnie to samo, inny transport”; ryzyko blokady DataDome przyjęte świadomie (scrape nie-fatalny, `photos: []`) |
| Co z 11 odpowiedziami w generycznym cache? | **Nie przenosimy** — jednorazowe zrzuty sprzed tygodni, ogłoszenia wygasają, ponowny klik to run subskrypcji |

Restate (wynik / użytkownik / dlaczego teraz / sukces / ograniczenia / poza zakresem) potwierdzone „tak”; „tak” było też
zgodą na start prac. Poza zakresem: Ceneo (UI go nie woła), karta „Używane” (tylko OLX), TTL, żywotność ogłoszeń, K1
(globalna unikalność `url`, TODO-021), Allegro REST API (TODO-008, zablokowane).

## 3. Sondy — i to one zmieniły plan

Tak jak poprzednio: zanim powstała linijka kodu, jeden run `claude -p` przez **niezmieniony** `searcher/app/claude_cli.run_structured`
ze starym promptem backendu i schematem OLX, plus **niezmieniony** fetcher backendu na zwróconym URL-u.

| Sonda | Wynik |
|---|---|
| 1. Stary prompt, Trek Marlin 5 | 1 prawdziwa oferta (2319 zł, używany) — ale w **286 s** z limitu 300 s; Playwright 9,8 s → **0 zdjęć** |
| 2. Stary prompt, Kross Level 3.0, z logiem tur | 49 s, 9 tur, **0 ofert**: *„Allegro.pl blocks automated page fetching (HTTP 403 Forbidden)”* |
| Diagnostyka strony oferty (patchright, headless **i** z oknem) | już strona główna: **403, tytuł „allegro.pl”, markery DataDome / captcha-delivery**; 0 dopasowań regexu w obu trybach |
| Stare cache | 5 z 11 wierszy miało po 49–257 „zdjęć” (kiedyś scrape przechodził), 6 miało 0 |

Wniosek: **allegro.pl odpowiada 403 na każde zautomatyzowane żądanie** — i na `WebFetch` CLI, i na Chromium. Prompt pisany
pod SDK-owy `web_search` (który dostawał treść strony od serwera Anthropic) w CLI nie ma czego czytać: model albo wypala cały
limit na próby fetchowania (sonda 1), albo się poddaje (sonda 2). Decyzja P2 („byte-identyczny prompt”) musiała ustąpić
realiom — powstała wersja pod CLI: **tylko WebSearch**, nigdy `WebFetch` na allegro.pl, tylko URL-e `/oferta/` i
`/produkt/`, cena i stan z tytułu/snippetu wyniku, brakująca cena → `""` zamiast zmyślonej, `is_new` z tekstu (stan
„używany” → false; „nowy”/oferta sklepowa → true), maks. 6 wyszukań.

| Sonda z nowym promptem | Wynik |
|---|---|
| 3a. Kross Level 3.0 | **3 oferty w 67 s** (8 tur), jedna bez widocznej ceny |
| 3b. Trek Marlin 4 | 3 oferty w 75 s (11 tur), **żadna z ceną** w snippetach → dopisany krok „dosukaj z »zł«” |
| 4. Trek Marlin 6 przez **prawdziwy** `find_allegro_offers` (prompt + regex URL + fetcher) | 3 oferty z cenami (2 799–3 458 zł) w 93 s; obie strony ofert **403** → pominięte, `photos: []` |

Zdjęcia zostają więc krokiem nie-fatalnym „na wypadek, gdyby Allegro odpuściło” — dziś dają 0. To udokumentowane
ograniczenie (K2 w planie testów), nie regresja: stary backend też dostawał 0 dla ponad połowy rowerów.

## 4. Kontrakt między modułami (spisany w `backlog/TODO_033_…` przed implementacją)

**Searcher**
- `POST /v1/search/allegro` `{company, model}` + `X-Searcher-Key` → `{offers, info, bike_id, saved}`; 401/422/502/503/500
  jak dwie pozostałe trasy; **wspólny semafor**, teraz `SEARCHER_MAX_CONCURRENT` domyślnie 2 (busy check `locked()`
  działa dla N > 1).
- `app/allegro_finder.py` — `find_allegro_offers()`: schemat OLX, ≤ 3 ofert, URL musi pasować do
  `^https://(www\.)?allegro\.pl/(oferta|produkt)/` (strona listingu/kategorii byłaby zapisana jako „oferta”, a jej kafle
  zeskrobane jako zdjęcia), dedupe, przycięcie do szerokości kolumn, `is_new` z modelu, `city=None`, potem
  `fetch_images_for_offers`.
- `app/allegro_image_fetcher.py` — przeniesiony fetcher z tą samą rozgrzewką i regexem, ale: log statusu strony i pominięcie
  nie-200 (challenge DataDome), **jeden URL na obraz** (`/original/<id>` albo największa rendycja `/s<size>/<id>`), kolejność
  galerii, **≤ 8** na ofertę (zamiast wszystkiego alfabetycznie).
- `app/repository.py` — `save_offers(source='allegro.pl')` bez zmian w kodzie (upsert w obrębie (rower, źródło), pusty
  wynik nic nie kasuje).

**Backend**
- `/v1/bike/allegro` → `offers_repository.get_allegro_offers()` (czysty odczyt, zdjęcia z `bike_offer_photos`); koniec z
  `_ALLEGRO_CACHE_KEY`.
- `POST /v1/bike/allegro/search`: **404** nieznany rower → proxy `searcher_client.search_allegro()`; 503 „Allegro
  searcher is not configured / unavailable / is busy”, 502 z `detail`. `SEARCH_PATHS` z trzema ścieżkami,
  `DEFAULT_MAX_INFLIGHT = 2`, **HTTP 429** od searchera/Cloud Run (obie instancje zajęte) traktowane jak 503 busy.
- Usunięte: `bike_offer_finder.py`, `allegro_image_fetcher.py` (→ searcher), `prompts/bike_offer_allegro.md` (→ searcher,
  przepisany), `prompts/allegro_image_extractor_prompt.md`, skrypty `test_offer.py` / `test_offer_prompt.py` /
  `test_offer_images.py` (wszystkie kręciły się wokół usuniętego kodu; smoke `/v1/bike/allegro` to teraz `case_allegro`).
- `scripts/test_browser_slots.py` importował `olx_image_fetcher`, którego nie ma w backendzie od TODO-031 — `pytest` padał
  przy kolekcji już na `main`; naprawione przy okazji (22 passed).

**Frontend**
- `App.tsx`: `searchAllegro` + `searchNew = Promise.allSettled([searchDecathlon, searchAllegro])` — każde wyszukiwanie
  ustawia swój stan od razu, więc wiersze z dowolnego źródła zastępują przycisk, gdy tylko dotrą. Trzy odczyty ofert z bazy
  zwinięte w `fetchStoredOffers` (plik zmalał z 651 do 644 linii). `BikeDetailsView`: karta „Nowe” proponuje szukanie tylko
  gdy **żadne** źródło nie ma zapisanych wierszy (`hasNewSourceRows` — używane ogłoszenie Allegro siedzi w „Używane”, a
  ponowny klik kosztowałby dwa runy), etykieta „Szukam na Allegro i Decathlon…”.

## 5. Implementacja: workflow z ośmioma agentami

Jeden skrypt `Workflow`: faza *Implement* (searcher / backend / frontend równolegle, rozłączne pliki, bez komend git —
przenosiny plików zwykłymi operacjami na dysku, żeby dwa agenty nie waliły o `index.lock`), faza *Docs* + *Verify*
równolegle (CLAUDE.md/README/deploy/compose oraz importy, `pytest`, `npm run build`, grep pozostałości, identyczność
bajtowa promptu, liczby linii), faza *Review* (trzy soczewki: integracja, bezpieczeństwo i koszty, konwencje i
dokumentacja). 8 agentów, ~18 min, 0 błędów. Pułapka tej rundy: agenci czytali plik zadania **przed** wynikiem sond, więc
prompt przenieśli byte-identycznie — i wszystkie trzy przeglądy zgłosiły to jako *high* wobec zaktualizowanej decyzji 4.
Co przeglądy znalazły i co z tym zrobiłem:

| Znalezisko | Poprawka |
|---|---|
| **high** ×3 — prompt byte-identyczny wbrew decyzji 4 po sondach | prompt pod CLI wgrany po workflow, zweryfikowany sondą 4 przez prawdziwy moduł; zdania „byte-identical” i „DataDome suspected” w trzech README i CLAUDE.md poprawione na potwierdzone 403 i nowe czasy |
| **medium** ×2 — `searchNew` odrzucał tylko gdy **oba** wyszukiwania padły; dla marki spoza Decathlonu (większość rowerów) Decathlon zawsze odpowiada natychmiast pusto, więc 503 „busy” z Allegro (trzecie równoległe wyszukiwanie) kończyło się fałszywym „Nie znaleziono ofert” bez możliwości ponowienia | `searchDecathlon`/`searchAllegro` zwracają, czy przyniosły wiersze; `searchNew` odrzuca, gdy coś padło **i** nic nie przyniosło wierszy (TC-033-04/06/07) |
| low — etykieta przycisku przełączała się na domyślne „Szukam…”, gdy używane ogłoszenie Allegro dotarło w trakcie szukania (bramkowana tym samym warunkiem co `onRequested`) | etykieta stała, bramkowany tylko `onRequested` |
| low — `ALLEGRO_URL_PREFIXES` przepuszczało `allegro.pl/listing?string=…` (prompt sam taki URL budował) → strona wyszukiwania jako „oferta”, kafle jako zdjęcia | regex `/(oferta|produkt)/` w finderze + zasada w prompcie |
| low — `.claude/skills/feature-full-impl` kazał uruchamiać skasowany `test_offer.py`; komentarz i ostrzeżenie w `deploy.ps1` wymieniały tylko OLX; dwa punkty 502 w `backend/README.md` mówiły „non-200/503” mimo mapowania 429 | poprawione |
| low — reguła 500 linii: `test_search.py` 509 → 575, `main.py` 457 → 493, `App.tsx` 651 → 644 | zaakceptowane (przypadki muszą być w tym pliku wg CLAUDE.md); podział `test_search.py` i wydzielenie tras `*_search` do routera = osobne zadanie |
| moje — pusta cena renderowała się jako pusty napis | `OfferRow` pokazuje „cena w ofercie” |

## 6. Weryfikacja lokalna — co się naprawdę okazało

Stack: searcher :8102 (`SEARCHER_MAX_CONCURRENT=2`, headless), backend :8002 (`SEARCHER_MAX_INFLIGHT=2`), frontend :5176
(8000/8001/8100/5174/5175 zajęte przez compose innego worktree i martwe serwery z poprzedniej sesji — nietknięte), lokalny
Postgres `biker-pg`. Rowery do testów z bazy, bez żadnych zapisanych ofert: Trek Marlin 6 (59), Trek Marlin 8 (29), Triban /
Van Rysel EDR Easy (633), Decathlon / Triban RC 520 (33); regresja: Trek Marlin 5 (OLX) i Riverside 500 (Decathlon).

1. **Smoke searchera** (`test_searcher.py` TC-1..8): ALL OK, zero runów — 401/422 na trzech trasach.
2. **Smoke backendu** (`test_search.py` przez `BIKER_API_URL`): 9 passed / 0 failed / 3 skipped — `case_allegro` 0,7 s z
   fixtury (wiersz + zdjęcie, bez wiersza cache), `case_allegro_search` 404 w 0,3 s, jedyny płatny `case_decathlon_search`
   189 s. `pytest` w backendzie: 22 passed (na `main` padał przy kolekcji).
3. **`/manual-tester`**: plan ISTQB, 9 przypadków, dwa stacki — prawdziwy oraz fałszywy searcher na 8199 wybierający
   odpowiedź po nazwie modelu (Empty / Fail / Busy / NoPrice). Wynik **9/9 w dwóch rundach**:
   - TC-01 Trek Marlin 6: przycisk po 5 s → „Szukam na Allegro i Decathlon…” → Decathlon natychmiast pusto (obca marka),
     Allegro 200 po **99,6 s** → 2 wiersze: nowy 3 458 zł w „Nowe”, używany 2 299 zł w „Używane”, licznik `offers_new` 0→1,
     0 zdjęć (403). TC-02: ponowne otwarcie — odczyt z bazy w 2 s, bez wyszukiwania, bez przycisku.
   - TC-03 równoległość: dwa `claude CLI start` **w tej samej sekundzie** (Decathlon + Allegro), żadnej odmowy; runda 1
     (EDR Easy: Decathlon 1 oferta/49 s, Allegro 3 oferty/61 s) padła wyłącznie w harnessie — oracle uznał sprawę za
     skończoną, gdy przycisk zniknął po wierszu Decathlonu, a Allegro jeszcze biegło; runda 2 (Triban RC 520: 1 + 2 oferty
     w 70/76 s, jedna bez ceny → „cena w ofercie” na żywych danych) zielona.
   - TC-04 trzecie wyszukiwanie w trakcie pary (Trek Marlin 8): Allegro **503 w 0,6 s**, Decathlon pusto → przycisk znów
     klikalny — czyli poprawka z przeglądu działa na prawdziwym stacku; TC-06/07 to samo dla 502 i 503 z fałszywego
     searchera; TC-05 „Nie znaleziono ofert” tylko gdy oba puste; TC-08 pusta cena; TC-09 regresja OLX i Decathlonu z bazy.
4. Bez incydentów środowiskowych tym razem — poza tym, że stare serwery deweloperskie z sesji TODO-032 nadal trzymały
   porty (nie ruszałem, wziąłem kolejne).

## 7. Merge i commit

_(uzupełniane)_

## 8. Wdrożenie na GCP

_(dopiero po zgodzie użytkownika)_

## 9. Architektura po zmianie

```
przeglądarka ──klik „Poproś o dane” (karta Nowe)──► frontend (nginx / Vite)
   │                                                     │ /v1/*
   │  POST /v1/bike/missing  (licznik offers_new)        ▼
   │  POST /v1/bike/decathlon/search ──┐        backend (Cloud Run biker-backend)
   │  POST /v1/bike/allegro/search ────┤  RÓWNOLEGLE (Promise.allSettled)
   │                                   │          │ bike_exists? → 404
   │                                   │          │ Decathlon: is_decathlon_brand? → nie: 200 pusto (0 runów)
   │                                   │          │ single-flight (ścieżka, rower), max 2 w locie, 600 s, 429 = busy
   │                                   │          ▼  POST /v1/search/{decathlon,allegro}  +  X-Searcher-Key
   │                                   │   searcher (Cloud Run biker-searcher, --max-instances 2, --concurrency 1;
   │                                   │             lokalnie SEARCHER_MAX_CONCURRENT=2)
   │                                   │          │ claude -p --json-schema (subskrypcja) — Allegro: tylko WebSearch,
   │                                   │          │ allegro.pl odpowiada 403 na każdy fetch
   │                                   │          │ Playwright (Allegro): rozgrzewka + strona oferty → dziś 403 → photos: []
   │                                   │          ▼
   │                                   │   Cloud SQL biker-pg: bike_offer (source='allegro.pl' / 'decathlon.pl') + bike_offer_photos
   │                                   │          ▲
   └── automatycznie przy otwarciu roweru: POST /v1/bike/allegro ── czysty odczyt ──┘
```

Pliki: `searcher/app/allegro_finder.py` (nowy), `searcher/app/allegro_image_fetcher.py` (przeniesiony, przepisany
ekstraktor), `searcher/app/prompts/bike_offer_allegro.md` (przeniesiony, przepisany pod CLI),
`searcher/app/{main,config,schemas,repository}.py`, `searcher/.env.example`, `searcher/scripts/test_searcher.py`,
`searcher/README.md`; backend `app/{main,offers_repository,searcher_client}.py`, `app/DB_MIGRATION.md`,
`scripts/{test_search,test_browser_slots,test_e2e_ui_db}.py`, `.env.example`, `README.md`; frontend `App.tsx`,
`BikeDetailsView.tsx`, `types.ts`, `README.md`; `CLAUDE.md`, `README.md`, `docker-compose.yml`, `scripts/deploy.ps1`,
`.claude/skills/feature-full-impl/SKILL.md`; `docs/testing/TODO_033/` (plan + zrzuty). Usunięte z backendu:
`bike_offer_finder.py`, `allegro_image_fetcher.py`, `prompts/bike_offer_allegro.md`,
`prompts/allegro_image_extractor_prompt.md`, `scripts/test_offer.py`, `scripts/test_offer_prompt.py`,
`scripts/test_offer_images.py`.

## 10. Jak tego używać

```bash
# ręcznie na searcherze (lokalnie: klucz z searcher/.env; na GCP: gcloud secrets versions access latest --secret=searcher-api-key)
curl -X POST https://biker-searcher-919806073640.europe-central2.run.app/v1/search/allegro \
  -H "Content-Type: application/json" -H "X-Searcher-Key: <sekret>" -d '{"company":"Trek","model":"Marlin 6"}'

# przez backend (to, co robi przycisk w karcie „Nowe” — razem z /v1/bike/decathlon/search)
curl -X POST https://biker-backend-919806073640.europe-central2.run.app/v1/bike/allegro/search \
  -H "Content-Type: application/json" -d '{"company":"Trek","model":"Marlin 6"}'
# nieznany rower → 404; trzecie równoległe wyszukiwanie → 503 "Allegro searcher is busy — try again in a moment"

# smoke testy — jedyny płatny run w zestawie to nadal case_decathlon_search
cd backend && python scripts/test_search.py          # case_allegro (fixtura z bazy) + case_allegro_search (404), zero API
cd searcher && python scripts/test_searcher.py       # darmowe: health, 401/422 na trzech trasach

# deploy
.\scripts\deploy.ps1 -Only searcher      # --max-instances 2; albo bez -Only: searcher → backend → frontend
```

Lokalnie do równoległych wyszukiwań: `SEARCHER_MAX_INFLIGHT=2` w `backend/.env` i `SEARCHER_MAX_CONCURRENT=2` w
`searcher/.env` (to nowe wartości domyślne, więc wystarczy nic nie ustawiać).

## 11. Czego nie ma (świadomie) i co dalej

- **Zdjęcia Allegro = 0** dopóki DataDome blokuje Chromium (dziś 403 od strony głównej). Fetcher zostaje jako krok
  nie-fatalny; gdyby Allegro odpuściło, zdjęcia pojawią się bez zmian w kodzie. Alternatywa do rozważenia: oficjalne API
  (TODO-008, wymaga zweryfikowanej aplikacji).
- **Cena może być pusta** (`price: ""` → „cena w ofercie”), gdy żaden snippet wyszukiwarki jej nie pokazuje (Trek Marlin 4:
  3 oferty, 0 cen). Sortowanie po cenie wrzuca takie wiersze na koniec.
- `is_new` pochodzi z tekstu wyniku, nie ze strony — oferta sklepowa bez słowa „nowy” jest zgadywana jako nowa, prywatna
  bez „używany” — z opisu. Zła flaga = zła karta, nie utrata danych.
- K1 — kolizja globalnie unikalnego `url` przy zduplikowanych tożsamościach roweru (TODO-021 pkt 2) — bez zmian.
- Brak TTL/odświeżania; brak weryfikacji żywotności ogłoszeń; Ceneo nadal na generycznym cache i kluczu API bez kredytów.
- Reguła 500 linii: `test_search.py` (575) i `App.tsx` (644) nadal ponad; `main.py` 493 — jeszcze jedna trasa i pęknie.
  Podział smoke testów po grupach endpointów i wydzielenie tras `*_search` do routera to osobne zadanie.
- Cloud Run: `--max-instances 2` podwaja **sufit** kosztu searchera tylko wtedy, gdy oba wyszukiwania biegną naraz.

## 12. Lekcje

1. **Sonda przed kodem po raz trzeci się opłaciła — i po raz pierwszy zmieniła decyzję z wywiadu.** „Byte-identyczny
   prompt” był rozsądny dla OLX i Decathlonu, bo te strony dają się fetchować; Allegro nie. Gdyby workflow ruszył bez sond,
   kod byłby poprawny, a funkcja martwa.
2. **Agenci widzą plik zadania z chwili startu.** Poprawka decyzji wpisana w trakcie workflow trafiła tylko do recenzentów,
   którzy zgłosili rozjazd jako *high* — to zadziałało jak należy, ale kosztowało rundę poprawek. Następnym razem: sondy
   przed uruchomieniem workflow, nie równolegle z nim.
3. **„Odrzucaj tylko gdy oba padły” brzmi rozsądnie i jest błędne**, gdy jedna z dwóch gałęzi zwykle kończy się natychmiast
   pusto. Kryterium musi brzmieć „coś padło i nic nie przyniosło wierszy”. Trzy przeglądy o różnych soczewkach złapały to
   niezależnie.
4. **Fałszywy searcher wybierany po nazwie modelu** (Empty / Fail / Busy / NoPrice) daje cztery ścieżki błędów w jednym
   stacku bez ani jednego płatnego runu i bez dotykania kodu produkcyjnego.
5. **Zewnętrzny serwis, który blokuje boty, nie jest błędem implementacji** — ale trzeba to udowodnić (status, tytuł,
   markery DataDome, oba tryby przeglądarki) i zapisać jako ograniczenie, zamiast walczyć o zdjęcia kolejnymi sztuczkami.
