# Jak wyszukiwanie zdjęć rowerów przeszło z endpointu backendu do searchera (TODO-035)

Zapis zmiany z datą 2026-09-29: co i dlaczego przeniesiono, jak wygląda przepływ przed i po, trzy trasy, zmiana w bazie i
migracja, decyzje z wywiadu, różnice względem starego scrapera, testy, znane ograniczenia i lista rzeczy do zrobienia przy
wdrożeniu. Czwarta powtórka schematu z `docs/OLX_SEARCHER_MIGRATION.md` (TODO-031),
`docs/DECATHLON_SEARCHER_MIGRATION.md` (TODO-032) i `docs/ALLEGRO_SEARCHER_MIGRATION.md` (TODO-033). Branch
`feature/photos-searcher`, zadanie `backlog/done/DONE_035_PHOTOS_SEARCHER.md`. PR #115 zmergowany i wdrożony na GCP 2026-09-29 — patrz § 9.

## 1. Punkt wyjścia

Zdjęcia roweru robił `POST /v1/bike/details` w backendzie. Przy każdym nieskeszowanym otwarciu roweru trzy wywołania szły
równolegle (`asyncio.gather`), a trzecie z nich to `backend/app/bike_photos_finder.py`:

1. jedno wywołanie Anthropic SDK (`claude-haiku-4-5-20251001` + `web_search_20250305`, prompt `prompts/bike_photos.md`),
   które miało znaleźć oficjalną stronę produktu na witrynie producenta; odpowiedź parsowana jako „pierwsza linia
   zaczynająca się od `http`”;
2. Playwright (patchright) otwierał tę stronę raz i wyciągał regexem do 8 adresów `<img>` (`_IMG_SRC` / `_SKIP`);
3. wynik wracał w polu `photos` odpowiedzi szczegółów i lądował w `bike_detail_photos` przez `save_bike_details`.

Problemy: klucz API Anthropic od 2026-09-26 nie ma kredytów, więc każde nieskeszowane otwarcie roweru kończyło się błędem;
zdjęcia były sprzężone ze szczegółami (zapis szczegółów kasował i wstawiał zdjęcia od nowa, a zdjęcia nie mogły istnieć bez
wiersza `bike_detail`); szczegóły miały TTL 30 dni, po którym całość, razem ze zdjęciami, była liczona od nowa. Cel
zadania: zdjęcia mają działać jak oferty Allegro — szybki odczyt z bazy przy otwarciu roweru, a płatne wyszukiwanie
(`claude -p` na subskrypcji + Playwright) dopiero po kliknięciu **Poproś o dane**.

## 2. Decyzje z wywiadu

| Kwestia | Decyzja |
|---|---|
| Gdzie ma żyć wyszukiwanie? | **Nowa trasa w istniejącym serwisie `biker-searcher`**, nie osobny serwis Cloud Run (ten sam obraz, te same sekrety, brak nowego IAM) |
| Limit równoległych wyszukiwań | **2 → 10** wszędzie: `SEARCHER_MAX_CONCURRENT` w searcherze, `SEARCHER_MAX_INFLIGHT` / `DEFAULT_MAX_INFLIGHT` w backendzie, Cloud Run `--max-instances 10` (dalej `--concurrency 1`) |
| Gdzie trzymać zdjęcia? | W tej samej tabeli `bike_detail_photos`, **przekluczowanej na `bike_id`** (zamiast `bike_detail_id`) |
| TTL | **Zdjęcia nie mają TTL; TTL szczegółów (30 dni) usunięty z kodu** — zapisane szczegóły są zwracane bez względu na wiek. TTL wyszukiwań bez zmian |
| Nadpisywanie | **Żadne zdjęcie nie jest nigdy usuwane ani zastępowane.** Searcher zapisuje zdjęcia tylko dla roweru, który nie ma żadnych; jeśli ma — zwraca zapisane bez uruchamiania wyszukiwania |
| Scraper | Przeniesiony **1:1** z `bike_photos_finder.py` (te same regexy, maks. 8, 4 s czekania, ten sam UA), **bez** ulepszeń z `docs/bikes/pipeline/photo_extract.py` |
| Zdjęcia sprzętu (equipment) | Poza zakresem — `/v1/equipment/*` i `equipment_photos_finder.py` bez zmian, backend zachowuje Playwrighta i `BROWSER_SLOTS` |

