# Jak wyposażenie (kaski, światła, zapięcia, odzież, części) przeszło z endpointu backendu do searchera (TODO-042)

Zapis całego procesu — od stanu wyjściowego, przez wywiad, sondy, implementację i przeglądy, aż po testy ręczne — z datą
2026-10-01. Kolejna powtórka schematu z `docs/OLX_SEARCHER_MIGRATION.md` (TODO-031), `docs/DECATHLON_SEARCHER_MIGRATION.md`
(TODO-032) i `docs/ALLEGRO_SEARCHER_MIGRATION.md` (TODO-033), ale z własnymi tabelami i migracją schematu jak w TODO-041.
Branch `feature/042-equipment-searcher`, zadanie `backlog/done/DONE_042_EQUIPMENT_SEARCHER.md`, sondy
`docs/testing/TODO_042/PROBES.md`, plan i wyniki testów `docs/testing/TODO_042/TEST_PLAN.md`.

## 1. Punkt wyjścia

`POST /v1/equipment/details` w backendzie przy każdym nieskeszowanym wywołaniu: `get_cached` → trzy findery w
`asyncio.gather` (Anthropic SDK, Haiku): `equipment_details_finder` (jeden prompt per kategoria),
`equipment_description_finder` (`web_search`) i `equipment_photos_finder` (`web_search` + Playwright). Wynik zawsze do
generycznego cache, także pusty. Brak tabel wyposażenia — nic nie było utrwalane poza JSON-em w cache. Zdjęcia były częścią
odpowiedzi `/details`, nie miały własnej trasy.

Problem: klucz API od 2026-09-26 ma zero kredytów (nieskeszowane `/v1/equipment/details` → 500), a searcher rozlicza się z
subskrypcją Claude Code.

## 2. Wywiad i decyzje (4 pytania)

1. Odczyty z bazy (`POST /v1/equipment/details`, `POST /v1/equipment/photos`) plus nowe trasy `/search` w searcherze.
2. Tabele: `equipment`, `equipment_detail`, `equipment_detail_component`, `equipment_detail_photos` oraz nullowalna
   `bike_detail_component.equipment_id` — link dotyczy wyłącznie wiersza tego roweru.
3. Klik w element roweru otwiera widok wyposażenia; przycisk „Poproś o dane” tylko wtedy, gdy nic nie zapisano.
4. Migracja i wdrażanie jak w TODO-041: backup → migracja → backend + searcher razem → frontend, tylko na wyraźne „go”.

## 3. Sondy (2026-10-01)

Stare prompty backendu przez `claude -p` ze schematem searchera. Pięć przebiegów bez błędów CLI, trzy defekty wymusiły
poprawki promptów:

| Kategoria | Czas | Wynik |
|---|---|---|
| Kaski (POC Octal MIPS) | 99,8 s | ok |
| Lampy (Lezyne Macro Drive) | 53,1 s | ok |
| Zapięcia (Kryptonite Evolution) | 58,6 s | ok |
| Odzież (Castelli Perfetto) | 52,3 s | defekt `short_description` (52 znaki + etykieta) |
| Zdjęcia (POC Octal MIPS) | 19,3 s | ok |

Poprawki: `short_description` do ok. 400 znaków bez `\n\n`, opisy elementów po polsku, zakaz sklepów w `sources`.
Re-sondy na nowych promptach (odzież, Bar Tape) — bez defektów. Sondy pokazały też, że części roweru (Bar Tape, przerzutka)
lądują w `apparel` jako koszu na wszystko — stąd piąta kategoria, patrz § 5.

## 4. Kontrakt między modułami

**Searcher**: `POST /v1/search/equipment/details` i `/v1/search/equipment/photos`, ciało `{bike_company, bike_model,
element_name, category?}`, odpowiedzi `{details, equipment_id, saved}` i `{photos, equipment_id, saved}`. Jeden `claude -p`
na przebieg (szczegóły: `WebSearch` + `WebFetch`, zdjęcia: tylko `WebSearch` + Playwright ze strażnikiem adresów).

