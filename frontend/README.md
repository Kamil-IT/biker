# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

## Application overview

**Top tabs (TODO-041).** Under the BIKER wordmark the header carries a tab row (`components/TopTabs.tsx`): **Szukanie rowerów** `/`, **Rower na Twoją miarę** `/rower-na-twoja-miare`, **Kontakt** `/kontakt`. There is no router library: `hooks/useRoute.ts` reads `location.pathname` (an unknown path or a trailing slash is rewritten to the known path, unknown = `/`), pushes history entries on a tab click, listens to `popstate` (back/forward) and sets `document.title` per tab; nginx's SPA fallback and Vite already serve `index.html` for deep links. The tabs are plain `<a href>` links (a modified or middle click opens a new browser tab) with `aria-current="page"` and a terracotta bar on the active one. The search flow below stays mounted inside `App`, so leaving for another tab and coming back keeps the results; clicking **Szukanie rowerów** from the details or equipment view goes back to the result list (`handleBackToResults`), and the BIKER wordmark resets the search and returns to `/`. `components/FitComingSoonPage.tsx` is a "Wkrótce" teaser for the AI bike fitter (SVG sketch with a `.scan` sweep from `index.css`, hidden under `prefers-reduced-motion`); `components/ContactPage.tsx` is a contact form shown **disabled** with a "wkrótce" notice — there is no contact backend, nothing is sent. Approved mockups: `docs/mockups/zakladki/`.

On `/` the SPA has three views, switched by `App.tsx` state:

**UI language: Polish.** Every user-visible string (labels, buttons, placeholders, `aria-label`s, error messages, `index.html` title/description, `lang="pl"`) is Polish, hard-coded in the components (no i18n library). Filter `<select>`s keep their **English `value`s** — only the `label` is translated (`SearchInput.tsx` `Option { value, label }`), because the backend matches those values against its English data. Content returned by the backend (explanations, reviews, spec **values**, component names) is shown as-is — except the spec-tree **labels**: category, subcategory and spec-key names are translated at display time by `src/specLabels.ts` `translateLabel()` (case-insensitive dictionary, plus `Front …` / `Rear …` / `Max …` prefixes and a trailing `(…)` qualifier such as `Weight (Size M)` → `Waga (rozmiar M)`; unknown labels fall back to the English original). `CategorySection` in `BikeDetailsShared.tsx` applies it, so it covers both the bike and equipment views; the element-name link still passes the untranslated name to the equipment view. The English UI names below (e.g. "Request data") are the pre-translation names used in task files; on screen they read "Poproś o dane", "Nie mamy jeszcze tych danych", "Zgłoszono ✓", "Szukam na OLX…", "Szukam na Allegro i Decathlon…", "Szukam zdjęć…", "Szukam recenzji…", "Szukam danych roweru…", "Nie znaleziono ofert", "Nie znaleziono zdjęć", "Nie znaleziono recenzji", "Nie znaleziono danych", "Nie znaleziono", "Czytaj recenzję", "Źródła", "Używane" / "Nowe"; on the home page "Najpopularniejsze rowery", "Ocena eksperta", "Brak oceny".