Poza zakresem: osobny serwis Cloud Run, zdjęcia w wynikach wyszukiwania (`TODO_ISSUE_008`), jakikolwiek deploy, jakikolwiek
zapis do produkcyjnej bazy.

## 3. Przepływ przed i po

**Przed**

```
otwarcie roweru ──► POST /v1/bike/details ──► gather(komponenty, opis, zdjęcia)   ← zdjęcia: SDK web_search + Playwright w backendzie
                                              └─► zapis: bike + bike_detail (+ zdjęcia wg bike_detail_id), TTL 30 dni
```

**Po**

```
otwarcie roweru ──► POST /v1/bike/details        ──► gather(komponenty, opis)          ← bez zdjęć, bez TTL
               └──► POST /v1/bike/photos         ──► czysty odczyt bike_detail_photos  ← bez AI, bez cache, bez TTL
klik „Poproś o dane” w galerii
               ├──► POST /v1/bike/missing        (licznik missing_type = photos)
               └──► POST /v1/bike/photos/search ──► 404 nieznany rower → proxy (X-Searcher-Key)
                                                     └─► searcher POST /v1/search/photos
                                                          1. odczyt bike_detail_photos — są? zwróć, KONIEC (bez CLI, bez przeglądarki, bez busy)
                                                          2. claude -p (subskrypcja): {url} strony produktu producenta
                                                          3. walidacja URL (publiczny http/https)
                                                          4. Playwright otwiera stronę raz, ≤ 8 adresów <img>
                                                          5. INSERT tylko gdy rower nie ma zdjęć (SELECT … FOR UPDATE na wierszu roweru)
```

## 4. Trzy trasy

| Warstwa | Trasa | Zachowanie |
|---|---|---|
| backend | `POST /v1/bike/photos` `{company, model}` → `{photos: [url, …]}` | Czysty odczyt (`photos_repository.get_bike_photos`, `ORDER BY display_order, id`). Nieznany rower / brak zdjęć / błąd bazy → **200** `{photos: []}`. Walidacja: niepuste, ≤ 255 znaków (422) |
| backend | `POST /v1/bike/photos/search` → `{photos: […]}` | **404** „Bike not found” (`bike_exists`) **przed** wywołaniem searchera; potem proxy. **503** „Photos searcher is not configured / unavailable / is busy — try again in a moment”, **502** z `detail` searchera. Nigdy nie cache'owane; identyczne równoległe żądania dzielą jedno wyszukiwanie (single-flight) |
| searcher | `POST /v1/search/photos` + `X-Searcher-Key` → `{photos, bike_id, saved}` | 401/422/500/502/503 jak trasy ofert, te same sloty `SEARCHER_MAX_CONCURRENT`. Zapisane zdjęcia są zwracane **przed** sprawdzeniem zajętości; identyczne żądanie w trakcie wyszukiwania dołącza do niego (jedno płatne uruchomienie) |

`BikeDetailsResponse` **traci** pole `photos`; `/v1/bike/details` woła już tylko dwa wyszukiwania, a `/v1/bike/details-cache`
nie zwraca zdjęć. Z backendu zniknęły `bike_photos_finder.py` i `prompts/bike_photos.md` (przeniesione do searchera:
`searcher/app/photos_finder.py`, `searcher/app/prompts/bike_photos.md`).

Frontend: przy otwarciu roweru czwarty odczyt z bazy (`fetchStoredOffers` → `/v1/bike/photos`); galeria renderuje zwrócone
adresy w zwróconej kolejności. Pusta galeria po 5 s pokazuje `RequestDataButton` (`MissingType.photos`,
`pendingLabel="Szukam zdjęć…"`, nowy prop `emptyLabel="Nie znaleziono zdjęć"`); zwrócone zdjęcia zastępują przycisk;
wyjątek → przycisk znów klikalny; `selectedBikeRef` odrzuca spóźnione wyniki. Widok sprzętu bez zmian.

## 5. Zmiana w bazie i migracja