**Backend** (`backend/app/equipment_routes.py`, `equipment_repository.py`, `equipment_models.py`, `component_tree.py`):
`POST /v1/equipment/details` i `/photos` to czysty odczyt (po `equipment_id` albo po znormalizowanym `(company, model)`),
`/details/search` i `/photos/search` proxują do searchera po sprawdzeniu, że rower i element istnieją (404 przed jakimkolwiek
runem). `POST /v1/bike/details` zwraca teraz `equipment_id` przy elementach.

**Frontend**: klik w element z `equipment_id` czyta dane po id; bez niego widok pokazuje przyciski (Opis i Komponenty mają
wspólny run, galeria osobny). Po udanym wyniku `equipment_id` trafia do elementu, więc ponowne wejście nie kosztuje runu.

## 5. Implementacja: równoległy workflow agentów

Workflow agentów: backlog i sondy, potem backend (dane, trasy), searcher, frontend, na końcu dwa przeglądy i dokumentacja.

**Piąta kategoria `parts`.** Zakres obejmuje pięć kategorii: kaski, światła, zapięcia, odzież i `parts`
(wyświetlana „Bike parts & components”, po polsku „Części rowerowe”, własny prompt
`searcher/app/prompts/equipment_details_parts.md`). `parts` jest domyślna, gdy żadne słowo kluczowe nie pasuje. Reguły
w `searcher/app/equipment_categories.py`: słowa dopasowują się od początku wyrazu; przy kilku trafieniach wygrywa to, które
zaczyna się najpóźniej w nazwie (rzeczownik główny: „Abus T82 Battery Lock” → zapięcie), przy remisie dłuższe słowo, potem
`locks` przed `lights`; samo „battery” to część, chyba że w nazwie jest też słowo o świetle.

**Przeglądy.** Poprawność (Opus): 2 uwagi medium (blokada przed zapisem szczegółów, migawka mapowania nazw przy linkach)
i 4 low. Bezpieczeństwo (Sonnet): 23 testy cURL, 3 uwagi low. Wszystkie naprawione w gałęzi.

**Incydent z nieaktualnym agentem.** Agent z poprzedniej sesji dalej działał i zmienił `searcher/app/models.py` (jedna
nieszkodliwa wartość domyślna). Lekcja: przed rozdaniem pracy sprawdzić listę żywych agentów.

**Migracja** `backend/scripts/migrate_equipment_tables.py` uruchomiona naprawdę na lokalnym `biker-pg` 2026-10-01: status
`migrated`, 32972 wiersze `bike_detail_component` zachowane, ponowne uruchomienie `already-migrated`.

## 6. Weryfikacja lokalna — testy ręczne

Agent manual-tester (Opus) na izolowanej kopii PostgreSQL `biker_qa042` w kontenerze `biker-pg` (po sesji skasowanej).
Wspólna baza `biker` nie nadawała się: inny worktree (`refactor/remove-bike-detail`) zdążył ją przebudować. Porty: backend
8003, frontend 5178, searcher 8101. Rundy 1, 1b i 2 (fałszywy searcher: 503 / 502 / 400 / 429 / pusty wynik) plus retesty.

**Wynik: 26 zaliczonych, 0 niezaliczonych, 0 zablokowanych**, plan i wyniki w `docs/testing/TODO_042/TEST_PLAN.md`.
Pozostałe testy: backend pytest 152, searcher pytest 169, build frontendu ok, smoke 18 zaliczonych i 4 pominięte.

Cztery płatne runy:

| Run | Rower / element | Czas | Koszt | Wynik |
|---|---|---|---|---|
| Szczegóły | Trek Marlin 5 / Shimano Altus RD-M315 | 40,1 s | 0,10 USD | `found:false` — najpierw kategoria `apparel`, po dodaniu `parts` nadal `found:false`, bo RD-M315 nie jest prawdziwym kodem przerzutki Shimano (rygor zostaje) |
| Zdjęcia | to samo | 46,0 s | — | brak URL strony producenta |
| Szczegóły | Kona El Kahuna / Abus T82 Battery Lock | 54,4 s | 0,17 USD | zapisane jako `equipment` id 4 (`locks`, firma `""`, 8 wierszy specyfikacji, polski krótki opis), link tylko na wierszu tego roweru, ponowne wejście po id bez runu, `/v1/bike/details` zwraca `equipment_id` |
| Zdjęcia | to samo | 106,5 s | 0,36 USD | model zwrócił URL na nieistniejący host `veloconnect-ch.abus.com`, strażnik go odrzucił, nic nie zapisano |

