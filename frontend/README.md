# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

## Application overview

The SPA has three views, switched by `App.tsx` (no router):

**UI language: Polish.** Every user-visible string (labels, buttons, placeholders, `aria-label`s, error messages, `index.html` title/description, `lang="pl"`) is Polish, hard-coded in the components (no i18n library). Filter `<select>`s keep their **English `value`s** — only the `label` is translated (`SearchInput.tsx` `Option { value, label }`), because the backend matches those values against its English data. Content returned by the backend (explanations, reviews, spec **values**, component names) is shown as-is — except the spec-tree **labels**: category, subcategory and spec-key names are translated at display time by `src/specLabels.ts` `translateLabel()` (case-insensitive dictionary, plus `Front …` / `Rear …` / `Max …` prefixes and a trailing `(…)` qualifier such as `Weight (Size M)` → `Waga (rozmiar M)`; unknown labels fall back to the English original). `CategorySection` in `BikeDetailsShared.tsx` applies it, so it covers both the bike and equipment views; the element-name link still passes the untranslated name to the equipment view. The English UI names below (e.g. "Request data") are the pre-translation names used in task files; on screen they read "Poproś o dane", "Nie mamy jeszcze tych danych", "Zgłoszono ✓", "Szukam na OLX…", "Szukam na Allegro i Decathlon…", "Nie znaleziono ofert", "Nie znaleziono", "Czytaj recenzję", "Źródła", "Używane" / "Nowe".

- **Search** — `SearchInput` (free text + collapsible filters) → `POST /v1/bike/search`, rendered as `ResultCard`s — as many as the backend returns (no fixed count; 3 neutral `LoadingCard` skeletons while loading). An empty `bikes: []` (backend parse failure) shows a "Not found" message in the results section.
- **Bike details** (`BikeDetailsView`) — overview, pooled offers (Allegro / Decathlon / OLX), expert review, and a component spec tree. Each **component name in the spec tree is a link** that opens the equipment view for that item (the "Key features" chips stay as plain tags).
  **Request data (TODO-027):** each section — photos, overview, spec tree, expert review, and the Used / New offer cards — shows its loading state for 5 s. If it still has no data then (or its response was empty or failed), a shared `RequestDataButton` takes its place: "We don't have this data yet" + **Request data**. The request keeps running, and data that arrives later replaces the button. A click sends `POST /v1/bike/missing` with the section's `MissingType` (`photos` / `description` / `components` / `review` / `offers_new` / `offers_used`) and turns the button into a disabled "Requested ✓"; a failed POST makes it clickable again. The state is component-only (no `localStorage`). The offers section no longer disappears when both lists are empty — each card shows its own button. The equipment view has no such button.
  **On-demand OLX search (TODO-031):** the **Used** card's button does one thing more. After recording the click it calls `POST /v1/bike/used/search` (`App.tsx` `searchUsedBikes`, passed down as `onSearchUsed` → `RequestDataButton`'s optional `onRequested` prop with `pendingLabel="Szukam na OLX…"`) and shows a spinner + "Szukam na OLX…" while the searcher runs. Offers that come back go into the `usedBikes` state, so the card renders the rows and the button unmounts; if the search finishes with no offers the button becomes a disabled "Nie znaleziono ofert" (same outline style as "Requested ✓"); if the call fails (503 searcher unavailable, 502 searcher error, network) it returns to a clickable "Request data". A failed `/v1/bike/missing` POST does not stop the search — the counter is secondary. The `usedBikeState` is not flipped to `loading` during the search, so the 5 s skeleton grace of the offers section does not restart. The automatic `POST /v1/bike/used/olx` on opening the details view is unchanged (it is now a fast DB read on the backend). Every other `RequestDataButton` usage (no `onRequested`) keeps the TODO-027 behaviour.
  **On-demand Decathlon + Allegro search (TODO-032 / TODO-033):** the **New** card's button works the same way, but runs **two searches at once**. After recording the click (`offers_new`) it calls `POST /v1/bike/decathlon/search` **and** `POST /v1/bike/allegro/search` concurrently (`App.tsx` `searchNew` = `Promise.allSettled([searchDecathlon, searchAllegro])`, passed down as `onSearchNew` → the New `OfferCategoryCard`'s `onRequested` with `pendingLabel="Szukam na Allegro i Decathlon…"`) and shows a spinner + "Szukam na Allegro i Decathlon…" while the searchers run. Each search writes its own state the moment it returns — Decathlon rows into `decathlonOffers`, Allegro rows into `offers` — so rows from **either** source replace the button as they arrive, without waiting for the other. `is_new` comes from the listing (Decathlon: true unless outlet/refurbished; Allegro: false unless the listing says new), so a Decathlon row normally lands in the New card while an Allegro row lands in New **or** Used by its flag. `searchNew` resolves once both have settled: both empty → disabled "Nie znaleziono ofert"; it rejects — clickable again, with the first failure's `detail` — when a call failed (503 / 502 / network) and **neither** brought rows: both failed, or one failed while the other came back empty (for a non-Decathlon brand Decathlon is always instantly empty, so an Allegro 503 busy must not read as "no offers"); a failure next to real rows from the other source is swallowed, the rows are on screen. An Allegro offer with no visible price (`price: ""`) renders "cena w ofercie" instead of a price. While **either** source already has a stored row (`hasNewSourceRows`: any decathlon.pl or allegro.pl row, even one that sits in the Used card) the New card's button is the plain counter click, never a second paid pair of runs. For a brand Decathlon does not sell (anything but its house brands: Rockrider, Btwin, Triban, Van Rysel, Elops, Riverside, Stilus, Tilt, Decathlon) the backend answers the Decathlon call instantly with no offers and no searcher run, so only the Allegro search actually runs. Neither `decathlonState` nor `offerState` is flipped to `loading` during the search, for the same reason as above. The automatic `POST /v1/bike/decathlon` and `POST /v1/bike/allegro` on opening the details view are unchanged in shape but are now fast DB reads of the stored decathlon.pl / allegro.pl offers (empty until a search has run); `App.tsx` reads all three stored sources through one `fetchStoredOffers` helper.