`bike_detail_photos` zachowuje nazwę, ale kolumna `bike_detail_id` jest **zastąpiona** przez
`bike_id INTEGER NOT NULL REFERENCES bike(id) ON DELETE CASCADE` (indeks `ix_bike_detail_photos_bike_id`). Kolumny po
zmianie: `id, bike_id, url, display_order`. Zdjęcia nie potrzebują już wiersza `bike_detail`; `save_bike_details` ani ich nie
zapisuje, ani nie kasuje, a wiersz `bike_detail` **aktualizuje w miejscu** (stałe `id`, komponenty kasowane i wstawiane od nowa) zamiast go
usuwać i tworzyć na nowo. Powód: na niezmigrowanej bazie stary klucz obcy `bike_detail_photos.bike_detail_id → bike_detail ON DELETE
CASCADE` jeszcze istnieje, a stary kod usuwał wiersz szczegółów przy każdym ponownym zapisie — kaskada skasowałaby zdjęcia. `TTL_DETAILS` usunięty z `backend/app/repository.py`.

Skrypt `backend/scripts/migrate_photos_bike_id.py` (SQLite i PostgreSQL):

- SQLite nie potrafi usunąć kolumny z FK w miejscu, więc tabela jest przebudowywana (`CREATE …_new` → `INSERT … SELECT`
  przez `bike_detail` → `DROP` → `RENAME` → indeks); PostgreSQL jest zmieniany w miejscu (`ADD COLUMN bike_id` → `UPDATE …
  FROM bike_detail` → `NOT NULL` + FK + indeks → `DROP COLUMN bike_detail_id`). Identyfikatory i sekwencja zostają.
- Jedna transakcja; przed commitem weryfikacja wiersz po wierszu (id, url, `display_order`, właściwy rower) — każda rozbieżność
  albo błąd cofa całość. Kod wyjścia 1 przy porażce.
- Wiersze, których wiersz `bike_detail` (lub jego rower) nie istnieje, nie mają dokąd trafić: są wypisane, **kopiowane do tabeli
  `bike_detail_photos_orphans`** (`id, bike_detail_id, bike_id, url, display_order`) w tej samej transakcji (kopia jest weryfikowana)
  i pomijane w zmigrowanej tabeli — nigdy po cichu porzucone. Wypisuje liczby wierszy i rowerów przed i po.
- PostgreSQL: `LOCK TABLE … SHARE ROW EXCLUSIVE` na tabelach zdjęć i szczegółów, żeby równoległe zapisy nie zaburzyły weryfikacji.
- Idempotentny (już zmigrowana tabela jest sprawdzana — `NOT NULL`, FK do `bike` z `ON DELETE CASCADE`, indeks — i naprawiany jest tylko brakujący element; brakującą tabelę tworzy `init_db()` od razu w nowym schemacie), `--dry-run`,
  `--db <plik sqlite>`, `--url <url sqlalchemy>`, domyślnie `$DATABASE_URL`, inaczej `backend/cache.db`. Importowalny:
  `migrate(url_or_path=None, dry_run=False, verbose=True) -> dict`.
- **Trzeba go uruchomić raz na każdej istniejącej bazie — i to PRZED tym, zanim nowy backend lub searcher zacznie z nią pracować (kolejność wdrożenia to sprawa bezpieczeństwa danych, zob. § 9).** Bez tego: `POST /v1/bike/photos` zwraca `{photos: []}` i loguje
  ERROR ze wskazaniem skryptu, a **searcher odmawia startu** (`init_db()` sprawdza obecność `bike_detail_photos.bike_id`).

## 6. Różnice względem starego scrapera

Krok 2 (Playwright: `_IMG_SRC`, `_SKIP`, maks. 8, `domcontentloaded` + 4 s, ten sam UA i viewport, patchright,
`BROWSER_SLOTS`) jest portem 1:1. Zmieniło się to, co poniżej — wszystko poza pierwszym punktem to odstępstwa od założenia
„1:1”, dopisane w kodzie przez implementatora:

| Różnica | Powód |
|---|---|
| Krok 1 (znalezienie strony producenta) idzie przez `claude -p` searchera (schemat JSON `{url}`) zamiast Anthropic SDK; prompt mówi `WebSearch` zamiast `web_search` i prosi o `{"url": …}` zamiast gołej linii | subskrypcja zamiast klucza API bez kredytów; ta sama zmiana transportu co w TODO-031..033 |
| CLI ma tylko `WebSearch` (bez `WebFetch`) i cały ruch przeglądarki przechodzi przez strażnika hostów publicznych (zob. „Bezpieczeństwo” niżej) | wektor SSRF przez URL od modelu |
| Błąd CLI to **502** (`SearcherError`), a stary finder zamieniał błąd API w `photos: []` | żeby przycisk w UI znów był klikalny zamiast fałszywego „Nie znaleziono zdjęć” |
| **URL zwrócony przez model jest walidowany przed otwarciem przeglądarki** (`is_public_http_url`): tylko http/https, bez danych logowania w URL, bez `localhost` / `*.local` / `*.internal`, każdy adres hosta musi być publiczny; przekierowanie poza publiczny internet odrzuca wynik | URL pochodzi z modelu czytającego internet, a przeglądarka działa wewnątrz naszej sieci (metadata server Cloud Run). Odrzucony URL kończy wyszukiwanie z `photos: []`. **Uwaga:** kontrakt zadania mówił „port 1:1 bez ulepszeń” — to jedyna świadoma zmiana zachowania scrapera |
| Zapis tylko dla roweru bez zdjęć, pod `SELECT … FOR UPDATE`; wyszukiwanie, które nic nie znalazło, nie zapisuje nic (nawet wiersza roweru) | decyzja „nigdy nie zastępuj”, także przy równoległych wyszukiwaniach z różnych procesów / instancji |

### Bezpieczeństwo (uruchomienie przeglądarki na adresie od modelu)

URL strony produktu pochodzi z modelu czytającego internet, a przeglądarka searchera działa wewnątrz naszej sieci, więc:

- uruchomienie CLI dla zdjęć ma **tylko `WebSearch`** (bez `WebFetch`) — tekst wstrzyknięty w wynik wyszukiwania nie skłoni go do pobierania dowolnych adresów;
- URL musi być http/https i wskazywać wyłącznie na adresy publiczne; routing żądań Playwrighta **przerywa każde żądanie do hosta niepublicznego** (przekierowania, subzasoby, fetch/XHR, nawigacje z JS); service workery zablokowane;
- zapisywane adresy obrazków: tylko http/https, ≤ 2048 znaków, bez nazw lokalnych i prywatnych adresów IP;
- zaakceptowane ograniczenie: **DNS rebinding** (host jest rozwiązywany przez strażnika i drugi raz przez Chromium, odpowiedzi mogłyby się różnić).

## 7. Jak to przetestowano

Środowisko testowe (nie domyślne porty): backend 8011, frontend 5181, searcher 8111, baza `biker_photos` = kopia lokalnej bazy
w kontenerze `biker-pg`, łączona przez `127.0.0.1` (`localhost` bywa przekierowany na relay WSL po `::1`). Współdzielona baza
`biker`, `backend/cache.db` w głównym checkoutcie i produkcyjny Cloud SQL nie były migrowane ani zapisywane.

Testy w repozytorium (bez płatnego uruchomienia):

- `backend/scripts/test_search.py`: `case_photos` — fixtura z trzema wierszami `bike_detail_photos` wstawionymi w złej
  kolejności i **bez** wiersza `bike_detail` → 200 z adresami w kolejności `display_order`, bez wiersza w generycznym cache,
  < 5 s; nieznany rower → szybki pusty 200. `case_photos_search` — nieznany rower → 404 przed wywołaniem searchera.
- `backend/scripts/test_details.py`: odpowiedź szczegółów **nie ma** klucza `photos`.
- `backend/scripts/test_browser_slots.py`: po usunięciu bike photos finder z backendu dotyczy tylko scrapera zdjęć sprzętu.
- `backend/scripts/test_searcher_client_photos.py` (pytest, dopisany do `backend/pytest.ini`): klient `search_photos` z
  podmienionym transportem httpx — żądanie (ścieżka `/v1/search/photos`, nagłówek klucza), single-flight, mapowanie 503/429 na
  „busy”, domyślny limit „w locie” = 10, poprawne i zniekształcone ciała odpowiedzi.
- `searcher/scripts/test_searcher.py`: 401 i 422 na `/v1/search/photos` oraz rower, który ma już zdjęcia → 200 z bazy,
  `saved: 0`, < 5 s (SKIP bez takiego roweru).

### Wyniki (kod zamrożony, środowisko: backend 8011, frontend 5181, searcher 8111, baza `biker_photos`)

| Test | Wynik |
|---|---|
| Backend `pytest -q` | **31 passed** |
| `backend/scripts/test_search.py` na 8011 / `biker_photos` | **11 passed, 0 failed, 4 skipped** — `decathlon_search` (searcher był wtedy wyłączony) i trzy przypadki `--ai` (brak kredytów API) |
| Frontend | `tsc -b --noEmit` bez błędów, `npm run build` OK, `eslint` bez uwag |