Ścieżka wstawiania zdjęć przeszła tylko w pytest. Znane, niskie ryzyko: przebieg zdjęć na złym hoście potrafi kosztować
ok. 0,36 USD.

**Znaleziska QA naprawione w gałęzi:**

- **Kolejność kategorii** (TC-26): „battery lock” wychodziło jako światła — reguła rzeczownika głównego i `locks` przed `lights`.
- **Sklepy w źródłach** (TC-25): mimo zakazu w prompcie zapisały się ebike24.com, melbournepowered.com.au i
  elanusparts.com. Filtr w kodzie `searcher/app/shop_filter.py` odrzuca hosty marketplace, tokeny sklepowe i ścieżki ofert;
  strona produktu na hoście producenta zostaje. Ponowny zapis przez searcher zostawił Abusa bez źródeł, opis bez zmian.
- **Nieprzetłumaczone „Key type”** — sześć nowych kluczy w `frontend/src/specLabels.ts`.

## 7. Commit i PR

Na dzień pisania tego dokumentu commit i PR jeszcze nie istnieją; lead otwiera PR zaraz po tym dokumencie. Merge i
przeniesienie zadania do `backlog/done/` dopiero po merge'u (merged is the bar).

## 8. Wdrożenie GCP — NIE wykonane

Wdrożenie wyłącznie na wyraźne „go” użytkownika, w tej kolejności:

1. Ręczny backup Cloud SQL `biker-pg`.
2. `migrate_drop_bike_detail.py` z `main` (PR #137), jeśli Cloud SQL jeszcze go nie przeszedł, potem
   `migrate_equipment_tables.py` — oba na Cloud SQL przez proxy, w tej kolejności, przed wszystkim innym.
3. Backend i searcher razem (`scripts/deploy.ps1`) — nowy searcher nie wystartuje bez kolumny `equipment_id`.
4. Frontend.

Okno między krokiem 2 a 3 jest bezpieczne, bo stary backend działa na zmigrowanej bazie (kolumna nullowalna). Zmiana
`--max-instances` niepotrzebna.

**Merge z `main` (2026-10-01).** Po bazie TODO-042 do `main` weszły PR #137 (tabela `bike_detail` usunięta, opis i krótki
opis leżą na `bike`, `bike_detail_component` przekluczone na `bike_id`) i PR #136 (TODO-043, usunięte `search_cache` i
`search_bike_rating_cache`). Gałąź zmergowała `origin/main` i dostosowała się:

- `bike_detail_component.equipment_id` zostaje (nullowalne FK → `equipment.id` `ON DELETE SET NULL`, z indeksem), teraz na
  tabeli kluczowanej `bike_id`. Migawka linków w `save_bike_details` (backend) i `save_details` (searcher) czyta wiersze po
  `bike_id` (`norm(element_name)` → `equipment_id`, pierwszy wygrywa); linkowanie i strażnik „Component not found” też.
- Tabele wyposażenia bez zmian (`equipment`, `equipment_detail`, `equipment_detail_component`, `equipment_detail_photos`).
- `init_db()` searchera sprawdza po kolei: `bike_detail_photos.bike_id`, nowy układ z PR #137 (nazywa
  `migrate_drop_bike_detail.py`), potem `equipment_id` (nazywa `migrate_equipment_tables.py`).
- **Kolejność migracji:** `migrate_drop_bike_detail.py` → `migrate_equipment_tables.py`. Nasz skrypt odmawia (`failed`, kod 1,
  nic nie zapisuje) tabeli wciąż kluczowanej `bike_detail_id`, bo przebudowa SQLite w migracji z `main` ma stałą listę kolumn
  i zgubiłaby wcześniej dodane `equipment_id` (PostgreSQL zmienia tabelę w miejscu i kolumnę zachowuje). Ponowny run naszego
  skryptu dodaje brakującą kolumnę i indeks z powrotem.