- **Home page (TODO-034)** — before the first search, the search view shows a "Najpopularniejsze rowery" section under the form: `GET /v1/bike/popular` is fetched **once** on app load by `hooks/usePopularBikes.ts` and kept for the app's lifetime (coming back from the details view does not refetch), and for every bike the hook fires its own `POST /v1/bike/review` — all in parallel, each card settling on its own. `PopularBikesSection.tsx` renders the results section's container and eyebrow with one `ResultCard` per bike in its **popular look** (`expertRating` prop, same layout as the search results): the expert `rating` in the numeral slot ("8.4" over "/ 10"; "—" while pending; "?" + "Brak oceny" when the review call failed, answered non-OK or returned `rating` 0), the stored description in the explanation slot, the bar label "Ocena eksperta" ("Ocena eksperta…" while pending) with the bar filled to `rating × 10 %`, the rank "#n", and **no** "Najlepsze dopasowanie" badge, accessories chips or percentage. The section is rendered only while no search is running and no results are shown (`appState` idle or error) — it disappears on submit and returns after "Nowe wyszukiwanie" / the header reset / a return from the details view with no results; an empty or failed `/v1/bike/popular` simply hides it (no error UI). A click calls the same `handleBikeSelect` as a search result with `{ brand, model, accessories: [], explanation: description }`, so the details view opens unchanged.
- **Search** — `SearchInput` (free text + collapsible filters) → `POST /v1/bike/search`, rendered as `ResultCard`s — as many as the backend returns (no fixed count; 3 neutral `LoadingCard` skeletons while loading). An empty `bikes: []` (backend parse failure) shows a "Not found" message in the results section. **Expert rating (TODO-040):** every result card shows the bike's expert rating instead of a match score — `hooks/useCachedRatings.ts` fires one `POST /v1/bike/review` per result bike, all in parallel (stored reviews in the `bike_review` table only, no AI), and publishes all ratings together when the last one returns. The numeral is the rating ("8.4" over "/ 10"), **"—"** while the answer is pending and **"?"** when the bike has no stored review (or the call failed); the bar reads "Ocena eksperta" ("Ocena eksperta…" / "Brak oceny") and fills to `rating × 10 %`. Cards keep the backend order until every rating has settled, then the list is sorted by rating descending with unrated bikes last (stable). **Explanation and chips (TODO-041):** the card's paragraph is the bike's stored short description and its chips are drivetrain / brakes / frame-material names computed by the backend from stored components; `ResultCard` renders each **only when non-empty**, so a bike without stored details (typical for an AI-found bike) shows neither. There is no "Najlepsze dopasowanie" badge, no percentage and no "Dopasowanie" block in the details header any more. `bikeKey` / `PENDING_RATING` / `NO_RATING` are shared in `src/ratings.ts`.
  **Free text → filters:** a submit with free text and no filters set first calls `POST /v1/bike/parse` and fills the Filters panel from the result, then waits for a second submit. `App.tsx` keeps the parsed text in a `parsedQueryRef`, so **any later submit whose search text differs from it clears every filter first** (`EMPTY_FILTERS`, manual ones included), sends only `{ search }` and parses the new text — typing a different bike can never search with the previous bike's brand/model still in the panel. A submit with the text unchanged does not parse again; it searches with whatever the filters hold, so a filter tweaked by hand still applies. Resetting the app ("BIKER" in the header, "new search" in the results) clears that memory as well, so the same text parses again after a reset.