**Migracja** (`migrate_photos_bike_id.py`):

| Baza | Wynik |
|---|---|
| SQLite, kopia `cache.db` | dry-run: 4451 wierszy / 540 rowerów / 0 osieroconych; uruchomienie: 4451 → 4451; ponowne uruchomienie: `already-migrated` |
| SQLite, kopia z 8 wstrzykniętymi osieroconymi wierszami | 4451 → 4443, 8 wierszy zachowanych w `bike_detail_photos_orphans` |
| PostgreSQL, świeża niezmigrowana kopia `biker` (baza tymczasowa, potem usunięta) | dry-run; uruchomienie (z blokadą tabeli) 4443 → 4443 wiersze / 539 rowerów; ponowne uruchomienie bez zmian; uporządkowane listy URL identyczne z `biker` dla wszystkich 539 rowerów |
| PostgreSQL, tryb naprawy (usunięte FK, indeks i `NOT NULL` + 1 wiszący wiersz) | wykryto wszystkie trzy braki, naprawiono, wiszący wiersz przeniesiony do tabeli osieroconych |
| Współdzielona baza `biker` | suma kontrolna identyczna przed i po (nigdy nie była zapisywana) |

**Ponowny zapis szczegółów nie kasuje zdjęć:** na NIEZMIGROWANEJ kopii SQLite z włączonymi kluczami obcymi dwukrotne
`save_bike_details` dla Trek FX 3 → `id` wiersza szczegółów bez zmian, zdjęcia 8 → 8, wszystkich wierszy 4451 → 4451.

**Prawdziwe (płatne, na subskrypcji) wyszukiwania**, wszystkie na trekbikes.com:

| Rower | Wynik |
|---|---|
| Trek Marlin 4 | 6 zdjęć, 36 s |
| Trek Marlin 8 | 8 zdjęć, 32 s w trasie (CLI 20,5 s, scrape 11,3 s, 291 żądań przeglądarki przepuszczonych, 0 przerwanych) |
| Trek Marlin 7 przez przycisk w UI | 8 zdjęć, 45 s; po odświeżeniu obsłużone z `/v1/bike/photos` bez nowego wyszukiwania |

Log CLI podawał ok. 0,064–0,065 USD na run, rozliczane z subskrypcji.

**Testy ręczne** (skill `manual-tester`, Playwright, porty 5181 / 8011 / 8111): **32 zaliczone, 0 niezaliczonych, 0
zablokowanych, 4 niewykonane; bez defektów.** Pokryte: kolejność zapisanych zdjęć; dokładnie jedno wywołanie
`/v1/bike/photos` na otwarcie; brak klucza `photos` w details i details-cache; szczegóły z 2026-07-22 nadal serwowane (TTL
usunięty); poprawna galeria, gdy details zwraca 400/500 lub odpowiada wolno; 5 s okna ładowania; przepływ przycisku (jedno
`/missing` + jedno `/photos/search`, „Szukam zdjęć…”, pusty wynik → „Nie znaleziono zdjęć”, 503/502 → znów klikalny); trzy
scenariusze wyścigu przy przełączaniu rowerów; żaden wiersz zdjęć nie został usunięty ani zmieniony; zachowanie na
niezmigrowanej bazie (backend zwraca `[]` + ERROR ze wskazaniem skryptu, searcher odmawia startu); searcher 401/422 i
zapisane zdjęcia z `saved: 0`; regresja kart popularnych rowerów, ofert, recenzji i widoku sprzętu.

**Czego NIE przetestowano:**

- żywego backendu w przypadkach 503 „not configured” / „unavailable” (tylko testy jednostkowe);
- prawdziwego busy / single-flight pod obciążeniem;
- prawdziwego wyszukiwania, które nic nie znajduje;
- jakiejkolwiek strony producenta poza Trekiem;
- przerwania żądania przez strażnika tras wewnątrz prawdziwej przeglądarki (tylko z fałszywymi trasami);
- obrazu Docker, Cloud Run i Cloud SQL;
- dwóch procesów ścigających się na PostgreSQL.

## 8. Znane ograniczenia

