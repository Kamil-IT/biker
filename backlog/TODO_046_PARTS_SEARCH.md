# TODO-046 — Zakładka „Wyszukiwanie części” (katalog części)

**Branch:** `feature/todo-046-parts-search`
**Status:** zaimplementowane, PR otwarty — czeka na review, merge i deploy (nie mergować, nie deployować i nie migrować Cloud SQL bez wyraźnej zgody użytkownika)
**Makieta:** `docs/mockups/wyszukiwanie-czesci/wyszukiwanie-czesci.html` (linkuje `../zakladki/styles.css`; przełącznik stanów w prawym dolnym rogu: start, po parsowaniu, wyniki z bazy, 0 w bazie → karta, klik → AI szuka, wyniki z AI, AI też nic, nie rozpoznano)

## Cel (wywiad z użytkownikiem odbył się przed zadaniem — decyzje potwierdzone)

Nowa zakładka **„Wyszukiwanie części”** w `TopTabs`, **między „Rower na Twoją miarę” a „Kontakt”**.
Adres `/parts` (start) i `/parts?q=…&type=…&brand=…&model=…&group=…` (wyniki).

- Tryb **katalogu części**: użytkownik przegląda części po typie, marce, modelu i grupie osprzętu, **bez** podawania swojego roweru.
- **Filtry** (panel „Filtry” jak w wyszukiwarce rowerów): typ części, marka, model, grupa osprzętu. **Bez parametrów zależnych od typu** (rzędowość, mocowanie tarczy — usunięte przez użytkownika, na razie niepotrzebne).
- **Typy części (12, slug → etykieta):** `cassette` Kaseta, `chain` Łańcuch, `rear_derailleur` Przerzutka tylna, `shifter` Manetka, `crankset` Korba, `bottom_bracket` Suport, `brake` Hamulec, `rotor` Tarcza hamulcowa, `tyre` Opona, `wheel` Koło, `cockpit` Kierownica / mostek, `seat` Siodło / sztyca. Bez kasków, oświetlenia, zapięć, odzieży, widelców i amortyzatorów.
- **Parsowanie tekstu identyczne jak w wyszukiwarce rowerów:** sam tekst bez filtrów → parse wypełnia panel filtrów, wyszukiwanie czeka na drugie „Szukaj części”. Te same reguły `parsedQueryRef` co w `App.tsx` `handleSearch`: zmieniony tekst czyści filtry i parsuje od nowa, niezmieniony od razu szuka. Parse → 400 → komunikat nad polem „Nie znaleziono: Nie mamy tej części w naszej bazie”, wyszukiwanie nie rusza.
- **Baza = wyłącznie tabela `equipment`** (nie `bike_component`). Wyszukiwanie w bazie nie woła AI.
- **AI tylko na kliknięcie, nigdy automatycznie.** Gdy lista jest pusta (baza 0 albo AI 0), pod nagłówkiem „Nie znaleźliśmy żadnej części” jest karta „Nie ma tu tego, czego szukasz?” / „Przeszukamy sieć i dopiszemy nowe części do katalogu. To potrwa do ok. 40 s.” / przycisk **„Szukaj więcej z AI”**. Karta **tylko przy 0 częściach**, nigdy pod wynikami. Po kliknięciu spinner „Szukam w sieci…” i szkielety kafelków; błąd → alert, przycisk znów klikalny.
- **AI = Haiku w backendzie + `web_search`** (jak `app/equipment_review_finder.py`: `web_search_20250305`, ten sam model). AI zwraca markę, model, typ, grupę i kluczowe parametry; **wiersz `equipment` zapisujemy razem z parametrami**, więc następne podobne zapytanie trafia do bazy.
- **Wyniki:** kafelki „Kadr” jak `ResultCard` (kadr 4:3), **bez tabliczki i paska oceny eksperta**. Linia „Marka · Typ”, model jako nagłówek, chipy z kluczowych parametrów, krótki opis albo „Nie mamy jeszcze opisu tej części.”, znacznik **„Nowe z AI”** na częściach dodanych w tym wyszukiwaniu. Sortowanie tylko „Nazwa: A–Z / Z–A” (marka, potem model, `Intl.Collator('pl')`, numeric), select tylko przy 2+ wynikach. Klik → `/equipment/{id}` (istniejący widok); „Wróć do wyników” → z powrotem do `/parts?…`.
- **Zdjęcia tylko po kliknięciu**, jak przy rowerach: kafelek bez zdjęcia ma rysunek i „Brak zdjęcia. Poproś o nie w szczegółach części.”; zdjęcie pobiera istniejący przycisk „Poproś o dane” w galerii widoku części (searcher). Kafelek pokazuje pierwsze (użyteczne) zdjęcie z `equipment_detail_photos` na tle `#FFFFFF` (ta tabela nie ma `bg_color`). Żadnego automatycznego wyszukiwania zdjęć.