- **Bike details** (`BikeDetailsView`) — photo gallery, overview, pooled offers (Allegro / Decathlon / OLX), expert review, and a component spec tree. Each **component name in the spec tree is a link** that opens the equipment view for that item (the "Key features" chips stay as plain tags).
  **Request data (TODO-027):** each section — photos, overview, spec tree, expert review, and the Used / New offer cards — shows its loading state for 5 s. If it still has no data then (or its response was empty or failed), a shared `RequestDataButton` takes its place: "We don't have this data yet" + **Request data**. The request keeps running, and data that arrives later replaces the button. A click sends `POST /v1/bike/missing` with the section's `MissingType` (`photos` / `description` / `components` / `review` / `offers_new` / `offers_used`) and turns the button into a disabled "Requested ✓"; a failed POST makes it clickable again. The state is component-only (no `localStorage`). The offers section no longer disappears when both lists are empty — each card shows its own button. The equipment view has no such button.
  **On-demand OLX search (TODO-031):** the **Used** card's button does one thing more. After recording the click it calls `POST /v1/bike/used/search` (`App.tsx` `searchUsedBikes`, passed down as `onSearchUsed` → `RequestDataButton`'s optional `onRequested` prop with `pendingLabel="Szukam na OLX…"`) and shows a spinner + "Szukam na OLX…" while the searcher runs. Offers that come back go into the `usedBikes` state, so the card renders the rows and the button unmounts; if the search finishes with no offers the button becomes a disabled "Nie znaleziono ofert" (same outline style as "Requested ✓"); if the call fails (503 searcher unavailable, 502 searcher error, network) it returns to a clickable "Request data". A failed `/v1/bike/missing` POST does not stop the search — the counter is secondary. The `usedBikeState` is not flipped to `loading` during the search, so the 5 s skeleton grace of the offers section does not restart. The automatic `POST /v1/bike/used/olx` on opening the details view is unchanged (it is now a fast DB read on the backend). Every other `RequestDataButton` usage (no `onRequested`) keeps the TODO-027 behaviour.
  **On-demand Decathlon + Allegro search (TODO-032 / TODO-033):** the **New** card's button works the same way, but runs **two searches at once**. After recording the click (`offers_new`) it calls `POST /v1/bike/decathlon/search` **and** `POST /v1/bike/allegro/search` concurrently (`App.tsx` `searchNew` = `Promise.allSettled([searchDecathlon, searchAllegro])`, passed down as `onSearchNew` → the New `OfferCategoryCard`'s `onRequested` with `pendingLabel="Szukam na Allegro i Decathlon…"`) and shows a spinner + "Szukam na Allegro i Decathlon…" while the searchers run. Each search writes its own state the moment it returns — Decathlon rows into `decathlonOffers`, Allegro rows into `offers` — so rows from **either** source replace the button as they arrive, without waiting for the other. `is_new` comes from the listing (Decathlon: true unless outlet/refurbished; Allegro: false unless the listing says new), so a Decathlon row normally lands in the New card while an Allegro row lands in New **or** Used by its flag. `searchNew` resolves once both have settled: both empty → disabled "Nie znaleziono ofert"; it rejects — clickable again, with the first failure's `detail` — when a call failed (503 / 502 / network) and **neither** brought rows: both failed, or one failed while the other came back empty (for a non-Decathlon brand Decathlon is always instantly empty, so an Allegro 503 busy must not read as "no offers"); a failure next to real rows from the other source is swallowed, the rows are on screen. An Allegro offer with no visible price (`price: ""`) renders "cena w ofercie" instead of a price. While **either** source already has a stored row (`hasNewSourceRows`: any decathlon.pl or allegro.pl row, even one that sits in the Used card) the New card's button is the plain counter click, never a second paid pair of runs. For a brand Decathlon does not sell (anything but its house brands: Rockrider, Btwin, Triban, Van Rysel, Elops, Riverside, Stilus, Tilt, Decathlon) the backend answers the Decathlon call instantly with no offers and no searcher run, so only the Allegro search actually runs. Neither `decathlonState` nor `offerState` is flipped to `loading` during the search, for the same reason as above. The automatic `POST /v1/bike/decathlon` and `POST /v1/bike/allegro` on opening the details view are unchanged in shape but are now fast DB reads of the stored decathlon.pl / allegro.pl offers (empty until a search has run); `App.tsx` reads all three stored sources through one `fetchStoredOffers` helper.
  **Photos (own DB read + on-demand search):** the gallery no longer comes from `/v1/bike/details` — `BikeDetailsResponse` has no `photos` field. On opening the details view `App.tsx` sends `POST /v1/bike/photos` (through the same `fetchStoredOffers` helper as the stored offers, into `bikePhotos` / `photosState`), a fast DB read independent of the details request, so photos show even when `/v1/bike/details` is slow or fails. The gallery renders the URLs in the returned order and has its own 5 s loading grace (`photosState`, not `detailsState`). An empty list shows the photos `RequestDataButton` (`MissingType.photos`) with `onRequested={onSearchPhotos}`, `pendingLabel="Szukam zdjęć…"` and `emptyLabel="Nie znaleziono zdjęć"`: the click records the request, then `searchPhotos` sends `POST /v1/bike/photos/search`; returned photos go into `bikePhotos` and replace the button, an empty answer leaves a disabled "Nie znaleziono zdjęć", a failure (404 / 503 / 502 / network) makes the button clickable again. `photosState` is not flipped to `loading` during the search, and a result that arrives after another bike was opened is dropped (`selectedBikeRef`). `RequestDataButton`'s `emptyLabel` prop defaults to "Nie znaleziono ofert", so the offer cards are unchanged. The equipment view still takes its photos from `/v1/equipment/details`.

  **Description + components (own DB read + on-demand search, TODO-041):** `POST /v1/bike/details` is now a fast DB read of the stored details; with nothing stored it answers 200 with an empty description text and `components: []` (and `short_description: ""`), which the view treats as no data — not an error — so after the 5 s loading grace the **Opis** and **Komponenty** sections show their `RequestDataButton` (`MissingType.description` / `MissingType.components`). Both buttons share **one** on-demand details search and watch the same promise: they each get the **one shared** `onRequested={onSearchDetails}` (only while both sections are empty; otherwise the click is a plain counter click) and the **same** `watch` promise. A click on either button triggers one `searchDetails` run, the clicked button's `onRequested` fires it, and both buttons show `pendingLabel="Szukam danych roweru…"` while the promise is pending (`watch` prop). The click records the request, then `searchDetails` in `App.tsx` sends `POST /v1/bike/details/search` (the paid searcher run, ~1–2.5 min, only on click, never automatic) through `postOnDemandSearch`; the answer goes into `bikeCategories` / `bikeDescription` (`detailsState` → `loaded`, not flipped to `loading` during the search) and fills **both** sections, an empty answer leaves both buttons disabled "Nie znaleziono danych", a failure (404 / 503 / 502 / network) makes both buttons clickable again, and a result that arrives after another bike was opened is dropped (`selectedBikeRef`).
  **Expert review (own DB read + on-demand search, TODO-037):** `POST /v1/bike/review` is now a fast DB read of the stored review; with nothing stored it answers 200 `{ score: 0, explanation: "", ref: [], rating: 0, sources_used: 0 }`, which `hasReview` (`ref` empty **and** `sources_used` 0) treats as no data, so after its 5 s loading grace the section shows the review `RequestDataButton` (`MissingType.review`) with `onRequested={onSearchReview}`, `pendingLabel="Szukam recenzji…"` and `emptyLabel="Nie znaleziono recenzji"`. The click records the request, then `searchReview` in `App.tsx` sends `POST /v1/bike/review/search` (the paid searcher run, ~1 min); a found review goes into `review` (`reviewState` → `loaded`) and replaces the button, an empty answer leaves a disabled "Nie znaleziono recenzji", a failure (404 / 503 / 502 / network) makes the button clickable again. `reviewState` is not flipped to `loading` during the search, and a result that arrives after another bike was opened is dropped (`selectedBikeRef`). The home page keeps calling `POST /v1/bike/review` and reads the empty answer's `rating` 0 as "Brak oceny". The equipment view's review (`/v1/equipment/review`) is unchanged and has no button.