- Nie sprawdzono `max_connections` Cloud SQL przy do 10 równoległych instancjach searchera (każda otwiera własne połączenia).
- Limit „w locie” backendu jest **na proces**: dwie instancje backendu przepuszczą razem do 20 wyszukiwań, więcej niż
  searcher (10) — nadwyżkę odeprze searcher / Cloud Run (429 → 503 busy).
- **Brak limitu żądań dla anonimowych wyszukiwań.** Przy limicie 10 każdy może przez `POST /v1/bike/photos/search` uruchomić do 10 równoległych płatnych runów subskrypcji dla istniejących rowerów, a rower, dla którego wyszukiwanie nic nie znalazło, można wyszukiwać ponownie bez końca (UI blokuje przycisk, `curl` nie). Planowaną odpowiedzią jest limit na IP („Step 2” wdrożenia).
- Pojemność bazy: 10 instancji searchera + 2 backendu, każda z własną pulą SQLAlchemy (domyślnie 5 + 10 nadmiarowych), a `max_connections` instancji Cloud SQL nie było sprawdzane (w `TODO_030`: „najmniejsza instancja shared-core”, `scripts/deploy.ps1` nie ustawia tieru). Lokalnie i w docker compose jeden kontener searchera dostaje wszystkie 10 slotów (przeglądarki ograniczone do 2 na proces), więc limitem jest RAM; `SEARCHER_MAX_CONCURRENT` można obniżyć w `searcher/.env`.
- Przy 10 slotach i 2 przeglądarkach na proces searchera lokalne/compose'owe wyszukiwania mogą czekać na przeglądarkę i przekroczyć 600 s timeoutu backendu (backend odpowie 503; searcher i tak skończy i zapisze zdjęcia, więc ponowna próba zwróci je bez drugiego płatnego runu). Na Cloud Run (`--concurrency 1`) to nie występuje.
- `saved` w odpowiedzi searchera to liczba wierszy zapisanych przez wyszukiwanie; wywołania, które dołączyły do trwającego wyszukiwania, dostają tę samą wartość, choć nic nie zapisały (backend to pole odrzuca).
- Znany błąd sprzed tej zmiany, poza zakresem: `save_bike_details` szuka roweru po dokładnej parze marka/model, a odczyt zdjęć po tożsamości znormalizowanej; istnieją zduplikowane wiersze `bike` różniące się tylko wielkością liter (2 tożsamości w kopii testowej) i zdjęcia na nowszym duplikacie są nieosiągalne przez `/v1/bike/photos`.
- Przeglądarki są ograniczone do 2 na proces searchera (`BROWSER_MAX_CONCURRENCY`, ~0,5–0,9 GiB każda), więc przy lokalnym
  jednym procesie z 10 slotami wyszukiwania OLX i zdjęć czekają w kolejce na przeglądarkę; na Cloud Run każda instancja
  obsługuje jedno żądanie (`--concurrency 1`), więc to ograniczenie tam nie boli.
- Scraper jest celowo prosty (regexy 1:1): strona producenta ładowana leniwie albo zza bota może dać 0 zdjęć albo zdjęcia
  nie-produktowe; poprawki z `docs/bikes/pipeline/photo_extract.py` świadomie odłożone.
- Nic nigdy nie zastępuje zdjęć — błędne zdjęcia trzeba usunąć ręcznie z bazy. Rower, dla którego wyszukiwanie nic nie
  znalazło, pozostaje bez zdjęć i przy następnym kliknięciu płaci kolejny run.
- Zdjęcia w wynikach wyszukiwania (`TODO_ISSUE_008`) nadal niezałatwione; pipeline offline
  (`docs/bikes/pipeline/db_saver.py`) używa teraz `photos_repository.save_bike_photos` (tak samo insert-only).

## 9. Lista kontrolna wdrożenia (wykonana 2026-09-29, poza krokiem 5)

**Kolejność jest krytyczna dla bezpieczeństwa danych.** Migracja musi przejść na bazie PRZED tym, zanim nowy backend lub searcher zacznie na niej działać:

- nowy searcher **odmawia startu** na niezmigrowanej bazie (Cloud Run zostawia wtedy stary rewizję), a nowy backend zwraca `{photos: []}`, dopóki migracja nie przejdzie;
- po migracji **aktualnie wdrożony (stary) backend przestaje działać na tej bazie** — nadal zapisuje `bike_detail_id`. Między krokiem 2 a 3 należy się spodziewać krótkiego okna, w którym zapis szczegółów starego backendu się nie udaje (rollback + ostrzeżenie w logu; żadne dane nie giną);
- nowy `save_bike_details` aktualizuje wiersz szczegółów w miejscu, więc nie uruchomi kaskady starego klucza obcego i nie skasuje zdjęć.