## Poza zakresem

Parametry/standardy w filtrach, dopasowanie do roweru użytkownika, ceny i oferty, kategorie inne niż części, ocena eksperta na kafelkach, automatyczne AI i automatyczne zdjęcia, limit zapytań na IP, deploy i zmiany w Cloud SQL (tylko na wyraźne „go” użytkownika).

## Backend

### Dane — `equipment` (`app/equipment_models.py`), trzy kolumny nullable

| Kolumna | Typ | Znaczenie |
|---|---|---|
| `part_type` | `VARCHAR(32)` | slug z listy 12 typów (`app/part_types.py`); NULL = nieznany (np. wiersz z kliknięcia w specyfikacji roweru) |
| `groupset` | `VARCHAR(128)` | grupa osprzętu / linia produktu |
| `key_specs` | `TEXT` | JSON lista ≤ 6 krótkich napisów na chipy (≤ 40 znaków), np. `["12 rz.", "10-51T", "Micro Spline"]` |

**Nie zapisujemy parametrów do `equipment_component`** — widok części (`useEquipment.ts`, `hasDetails`) startuje wyszukiwanie szczegółów automatycznie tylko wtedy, gdy nie ma ani opisu, ani komponentów; komponenty od AI by je zablokowały.

Migracja `backend/scripts/migrate_equipment_part_search.py` (wzorzec `migrate_photo_bg_color.py`): SQLite i PostgreSQL, jedna transakcja, liczba wierszy zweryfikowana, idempotentna (`already-migrated`), `--dry-run`, `--db`, `--url`, importowalne `migrate(url_or_path=None, dry_run=False, verbose=True) -> dict`; test `scripts/test_migrate_equipment_part_search.py`. Dosłowna kopia DDL w `searcher/app/models.py` (najpierw backend, potem kopia); searcher nie wystartuje bez kolumn.

### Endpointy (`app/parts_routes.py`, schematy w `app/schemas.py`)

1. `POST /v1/parts/parse` `{text}` (1–500) → `{part_type, brand, model, groupset}` — Haiku bez narzędzi, prompt `app/prompts/parts_parse.md` (wzór `bike_parse.md`), generic cache tylko na szczęśliwej ścieżce; pusty wynik → **400** `"Part not available in our database"`, także na trafieniu z cache, nigdy nie cache'owany.
2. `POST /v1/parts/search` `{search?, part_type?, brand?, model?, groupset?}` (≥ 1 pole; 500/32/255/255/128; `part_type` z enumu) → `{search, parts: [PartResult]}` — **tylko odczyt z bazy**, bez AI i generic cache. Wiersze `category='parts'`; każde podane pole musi pasować: `part_type` równość; `brand` równość z `company_norm`, a gdy `company` pusty — `name_norm` zaczyna się od marki (całe słowo); `model` podciąg `model_norm` lub `name_norm`; `groupset` podciąg; `search` niesprawdzany. Normalizacja w Pythonie (`models.norm()`). Sortowanie: marka, model. `PartResult = {id, part_type, brand, model, name, groupset, key_specs, short_description, photo, is_new}`; `photo` = pierwsze użyteczne zdjęcie (`display_order, id`; filtr śmieci jak na kafelkach rowerów) jednym zapytaniem dla całej listy.
3. `POST /v1/parts/search/ai` (to samo body) → `{search, parts}` — **jedno** wywołanie Haiku + `web_search` (`max_uses` 4), prompt `app/prompts/parts_search.md`; JSON ≤ 10 części `{brand, model, part_type, groupset|null, key_specs[≤6]}`, tylko realne produkty (nie oferty sklepów), `extract_json()`; zły JSON → `parts: []`, nigdy 502. Walidacja: `part_type` z enumu (inny typ niż zapytany → odrzucony), napisy przycięte do długości kolumn, chipy ≤ 40 znaków. Zapis: `category='parts'`, `name` = „Marka Model”, `company`/`model` z AI, `INSERT … ON CONFLICT DO NOTHING` na `uq_equipment_name`; istniejący wiersz (ten sam `name_norm` albo para `company_norm` + `model_norm`) dostaje **tylko brakujące** `part_type`/`groupset`/`key_specs`. `is_new: true` dla wierszy utworzonych w tym wywołaniu. **Bez generic cache** (wynik to dane). Single-flight na znormalizowane zapytanie. Anthropic 400 → 400 (handler aplikacji).