- **Equipment details** (`EquipmentDetailsView`) — the gear counterpart: category eyebrow, overview, expert review, and a component spec tree. **No offers/buy links** — equipment is informational only.

`BikeDetailsView` and `EquipmentDetailsView` share their building blocks (`PhotoGallery`, `DescriptionCard`, `ReviewSection`, `LoadingSkeleton`, `CategorySection`) from `components/BikeDetailsShared.tsx`. The overview renders its sources as **citation footnote chips** (`components/CitationChips.tsx`) — a "Sources" row of terracotta pill links showing each source's domain, opening in a new tab with the full URL as a hover tooltip. The expert review renders its sources as a **full-width source table** below the explanation instead: one row per URL, `stars | domain | "Read review →"`, each row an external link with the full URL as a hover tooltip. The stars are decorative, mapped 0–10 → 1–5 from the aggregate `rating` where one exists.

### Docker

`frontend/Dockerfile` builds the bundle (node 24) and serves it from nginx. `nginx.conf.template` is rendered by the image's
envsubst entrypoint at start (only `PORT` and `BACKEND_URL` are substituted, `NGINX_ENVSUBST_FILTER`): SPA fallback plus
`/v1/*` proxied to `BACKEND_URL` — the same routing Vite does in dev. The Dockerfile defaults (`PORT=8080`,
`BACKEND_URL=http://backend:8000`) serve the root `docker-compose.yml`; on Cloud Run `scripts/deploy.ps1` sets `BACKEND_URL`
to the backend service's https URL. The proxy sends the backend's own hostname as `Host` (Cloud Run routes by it) with SNI
on, and keeps the 600 s read timeout for the on-demand searches (`/v1/bike/details/search` and the other `*/search` routes).

### API integration (all proxied via Vite `/v1` → backend on :8000)

