# TODO-042 — Wyposażenie (kaski, światła, zapięcia, odzież) przez searcher (ten sam schemat co TODO-031 / 032 / 033 / 035 / 037 / 041)

Wzorce: `backlog/done/DONE_041_DETAILS_SEARCHER.md` (najbliższy), `DONE_035_PHOTOS_SEARCHER.md`, `DONE_033_SEARCHER_ALLEGRO_ON_DEMAND.md`;
szablon zapisu procesu: `docs/ALLEGRO_SEARCHER_MIGRATION.md`. Branch `feature/042-equipment-searcher`. Zostaje `TODO_`, dopóki PR
nie zostanie zmergowany do `main` (potem `DONE_` + `backlog/done/` + `backlog/done/README.md`). Zapis po polsku na końcu:
`docs/EQUIPMENT_SEARCHER_MIGRATION.md`. Limity: searcher `SEARCHER_MAX_CONCURRENT` 10, backend `SEARCHER_MAX_INFLIGHT` 10, wspólne dla
wszystkich tras (po tym zadaniu osiem tras).

## Cel

Wyposażenie działa jak rowery. `POST /v1/equipment/details` i nowy `POST /v1/equipment/photos` stają się **czystym odczytem z bazy** (bez AI,
bez generycznego cache, bez TTL). Wyszukiwanie dzieje się wyłącznie na żądanie, w searcherze (`claude -p`, subskrypcja), po kliknięciu
**Poproś o dane**. Powód: klucz Anthropic API w backendzie nie ma kredytów (nieskeszowane `/v1/equipment/details` kończy się 500), a searcher
rozlicza się z subskrypcją.

## Punkt wyjścia (stan na `main`, 2026-10-01)

- `POST /v1/equipment/details` (`backend/app/main.py` ~519–551): `get_cached` → trzy finderi w jednym `asyncio.gather` (Anthropic SDK, Haiku):
  `equipment_details_finder.find_equipment_details` (jeden fokusowany prompt `equipment_details_{slug}.md`, kategoria podana lub wywnioskowana
  przez `equipment_categories.resolve_category`), `equipment_description_finder` (`web_search`, 4–5 zdań), `equipment_photos_finder`
  (`web_search` → URL strony producenta → Playwright, ≤ 8 `<img>`; trzyma `BROWSER_SLOTS`). Wynik **zawsze** do generycznego cache (kluczem
  `{company, model, category}`), także pusty. Odpowiedź: `{company, model, category, description, components, photos}`.
- `equipment_categories.py`: 4 kategorie (`helmets`, `lights`, `locks`, `apparel`), prompty ładowane przy imporcie, wnioskowanie po słowach
  kluczowych, `apparel` jako worek na resztę.
- **Brak tabel wyposażenia.** Wyposażenie nie ma tożsamości w bazie; nic nie jest utrwalane poza JSON-em w generycznym cache.
- Frontend: kliknięcie nazwy elementu w drzewie komponentów roweru woła `handleEquipmentSelect(name)` (`App.tsx` ~429) z `company: ''`,
  `model: nazwa elementu`; widok od razu sam woła `/v1/equipment/details` i `/v1/equipment/review`. `EquipmentDetailsView` **nie ma**
  `RequestDataButton` — tylko szkielet ładowania i błąd z ponowieniem. Zdjęcia przychodzą razem ze szczegółami.
- `POST /v1/equipment/review` (SDK + generyczny cache) zostaje bez zmian — patrz „Poza zakresem”.

## Decyzje z wywiadu (stałe)

1. **Backend**: `POST /v1/equipment/details` i nowy `POST /v1/equipment/photos` = czysty odczyt z bazy. Nowe `POST /v1/equipment/details/search` i
   `POST /v1/equipment/photos/search` proxują do searchera przez `app/searcher_client.py` (te same mapowania 404 / 503 / 502 / 400, single-flight,
   wspólny limit `SEARCHER_MAX_INFLIGHT`, korekta 429 Cloud Run = busy).