| Krok | Kto | Co |
|---|---|---|
| 1 | użytkownik | zgoda na deploy; merge PR-a dopiero po decyzji użytkownika |
| 2 | ja, na prośbę | **migracja na Cloud SQL `biker-pg` PRZED wdrożeniem backendu i searchera**: `python scripts/migrate_photos_bike_id.py --dry-run`, potem bez `--dry-run` (`--url` z hasłem tylko z gitignorowanego pgpass, nigdy w URL/repo); sprawdzić tabelę `bike_detail_photos_orphans` |
| 3 | ja | **zaraz po migracji, razem**: `scripts/deploy.ps1` — searcher (`--max-instances 10`, `--concurrency 1`) → backend; brak nowych sekretów i IAM |
| 3b | ja | frontend na końcu |
| 4 | ja | weryfikacja na publicznych URL-ach: `POST /v1/bike/photos` (pusty dla roweru bez zdjęć), nieznany rower → 404 na `/photos/search`, jedno prawdziwe wyszukiwanie, powtórka z bazy |
| 5 | do sprawdzenia | `max_connections` Cloud SQL względem 10 instancji searchera + 2 backendu |

### Wynik wdrożenia (2026-09-29)

| Element | Wynik |
|---|---|
| PR | #115 zmergowany, `main` = `1781f00` |
| Kopia zapasowa Cloud SQL | na żądanie, „before photos bike_id migration (PR 115)” |
| Migracja Cloud SQL | przed i po 4459 wierszy zdjęć, 541 rowerów, 0 sierot, `RESULT: migrated` (uruchomił użytkownik) |
| Cloud Run | `biker-searcher-00004`, `biker-backend-00009`, `biker-frontend-00007`, obraz `1781f00` |
| Lokalne bazy | `backend/cache.db` (4451 wierszy, 540 rowerów) i Postgres `biker` (4828 wierszy, 588 rowerów) zmigrowane, 0 sierot |
| Krok 5 (`max_connections`) | nadal niesprawdzony |

Test ścieżki głównej na produkcji (Playwright, 3 z 3 kroków):

| Krok | Rower | Wynik |
|---|---|---|
| Zapisane zdjęcia | Trek Marlin 5 | 8 zdjęć w kolejności z `/v1/bike/photos`, 0 wyszukiwań, `/v1/bike/details` bez pola `photos` |
| „Poproś o dane” | Trek Marlin 6 | pusta lista → przycisk, „Szukam zdjęć…”, 8 zdjęć po 42 s, jedno `/photos/search` i jedno `/missing` |
| Przeładowanie | Trek Marlin 6 | 8 zdjęć z bazy, 0 wyszukiwań |

W konsoli przeglądarki były odpowiedzi 400 z `/v1/bike/details` i `/v1/bike/review`: te endpointy nadal używają klucza
Anthropic API (nie subskrypcji), a konto nie ma kredytów. Zdjęć to nie dotyczy.

## 10. Jak tego używać

```bash
# migracja (raz na każdej istniejącej bazie)
cd backend && python scripts/migrate_photos_bike_id.py --dry-run && python scripts/migrate_photos_bike_id.py

# ręcznie na searcherze (lokalnie: klucz z searcher/.env)
curl -X POST http://localhost:8100/v1/search/photos \
  -H "Content-Type: application/json" -H "X-Searcher-Key: dev-local-searcher-key" -d '{"company":"Trek","model":"Marlin 4"}'

# przez backend (to, co robi przycisk w galerii)
curl -X POST http://localhost:8000/v1/bike/photos/search -H "Content-Type: application/json" -d '{"company":"Trek","model":"Marlin 4"}'
curl -X POST http://localhost:8000/v1/bike/photos        -H "Content-Type: application/json" -d '{"company":"Trek","model":"Marlin 4"}'

# smoke testy (darmowe)
cd backend && python scripts/test_search.py        # case_photos + case_photos_search
cd searcher && python scripts/test_searcher.py     # 401/422 + zdjęcia z bazy
```