| Call | Request | Response |
|------|---------|----------|
| `POST /v1/bike/search` | `SearchPayload` | `{ search, bikes[] }` |
| `GET /v1/bike/popular` | — | `PopularBikesResponse` `{ bikes: [{ brand, model, description }] }` — the curated home-page list, already ordered (DB read, no AI, TODO-034); fetched once on app load by `usePopularBikes`; `{ bikes: [] }`, a non-OK answer or a network error just hides the section |
| `POST /v1/bike/details` | `{ company, model }` | `BikeDetailsResponse` (overview + component tree + `short_description` — no photos) — the stored details, a fast DB read (TODO-041); nothing stored → empty description text, `components: []`, `short_description: ""`, shown as the Opis / Komponenty "Request data" buttons |
| `POST /v1/bike/details/search` | `{ company, model }` | `BikeDetailsResponse` — on-demand details search via the searcher service (TODO-041), triggered only by the Opis / Komponenty "Request data" buttons (one shared run fills both); empty result = "Nie znaleziono danych"; 404 when the bike is unknown, 503 when the searcher is not configured/reachable/busy, 502 when it fails |
| `POST /v1/bike/photos` | `{ company, model }` | `BikePhotosResponse` `{ photos }` — stored photo URLs in display order (DB read, no AI), sent on opening the details view; `{ photos: [] }` until the on-demand search below has run |
| `POST /v1/bike/review` | `{ company, model }` | `BikeReviewResponse` — the stored review, a fast DB read (TODO-037); nothing stored → `{ score: 0, explanation: "", ref: [], rating: 0, sources_used: 0 }`, shown as the Review section's "Request data" button. Also sent once per popular bike on the home page (TODO-034) and once per search-result bike (TODO-040, `useCachedRatings`, in parallel) for the card's expert `rating`; there a non-OK / failed answer or `rating` 0 reads as "Brak oceny" |
| `POST /v1/bike/allegro` | `{ company, model }` | `BikeOfferResponse` `{ offers, info }` — stored allegro.pl offers only (DB read, no AI, TODO-033; `photos` is always `[]` — the Allegro search stores none); empty until the on-demand search below has run |
| `POST /v1/bike/decathlon` | `{ company, model }` | `BikeOfferResponse` `{ offers, info }` — stored decathlon.pl offers only (DB read, no AI); empty until the on-demand search below has run |
| `POST /v1/bike/used/olx` | `{ company, model }` | `UsedBikeResponse` `{ offers, info }` — stored OLX listings only (DB read, no AI); empty until the on-demand search below has run |
| `POST /v1/bike/missing` | `MissingDataRequest` `{ company, model, missing_type }` | `MissingDataResponse` `{ bike_id, missing_type, counter }` (sent by `RequestDataButton`) |
| `POST /v1/bike/used/search` | `{ company, model }` | `UsedBikeResponse` `{ offers, info }` — on-demand OLX search via the searcher service (TODO-031), triggered only by the Used card's "Request data" button; 503 when the searcher is not configured/reachable/busy, 502 when it fails |
| `POST /v1/bike/decathlon/search` | `{ company, model }` | `BikeOfferResponse` `{ offers, info }` — on-demand Decathlon search via the same searcher service (TODO-032), triggered only by the New card's "Request data" button; a non-Decathlon brand answers 200 with `offers: []` and a Polish `info` at once (no searcher call); 404 when the bike is unknown, 503 when the searcher is not configured/reachable/busy, 502 when it fails |
| `POST /v1/bike/allegro/search` | `{ company, model }` | `BikeOfferResponse` `{ offers, info }` — on-demand Allegro search via the same searcher service (TODO-033), sent by the New card's "Request data" button together with `/v1/bike/decathlon/search` (both at once); returned offers carry no photos (`photos: []` by design — allegro.pl blocks every automated fetch, so the searcher scrapes none) and `is_new` from the listing (used unless it says new); 404 when the bike is unknown, 503 when the searcher is not configured/reachable/busy, 502 when it fails |
| `POST /v1/bike/photos/search` | `{ company, model }` | `BikePhotosResponse` `{ photos }` — on-demand photo search via the searcher service, triggered only by the gallery's "Request data" button; 404 when the bike is unknown, 503 when the searcher is not configured/reachable/busy, 502 when it fails |
| `POST /v1/bike/review/search` | `{ company, model }` | `BikeReviewResponse` — on-demand review search via the searcher service (TODO-037), triggered only by the Review section's "Request data" button; empty `ref` / `sources_used` 0 = nothing found; 404 when the bike is unknown, 503 when the searcher is not configured/reachable/busy, 502 when it fails |

`BikeReviewResponse` also carries an aggregate `rating` (0–10, weighted across curated review sources) and `sources_used` count; `ReviewSection` does not display the aggregate rating itself — it only derives the source-table stars from `rating`. Equipment reviews carry neither field, so they fall back to `score` for the stars.
| `POST /v1/equipment/details` | `{ company?, model, category? }` | `EquipmentDetailsResponse` (overview, component tree, photos — no offers) |
| `POST /v1/equipment/review` | `{ company?, model }` | `EquipmentReviewResponse` (`score`, `explanation`, `ref[]` — review/forum links only) |

Equipment lookups are entered by clicking a component name in a bike's spec tree; the component name is sent as `model` (no `company`), and the backend infers the equipment `category`.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

```js
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...

      // Remove tseslint.configs.recommended and replace with this
      tseslint.configs.recommendedTypeChecked,
      // Alternatively, use this for stricter rules
      tseslint.configs.strictTypeChecked,
      // Optionally, add this for stylistic rules
      tseslint.configs.stylisticTypeChecked,

      // Other configs...
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```

You can also install [eslint-plugin-react-x](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-x) and [eslint-plugin-react-dom](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-dom) for React-specific lint rules:

```js
// eslint.config.js
import reactX from 'eslint-plugin-react-x'
import reactDom from 'eslint-plugin-react-dom'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...
      // Enable lint rules for React
      reactX.configs['recommended-typescript'],
      // Enable lint rules for React DOM
      reactDom.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```