2. **Searcher**: osobne trasy `POST /v1/search/equipment/details` (jeden `claude -p`: komponenty + opis + `short_description`, prompt per kategoria,
   `WebSearch` + `WebFetch`, bez Playwrighta) oraz `POST /v1/search/equipment/photos` (jeden `claude -p` z samym `WebSearch` po URL strony
   producenta + istniejący utwardzony scrape Playwright, ≤ 8 zdjęć, tylko dla wyposażenia, które zdjęć nie ma).
3. **Dane — nowe tabele**: `equipment`, `equipment_detail`, `equipment_detail_component`, `equipment_detail_photos` (kolumny w „Tabele i migracja”)
   **oraz** nullowalna kolumna `bike_detail_component.equipment_id` (FK → `equipment.id`, `ON DELETE SET NULL`).
4. **Powiązanie rower → wyposażenie**: klik w nazwę elementu otwiera widok wyposażenia. Gdy wiersz `bike_detail_component` ma `equipment_id`, widok od razu
   czyta zapisane dane po tym id. Gdy nie ma — sekcje Opis/Komponenty (jeden wspólny run) i galeria zdjęć pokazują **Poproś o dane**
   (`RequestDataButton`, jak w `BikeDetailsView`). Żądanie wyszukiwania niesie `company` + `model` **roweru**, `element_name` (i kategorię, jeśli znana).
   Searcher tworzy wiersz `equipment` i po udanym zapisie ustawia `equipment_id` na wierszach `bike_detail_component` **tego roweru** o tej nazwie
   elementu — nigdy globalnie.
5. **Kształty odpowiedzi**: `EquipmentDetailsResponse` bez `photos`, z `short_description` i `equipment_id`; zdjęcia jako `{ photos }`.
6. **Migracja**: jeden idempotentny skrypt `backend/scripts/migrate_equipment_tables.py` (SQLite + PostgreSQL, `--dry-run`, `--db`, `--url`,
   importowalne `migrate(...)`), uruchamiany na każdej istniejącej bazie przed wdrożeniem. Searcher nosi dosłowną kopię DDL w `searcher/app/models.py`
   i `init_db()` **odmawia startu** bez `bike_detail_component.equipment_id`.
7. **Wdrożenie**: jak TODO-041 — backup → migracja na Cloud SQL → backend + searcher razem → frontend; **tylko na wyraźne „go” użytkownika**.
8. **Proces**: najpierw sondy (stare prompty wyposażenia przez `claude -p`, czy wymagają przepisania pod CLI — jak Allegro), potem kod.
9. Stare `backend/app/equipment_details_finder.py`, `equipment_description_finder.py`, `equipment_photos_finder.py`, ich prompty
   (`equipment_details_{slug}.md` ×4, `equipment_description.md`, `equipment_photos.md`) i `scripts/test_equipment.py` znikają z backendu
   (prompty przechodzą do `searcher/app/prompts/`). `equipment_review_finder.py` + `equipment_review.md` zostają.

## Założenia (spoza wywiadu — do potwierdzenia przy przeglądzie)

- **Tożsamość wyposażenia**: wiersz `equipment` ma `company` = `""` i `model` = nazwa elementu z drzewa roweru (tak jak dziś robi to frontend); UNIQUE
  `(category, company_norm, model_norm)`. Ten sam element na drugim rowerze trafia w ten sam wiersz, ale **nie jest linkowany automatycznie** (decyzja 4:
  nigdy globalnie). Żeby nie płacić drugiego runu, odczyt bez `equipment_id` idzie po nazwie: frontend woła `POST /v1/equipment/details` / `/photos`
  z `{company: "", model: nazwa elementu}`, a backend szuka wiersza po `(company_norm, model_norm)` **niezależnie od kategorii** (pierwszy po `id`);
  trafienie pokazuje dane bez przycisku, brak trafienia pokazuje przyciski. Link powstaje dopiero po udanym wyszukiwaniu.