- **Equipment details** (`EquipmentDetailsView`) — the gear counterpart: category eyebrow, overview, expert review, and a component spec tree. **No offers/buy links** — equipment is informational only.

`BikeDetailsView` and `EquipmentDetailsView` share their building blocks (`PhotoGallery`, `DescriptionCard`, `ReviewSection`, `LoadingSkeleton`, `CategorySection`) from `components/BikeDetailsShared.tsx`. The overview renders its sources as **citation footnote chips** (`components/CitationChips.tsx`) — a "Sources" row of terracotta pill links showing each source's domain, opening in a new tab with the full URL as a hover tooltip. The expert review renders its sources as a **full-width source table** below the explanation instead: one row per URL, `stars | domain | "Read review →"`, each row an external link with the full URL as a hover tooltip. The stars are decorative, mapped 0–10 → 1–5 from the aggregate `rating` where one exists.

### Docker

`frontend/Dockerfile` builds the bundle (node 24) and serves it from nginx. `nginx.conf.template` is rendered by the image's
envsubst entrypoint at start (only `PORT` and `BACKEND_URL` are substituted, `NGINX_ENVSUBST_FILTER`): SPA fallback plus
`/v1/*` proxied to `BACKEND_URL` — the same routing Vite does in dev. The Dockerfile defaults (`PORT=8080`,
`BACKEND_URL=http://backend:8000`) serve the root `docker-compose.yml`; on Cloud Run `scripts/deploy.ps1` sets `BACKEND_URL`
to the backend service's https URL. The proxy sends the backend's own hostname as `Host` (Cloud Run routes by it) with SNI
on, and keeps the 600 s read timeout for `/v1/bike/details`.

### API integration (all proxied via Vite `/v1` → backend on :8000)

| Call | Request | Response |
|------|---------|----------|
| `POST /v1/bike/search` | `SearchPayload` | `{ search, bikes[] }` |
| `POST /v1/bike/details` | `{ company, model }` | `BikeDetailsResponse` |
| `POST /v1/bike/review` | `{ company, model }` | `BikeReviewResponse` (AI-backed, cached on the backend) |
| `POST /v1/bike/allegro` | `{ company, model }` | `BikeOfferResponse` `{ offers, info }` — stored allegro.pl offers only (DB read, no AI, TODO-033; `photos` is always `[]` — the Allegro search stores none); empty until the on-demand search below has run |
| `POST /v1/bike/decathlon` | `{ company, model }` | `BikeOfferResponse` `{ offers, info }` — stored decathlon.pl offers only (DB read, no AI); empty until the on-demand search below has run |
| `POST /v1/bike/used/olx` | `{ company, model }` | `UsedBikeResponse` `{ offers, info }` — stored OLX listings only (DB read, no AI); empty until the on-demand search below has run |
| `POST /v1/bike/missing` | `MissingDataRequest` `{ company, model, missing_type }` | `MissingDataResponse` `{ bike_id, missing_type, counter }` (sent by `RequestDataButton`) |
| `POST /v1/bike/used/search` | `{ company, model }` | `UsedBikeResponse` `{ offers, info }` — on-demand OLX search via the searcher service (TODO-031), triggered only by the Used card's "Request data" button; 503 when the searcher is not configured/reachable/busy, 502 when it fails |
| `POST /v1/bike/decathlon/search` | `{ company, model }` | `BikeOfferResponse` `{ offers, info }` — on-demand Decathlon search via the same searcher service (TODO-032), triggered only by the New card's "Request data" button; a non-Decathlon brand answers 200 with `offers: []` and a Polish `info` at once (no searcher call); 404 when the bike is unknown, 503 when the searcher is not configured/reachable/busy, 502 when it fails |
| `POST /v1/bike/allegro/search` | `{ company, model }` | `BikeOfferResponse` `{ offers, info }` — on-demand Allegro search via the same searcher service (TODO-033), sent by the New card's "Request data" button together with `/v1/bike/decathlon/search` (both at once); returned offers carry no photos (`photos: []` by design — allegro.pl blocks every automated fetch, so the searcher scrapes none) and `is_new` from the listing (used unless it says new); 404 when the bike is unknown, 503 when the searcher is not configured/reachable/busy, 502 when it fails |

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