### Widok części bez roweru

- `app/equipment_lookup.py` `search_context`: część (`category='parts'`), której nie linkuje żaden rower, dostaje kontekst **bez roweru** (zamiast 404 „Component not found”; inne kategorie bez roweru — nadal 404, po code review); `element_type` = angielska nazwa typu części (np. „Cassette”). 404 „Equipment not found” zostaje.
- `searcher_client` wysyła `bike_company`/`bike_model` tylko, gdy są.
- Searcher: `EquipmentSearchRequest` — rower opcjonalny (oba albo żaden); `user_message` obu finderów i `is_named_after_bike` działają bez roweru (prompt bez kontekstu roweru); `_link` pomijany bez roweru; zapis dalej po `(category, element_name)`.

## Frontend

- `TopTabs.tsx`: zakładka `parts` „Wyszukiwanie części”; poniżej 640 px krótkie etykiety „Na miarę” i „Części” (rząd mieści się od 360 px). Aktywna na `/parts` i na `/equipment/{id}` otwartym z `/parts` (także dla części bez roweru otwartej z linku).
- `useRoute.ts`: `PATHS.parts`, trasa `{name: 'parts', query}`, `partsPath(query)`; `partsQuery.ts` (parametry `q`, `type`, `brand`, `model`, `group`, kanoniczna kolejność, nieznane parametry i typy spoza enumu odrzucane).
- Nowe pliki: `PartsSearchPage.tsx`, `PartsSearchInput.tsx`, `PartCard.tsx` (wspólny kadr `TileStage.tsx` z `ResultCard`), `AiSearchCard.tsx`, `hooks/usePartsSearch.ts`, `partTypes.ts`, `sortParts.ts`.
- Zachowanie jak w wyszukiwarce rowerów: adres zmienia się dopiero, gdy wyszukiwanie rusza (każde to nowy wpis w historii); adres z linku (F5, nowa karta) wypełnia formularz i szuka od razu, bez parse; Back z części do `/parts?…` pokazuje te same wyniki bez nowego zapytania (razem z dopisanymi przez AI); odpowiedź na nieaktualne zapytanie odrzucana; `document.title` = „Wyszukiwanie części — Biker”.
- Widok części: gdy `from` to `/parts?…`, „Wróć do wyników” robi `goBack` do tego adresu.

## Testy, bezpieczeństwo, dokumentacja

- `backend/scripts/test_search.py`: `case_parts_search` (bez API); `case_parts_parse` i `case_parts_search_ai` tylko z `--ai`.
- Pytest: `scripts/test_parts_repository.py`, `scripts/test_migrate_equipment_part_search.py`, kontekst bez roweru w `test_equipment_repository.py`, ciało bez roweru w `test_searcher_client_equipment.py`; searcher `scripts/test_equipment_catalogue.py` (bez płatnego przebiegu).
- `/sparc-security-review`: tekst użytkownika w promptach Haiku (limity długości, tekst jako dane — JSON w `<query>`), przycinanie odpowiedzi AI. **Ryzyko:** przycisk AI to płatne wywołanie API dostępne anonimowo, bez limitu na IP.
- Dokumentacja: `backend/README.md` § Endpoints, `searcher/README.md`, `frontend/README.md`, `README.md`, `CLAUDE.md`, `backend/app/DB_MIGRATION.md`.
- Ręczne QA: `docs/testing/TODO_046/TEST_PLAN.md`.