- **Kategoria** jest wnioskowana w searcherze (`resolve_category` przechodzi do `searcher/app/equipment_categories.py`); 4 kategorie 
  (kaski, lampy, zapięcia, odzież) + piąta `parts` (Bike parts & components, etykieta PL "Części rowerowe") dla rzeczy generycznych 
  (derailleur, Bar Tape, reflektory) zamiast apparel fallback. Kategorie drzewa roweru (Frame, Drivetrain…) to nie kategorie wyposażenia, 
  więc frontend zwykle jej nie zna.
- **Wyszukiwanie niczego nie zapisuje, gdy wynik bezużyteczny** (puste komponenty **i** pusty opis / brak zdjęć): bez wiersza `equipment`, bez linku.
- **Zdjęcia też linkują**: udany zapis zdjęć ustawia `equipment_id` tak samo jak szczegóły (inaczej zdjęcia byłyby nieosiągalne po id).
- **Backend 404**: `"Bike not found"`, gdy roweru nie ma w `bike` (`offers_repository.bike_exists`), oraz `"Component not found"`, gdy rower nie ma elementu
  o tej nazwie w `bike_detail_component` — przed jakimkolwiek wywołaniem searchera (anonimowy ruch nie wypala runów na dowolne napisy).
- **Bez wstępnego odczytu** (jak po PR #134/#135): ani backend, ani searcher nie czytają zapisanych danych przed wyszukiwaniem; o tym, czy run ma sens,
  decyduje UI (przycisk tylko, gdy nic nie zapisano). Straż po stronie zapisu: zdjęć nigdy się nie podmienia, szczegóły zapisuje się tylko gdy użyteczne.
- **Re-zapis szczegółów roweru nie może gubić linków**: `save_bike_details` (backend) i `save_details` (searcher) **kasują i wstawiają** wiersze
  `bike_detail_component`, więc przed wymianą trzeba zapamiętać mapę `element_name → equipment_id` i nałożyć ją na nowe wiersze o tej samej nazwie.
- Liczniki „Poproś o dane” (`/v1/bike/missing`) dla wyposażenia: **pomijamy** (tabela `bike_missing_request` jest per rower); wrócić do tematu tylko jeśli
  okaże się trywialne.

## Kontrakt modułów

### Searcher (`searcher/`)

- `POST /v1/search/equipment/details` + `X-Searcher-Key`, ciało
  `{"bike_company": "Canyon", "bike_model": "Grizl CF 7 ESC", "element_name": "Abus Hyban 2.0", "category": "helmets"}` (`category` opcjonalne; `element_name`
  ≤ 255, pozostałe niepuste ≤ 255 → 422 inaczej). Odpowiedź `{"details": EquipmentDetailsResponse, "equipment_id": 7, "saved": 1}`; `saved` = 1 tylko
  po zapisie. Ta sama autoryzacja (401), te same mapowania 422/502/503/500, **ten sam semafor** co pozostałe trasy.
- `POST /v1/search/equipment/photos` + `X-Searcher-Key`, to samo ciało → `{"photos": [url…], "equipment_id": 7, "saved": 3}`. Strona producenta musi być
  publicznym http(s); każde żądanie przeglądarki idzie przez ten sam `_RouteGuard`; w bazie URL obrazu http/https ≤ 2048, nie lokalny. Zdjęcia
  wstawiane tylko dla wyposażenia, które ich nie ma (insert-only pod `SELECT … FOR UPDATE` na wierszu `equipment`); wynik pusty nie zapisuje nic.
- `app/equipment_details_finder.py` (nowy): `find_equipment_details(...)` — `run_structured` (`WebSearch,WebFetch`), schemat jak `DETAILS_SCHEMA`
  (`found`, `description`, `short_description`, `sources`, `components`), prompt `prompts/equipment_details_{slug}.md`, `BikeDescription` budowany ze `sources`
  (jedna zmiana segmentu, bez cytowań per zdanie), `found: false` → nic nie zapisujemy. Opis i `short_description` po polsku, `category`/`subcategory`/klucz specyfikacji
  angielskie, `name`/`value` jak u producenta.
- `app/equipment_photos_finder.py` (nowy): przeniesiony utwardzony `photos_finder` (te same regexy `_IMG_SRC`/`_SKIP`, ten sam strażnik tras) z promptem
  `prompts/equipment_photos.md` (CLI: `WebSearch` zamiast `web_search`, odpowiedź `{"url": …}`).
- `app/equipment_categories.py` (nowy, kopia rejestru z backendu), `app/prompts/equipment_details_{helmets,lights,locks,apparel}.md`,
  `equipment_photos.md` (przepisane tylko tam, gdzie sondy pokażą potrzebę).
- `app/repository.py`: `save_equipment_details`, `save_equipment_photos`, wspólny `_link_bike_components(bike_id, element_name, equipment_id)` (UPDATE tylko
  wierszy tego roweru z tą `element_name`, w tej samej transakcji co zapis); `app/models.py`: dosłowna kopia DDL + `REQUIRED_TABLES` + sprawdzenie kolumny
  `bike_detail_component.equipment_id`; `app/schemas.py`, `app/main.py` (dwie trasy, busy slot, 401/422); `README.md` (`## Endpoints` + Flow:
  `claude -p` × 1, zapis do bazy; zdjęcia dodatkowo Playwright × 1).
- `scripts/test_searcher.py`: 401 i 422 na obu trasach (bez runów CLI; po #134 nie ma już testu „zapisane zdjęcia bez runu”).

### Backend (`backend/`)

- `app/models.py` — modele `Equipment`, `EquipmentDetail`, `EquipmentDetailComponent`, `EquipmentDetailPhoto`; `BikeDetailComponent.equipment_id`
  (nullable, `ForeignKey("equipment.id", ondelete="SET NULL")`, indeks).
- `app/schemas.py` — `ComponentElement.equipment_id: Optional[int] = None` (frontend dostaje go z `POST /v1/bike/details`);
  `EquipmentDetailsResponse`: bez `photos`, plus `short_description: str = ""`, `equipment_id: Optional[int] = None`;
  `EquipmentDetailsRequest` dostaje `equipment_id: Optional[int]` (czytanie po id; gdy brak — po `(category, company, model)` znormalizowanych w Pythonie);
  nowe `EquipmentPhotosRequest`/`EquipmentPhotosResponse` (`{photos, equipment_id}`), `EquipmentSearchRequest`
  (`bike_company`, `bike_model`, `element_name`, `category?`, `max_length=255`).
- `app/equipment_repository.py` (nowy) — `get_equipment_details`, `get_equipment_photos` (tylko odczyt, `ORDER BY display_order, id`; nieznane wyposażenie /
  błąd bazy → pusta odpowiedź 200, błąd bazy też loguje ERROR); `app/repository.py` — `get_bike_details` oddaje `equipment_id` elementów,
  `save_bike_details` zachowuje linki (założenia wyżej); normalizacja `norm()` w Pythonie, nigdy `func.lower()`.
- `app/searcher_client.py` — `SEARCH_PATHS["equipment_details"]`, `["equipment_photos"]`, `search_equipment_details()` (rozpakowuje `{details, …}`),
  `search_equipment_photos()`; single-flight kluczem `(path, bike, element_name)`; ten sam semafor; `SearcherLimitReached` → 400 przez istniejący handler.
- `app/main.py` — `/v1/equipment/details` i `/v1/equipment/photos` = odczyt; `/v1/equipment/details/search`, `/v1/equipment/photos/search`: 404 (rower /
  element) → searcher → 503 (stałe napisy `"Equipment details searcher is not configured"` / `"… unavailable"` / `"… is busy — try again in a moment"`, analogicznie
  `"Equipment photos searcher …"`) / 502 (detail searchera) / 400 (limit subskrypcji). Usunięcie importów i martwego kodu (`browser_config.py`,
  `test_browser_slots.py`, `shot_offers.py` — dopiero po `grep`; Dockerfile nie ruszamy).
- `scripts/migrate_equipment_tables.py` (nowy); testy w sekcji „Testy”.

### Frontend (`frontend/`)

- `src/types.ts`: `ComponentElement.equipment_id?: number | null`; `EquipmentDetailsResponse` bez `photos`, plus `short_description`, `equipment_id`;
  `EquipmentPhotosResponse`; `EquipmentSelection` = `{ name, equipmentId, bikeCompany, bikeModel }`.
- `src/components/BikeDetailsShared.tsx`: `onElementSelect` oddaje cały element (nazwa + `equipment_id`), `App.handleEquipmentSelect` ustawia `equipItem`.
- `src/App.tsx`: widok wyposażenia po otwarciu **czyta** `POST /v1/equipment/details` / `/photos` (po `equipment_id`, gdy jest; gdy go nie ma — po
  `{company: "", model: nazwa elementu}`; pusta odpowiedź = przyciski); `searchEquipmentDetails` / `searchEquipmentPhotos` przez wspólne `postOnDemandSearch` (rzuca przy nie-OK, wpisuje wynik do stanu
  **bez** przełączania na `'loading'`, ochrona `selectedBikeRef`/analogiczna dla wyposażenia); po udanym wyniku wstrzykuje `equipment_id` do elementu w
  `bikeCategories`, żeby powrót i ponowne wejście nie kosztowały kolejnego runu. `POST /v1/equipment/review` bez zmian.
- `src/components/EquipmentDetailsView.tsx`: `RequestDataButton` w Opisie i Komponentach (jeden wspólny run: ten sam `watch`, `pendingLabel="Szukam danych
  wyposażenia…"`, `emptyLabel="Nie znaleziono danych"`) oraz w galerii zdjęć (`pendingLabel="Szukam zdjęć…"`, `emptyLabel="Nie znaleziono zdjęć"`); tylko na klik,
  nigdy automatycznie. Odpowiedź bez opisu i bez komponentów = „brak danych”, nie błąd. Bez `/v1/bike/missing`.
- `frontend/README.md`: mapa etykiet PL + lista API.

## Tabele i migracja

Wszystkie kolumny tekstowe z limitami czytanymi z modeli (PostgreSQL odrzuca to, co SQLite przyjmuje).

| Tabela | Kolumny |
|---|---|
| `equipment` | `id`, `category` (slug, ≤ 32), `company` (może być `""`), `model`, `company_norm`, `model_norm` (`strip().lower()` w Pythonie, `@validates`), `created_at`; `UNIQUE(category, company_norm, model_norm)` |
| `equipment_detail` | `id`, `equipment_id` (FK → `equipment.id` `ON DELETE CASCADE`, UNIQUE), `description` (JSON `BikeDescription`), `short_description` (`Text NOT NULL DEFAULT ''`), `created_at`, `updated_at` |
| `equipment_detail_component` | płaski kształt jak `bike_detail_component`, FK → `equipment_detail.id` `ON DELETE CASCADE` |
| `equipment_detail_photos` | `id`, `equipment_id` (FK → `equipment.id` `ON DELETE CASCADE`, `NOT NULL`, indeks), `url` (≤ 2048), `display_order` |
| `bike_detail_component` | **+** `equipment_id` (nullable, FK → `equipment.id` `ON DELETE SET NULL`, indeks) |

- `scripts/migrate_equipment_tables.py`: tworzy cztery nowe tabele (`create_all(checkfirst)`) i dodaje `bike_detail_component.equipment_id` tylko, gdy go brak
  (SQLite: `ALTER TABLE … ADD COLUMN … REFERENCES`; PostgreSQL: `ADD COLUMN` → FK → indeks, `LOCK TABLE … SHARE ROW EXCLUSIVE`), jedna transakcja, porównanie
  liczby wierszy `bike_detail_component` przed i po, `already-migrated` przy ponownym uruchomieniu, `--dry-run`, `--db`, `--url`, `migrate(...) -> dict`.
- Uruchomić na kopii lokalnej bazy (SQLite i `biker-pg`) i opisać w `backend/app/DB_MIGRATION.md`. Nowy backend na niezmigrowanej bazie nie działa (ORM czyta
  nową kolumnę); **stary backend działa na zmigrowanej** (kolumna nullowalna, nowe tabele ignoruje). Searcher nie wystartuje bez kolumny.

## Testy

- **pytest** (`backend/scripts/`, `pytest.ini`): `test_searcher_client_equipment.py` (mock httpx: ścieżki i nagłówek, rozpakowanie `{details, …}`, single-flight,
  busy 503 i 429, wspólny limit, mapowanie błędów, limit 400, walidacja ciała), `test_equipment_repository.py` (tymczasowy SQLite: zapis → odczyt po id,
  zachowanie linków po re-zapisie szczegółów roweru, pusty wynik nic nie zapisuje, zdjęcia insert-only), `test_migrate_equipment_tables.py` (idempotencja,
  `--dry-run`, wiersze bez zmian).
- **Smoke** `backend/scripts/test_search.py`: `case_equipment_details` i `case_equipment_photos` (zasiane wyposażenie → 200 z zapisanymi wartościami, brak wiersza w
  generycznym cache, < 5 s; nieznane id → szybkie puste 200), `case_equipment_details_search` / `case_equipment_photos_search` (nieznany rower i nieznany element → 404 —
  **bez płatnego runu**). Nagłówek pliku (`test_equipment.py` znika) zaktualizowany.
- **Searcher** `searcher/scripts/test_searcher.py`: 401 i 422 na obu nowych trasach, bez runów CLI. Testy limitu/502 tras (`test_cli_limit.py`) obejmują nowe trasy.
- Najwyżej **jeden** płatny run w całym zestawie; reszta darmowa.

## Weryfikacja

`/manual-tester` dwa razy: na realnym searcherze (jeden płatny run szczegółów i jeden zdjęć, rower z elementem bez `equipment_id`, potem ponowne wejście = dane z bazy
bez runu) oraz na fałszywym searcherze (503 / 502 / 400 / busy / pusty wynik → „Nie znaleziono danych”, ponowny klik po błędzie). Plan i wyniki w
`docs/testing/TODO_042/TEST_PLAN.md`. Wdrożenia nie robimy.

## Wdrożenie (do zapisania, wykonać dopiero po „go”)

1. Ręczny backup Cloud SQL (`biker-pg`). 2. `migrate_equipment_tables.py` na Cloud SQL przez proxy (**pierwsze**). 3. `scripts/deploy.ps1` — backend i searcher razem
(nowy searcher nie wystartuje bez kolumny). 4. Frontend. Okno między 2 a 3 jest bezpieczne dla starego backendu. Zmiana `--max-instances` niepotrzebna (limit 10
dzielony przez osiem tras).

## Poza zakresem

- `POST /v1/equipment/review` (zostaje na SDK i generycznym cache — osobne, późniejsze TODO); globalne linkowanie po nazwie na wszystkich rowerach; zmiany
  funkcjonalne w `/v1/bike/*`; ewentualne `/v1/equipment/*` w `bike_missing_request`; Ceneo; rate limit na anonimowe wyzwalacze; wdrożenie bez „go”; kasowanie
  starych wierszy `/v1/equipment/details` z generycznego cache (martwe, nic ich nie czyta — osobny skrypt purge, jeśli kiedyś zajdzie potrzeba).
- **`refactor/remove-bike-detail` (PR #137) i TODO-043 (PR #136)** weszły do `main` po bazie TODO-042 i zostały zmergowane do tej
  gałęzi 2026-10-01 (szczegóły w „Wynik” i w `docs/EQUIPMENT_SEARCHER_MIGRATION.md` § 8).

## Kryteria akceptacji

- [ ] `POST /v1/equipment/details` i `POST /v1/equipment/photos` zwracają zapisane dane po `equipment_id` bez AI i bez wiersza w generycznym cache, < 5 s; nieznane → 200 z pustą odpowiedzią.
- [ ] `…/details/search` i `…/photos/search`: nieznany rower / element → 404 przed searcherem; niekonfigurowany / niedostępny / zajęty (też 429) → 503 ze stałym napisem; błąd searchera → 502 z jego detalem; limit subskrypcji → 400; identyczne równoległe żądania dzielą jeden run.
- [ ] Searcher zapisuje tylko użyteczny wynik, tworzy `equipment`, linkuje wyłącznie wiersze tego roweru o tej nazwie, nie podmienia zdjęć, nie kasuje niczego przy pustym wyniku.
- [ ] Re-zapis szczegółów roweru (backend i searcher) zachowuje `equipment_id` elementów o tych samych nazwach.
- [ ] Migracja idempotentna (SQLite + PostgreSQL, `--dry-run`); searcher odmawia startu bez `equipment_id`; stary backend działa na zmigrowanej bazie.
- [ ] UI: klik w element z `equipment_id` pokazuje zapisane dane od razu; bez niego — przyciski (Opis+Komponenty wspólny run, osobny dla galerii), tylko na klik; wynik wypełnia sekcje i nie kosztuje drugiego runu po powrocie.
- [ ] `/v1/equipment/review` i `/v1/bike/*` bez zmian zachowania; usunięte findery i prompty nie zostawiają martwych importów.
- [ ] Testy z sekcji „Testy” zielone, najwyżej jeden płatny run; `/manual-tester` zielony na realnym i fałszywym searcherze.
- [ ] Dokumentacja wg Documentation Update Policy (`CLAUDE.md`, `README.md`, `backend/README.md` z `## Endpoints` + Flow, `searcher/README.md`, `frontend/README.md`, `backend/app/DB_MIGRATION.md`) i `docs/EQUIPMENT_SEARCHER_MIGRATION.md`.

## Wynik (2026-10-01)

- **QA:** 26 z 26 przypadków zaliczonych (0 niezaliczonych, 0 zablokowanych) na izolowanej kopii PostgreSQL `biker_qa042`; pytest backend 152, searcher 169, build frontendu ok, smoke 18 zaliczonych / 4 pominięte. Plan: `docs/testing/TODO_042/TEST_PLAN.md`.
- **Zakres rozszerzony w trakcie:** piąta kategoria `parts` (domyślna, własny prompt), reguła rzeczownika głównego przy wnioskowaniu kategorii (`locks` przed `lights`), filtr źródeł sklepowych `searcher/app/shop_filter.py`, sześć nowych etykiet w `frontend/src/specLabels.ts`.
- **Płatne runy (4):** Trek Marlin 5 / Shimano Altus RD-M315 (szczegóły 40,1 s `found:false`, zdjęcia 46,0 s bez URL); Kona El Kahuna / Abus T82 Battery Lock (szczegóły 54,4 s, 0,17 USD, zapisane jako `equipment` id 4; zdjęcia 106,5 s, 0,36 USD, URL na nieistniejący host odrzucony przez strażnika).
- **Migracja** uruchomiona naprawdę na lokalnym `biker-pg` 2026-10-01 (`migrated`, 32972 wiersze zachowane, ponowny run `already-migrated`).
- **Zostaje:** merge PR (dopiero wtedy przeniesienie do `backlog/done/`); wdrożenie GCP wyłącznie na wyraźne „go” (backup → migracja na Cloud SQL przez proxy → backend + searcher razem → frontend); Opis całości: `docs/EQUIPMENT_SEARCHER_MIGRATION.md`.
- **Merge `origin/main` (2026-10-01):** PR #137 (`bike_detail` usunięte, opis na `bike`, `bike_detail_component` kluczowane `bike_id`) i PR #136
  (TODO-043). `equipment_id` zostaje na przekluczonej tabeli; migawka linków przy re-zapisie roweru (backend i searcher), linkowanie i strażnik
  „Component not found” czytają wiersze po `bike_id`. Kolejność migracji: `migrate_drop_bike_detail.py` → `migrate_equipment_tables.py` (nasz
  skrypt odmawia tabeli z `bike_detail_id`, bo przebudowa SQLite w migracji z `main` gubi dodatkowe kolumny). Testy po merge'u: backend 162,
  searcher 169, webscraper 187, build frontendu ok, smoke 18 / 4 pominięte.
- **Możliwy follow-up (spójność):** spłaszczyć `equipment_detail` do kolumn na `equipment`, tak jak rower po PR #137 — celowo nie w tym merge'u.