- Sprawdzone: świeża kopia `cache.db` — odmowa, migracja z `main` (566 opisów, 31 826 wierszy), `migrate_drop_search_tables.py`,
  nasza migracja `migrated` (31 826 wierszy zachowanych), ponownie `already-migrated`; lokalny `biker-pg` — dry run
  `already-migrated` (32 972 wiersze). Testy: backend 162, searcher 169, webscraper 187, smoke 18 zaliczonych / 4 pominięte.

## 9. Architektura po zmianie

```
frontend (klik w element)  →  backend /v1/equipment/details, /photos   (odczyt z DB)
                              backend /v1/equipment/*/search            (proxy)
                                    │
                                    └─► searcher /v1/search/equipment/*  (claude -p, subskrypcja)
                                              │
                                              └─► Cloud SQL: equipment, equipment_detail,
                                                  equipment_detail_component, equipment_detail_photos,
                                                  bike_detail_component.equipment_id
```

Cztery trasy wyposażenia (2 odczyty z DB, 2 proxy do searchera); `POST /v1/equipment/review` bez zmian.

## 10. Jak tego używać

```bash
# przez searcher
curl -X POST http://localhost:8100/v1/search/equipment/details \
  -H "Content-Type: application/json" -H "X-Searcher-Key: <key>" \
  -d '{"bike_company":"Kona","bike_model":"El Kahuna","element_name":"Abus T82 Battery Lock"}'

# przez backend (tak robi UI)
curl -X POST http://localhost:8000/v1/equipment/details/search \
  -H "Content-Type: application/json" \
  -d '{"bike_company":"Kona","bike_model":"El Kahuna","element_name":"Abus T82 Battery Lock"}'

# smoke testy (bez płatnych runów)
cd backend && python scripts/test_search.py
cd searcher && python scripts/test_searcher.py
```

Migracja przed pierwszym startem na istniejącej bazie: `python scripts/migrate_equipment_tables.py --dry-run`, potem bez
`--dry-run` (szczegóły w `backend/app/DB_MIGRATION.md`).

## 11. Czego nie ma (świadomie)

- **Globalne linkowanie**: element występujący na wielu rowerach nie linkuje się sam; każdy rower ma własny `equipment_id`.
- `POST /v1/equipment/review` zostaje na SDK i generycznym cache — osobne zadanie.
- Liczniki `/v1/bike/missing` dla wyposażenia — `bike_missing_request` liczy per rower, nie per wyposażenie.
- Brak TTL i odświeżania; stare wiersze `/v1/equipment/details` w generycznym cache są martwe (nic ich nie czyta).
- Rygor `found:false`: nieistniejący kod części (RD-M315) nie daje zmyślonych danych — to zamierzone.
- Brak limitu zapytań na anonimowe wyzwalacze searcha (jak w pozostałych trasach `/search`).
- Wyposażenie zachowuje osobny wiersz `equipment_detail` (opis + krótki opis), choć rower po PR #137 trzyma je na `bike`.
  Spłaszczenie `equipment_detail` do `equipment` dla spójności to możliwe zadanie na później, celowo nie w tym merge'u.

## 12. Lekcje

1. **Kategoria domyślna decyduje o jakości.** Przy czterech kategoriach z koszem `apparel` części roweru dostawały prompt
   o odzieży; piąta kategoria `parts` jako domyślna naprawiła to u źródła, a nie w pojedynczych słowach kluczowych.
2. **Reguła „rzeczownik główny” zamiast kolejności kategorii.** „Battery Lock” to zapięcie, „Brake light” to światło;
   QA złapało to dopiero na prawdziwej parze, więc testy ręczne powinny używać nazw z realnych rowerów.
3. **Prompt nie wystarcza jako filtr.** Model zapisał sklepy mimo wyraźnego zakazu; zakaz musi mieć też strażnika w kodzie.
4. **Izolowana baza QA** (`biker_qa042`) uchroniła testy przed przebudowaną wspólną bazą innego worktree.
5. **Przed rozdaniem pracy sprawdzić żywych agentów** — agent z poprzedniej sesji zdążył edytować plik searchera.
6. **Dwa przeglądy o różnych soczewkach** (poprawność i bezpieczeństwo) znalazły inne klasy błędów; oba były warte kosztu.