## Wdrożenie (tylko po „go” użytkownika)

1. Backup Cloud SQL (on-demand).
2. `migrate_equipment_part_search.py` na Cloud SQL przez proxy.
3. Backend + searcher razem (nowy searcher nie wystartuje bez kolumn; stary backend i searcher działają na zmigrowanej bazie — kolumny nullable).
4. Frontend.

## Przegląd bezpieczeństwa (`/sparc-security-review`, 2026-10-07)

Pen-testy na lokalnym backendzie (worktree, port 8003): **20/20**. Klucz API nie pojawia się w logach ani odpowiedziach.

- **Walidacja wejścia:** wszystkie pola z limitami (tekst 500, marka/model 255, grupa 128, `part_type` z enumu — także wielkość liter); puste / same spacje → 422. Wartości w kształcie SQL injection, `%`/`_`, bajt NUL i wielkie litery spoza ASCII są zwykłymi danymi (dopasowanie w Pythonie, ORM z parametrami) → 200, nic nie pasuje.
- **Prompt injection:** w `/v1/parts/search/ai` zapytanie trafia do Haiku jako obiekt JSON w znacznikach `<query>` (cudzysłów ani nowa linia nie zamkną znacznika), prompt mówi, że pola to dane. W `/v1/parts/parse` tekst idzie jako treść wiadomości (jak `/v1/bike/parse`), ale odpowiedź jest twardo walidowana (enum typu, długości) i trafia tylko do pytającego (cache po jego własnym tekście).
- **Odpowiedzi AI:** przycinane do szerokości kolumn, ≤ 10 części, ≤ 6 chipów po ≤ 40 znaków, typ spoza enumu odrzucany, część innego typu niż zapytany odrzucana; React escapuje cały tekst (brak `dangerouslySetInnerHTML`), kafelki nie mają zewnętrznych linków.
- **Poprawione w przeglądzie:** (1) jawne timeouty wywołań Haiku — parse 30 s, wyszukiwanie AI 120 s (wcześniej domyślne 10 min SDK); (2) `/v1/parts/search` z samym tekstem zwracało cały katalog — teraz `[]` bez odczytu bazy (jak krok bazy w wyszukiwarce rowerów), więc UI proponuje wyszukiwanie AI.
- **Błędy:** zły JSON od modelu → 200 `parts: []`; błąd API → 502 `Upstream error: …` (jak `/v1/bike/search`); Anthropic 400 (brak kredytów) → 400 z komunikatem Anthropic; błąd zapisu → 503.

**Ryzyka zaakceptowane / do decyzji użytkownika:**
- **Przycisk „Szukaj więcej z AI” to płatne wywołanie API (Haiku + `web_search`) dostępne anonimowo, bez limitu na IP.** Single-flight łączy tylko identyczne zapytania; różne zapytania płacą osobno, bez globalnego limitu współbieżności. Odpowiedzią jest planowany limit na IP (krok 2 deployu) — poza zakresem tego zadania.
- **Zatrucie katalogu:** wyniki AI (także pod wpływem treści stron z `web_search`) zapisują się w współdzielonej tabeli `equipment` i są widoczne dla innych. Ograniczenia: walidacja jak wyżej, „tylko brakujące” — nic istniejącego nie jest nadpisywane.
- **Wyszukiwanie szczegółów / zdjęć części bez roweru:** element kategorii `parts` bez linku do roweru (część z katalogu) jest teraz szukany przez searcher (inne kategorie bez roweru — nadal 404) (płatny przebieg subskrypcji) zamiast 404. Wiersz musi istnieć (id), a nazwa pochodzi z bazy, nie od wywołującego; searcher czyści ją `prompt_value` i traktuje jako dane. Każdy istniejący id można było już wcześniej szukać, o ile linkował go rower.
