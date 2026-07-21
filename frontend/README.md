# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

## Application overview

The SPA has three views, switched by `App.tsx` (no router):

- **Search** — `SearchInput` (free text + collapsible filters) → `POST /v1/bike/search`, rendered as `ResultCard`s.
- **Bike details** (`BikeDetailsView`) — overview, pooled offers (Allegro / Ceneo / Decathlon / OLX), expert review, and a component spec tree. Each **component name in the spec tree is a link** that opens the equipment view for that item (the "Key features" chips stay as plain tags).
- **Equipment details** (`EquipmentDetailsView`) — the gear counterpart: category eyebrow, overview, expert review, and a component spec tree. **No offers/buy links** — equipment is informational only.

`BikeDetailsView` and `EquipmentDetailsView` share their building blocks (`PhotoGallery`, `DescriptionCard`, `ReviewSection`, `LoadingSkeleton`, `CategorySection`) from `components/BikeDetailsShared.tsx`.

### API integration (all proxied via Vite `/v1` → backend on :8000)

| Call | Request | Response |
|------|---------|----------|
| `POST /v1/bike/search` | `SearchPayload` | `{ search, bikes[] }` |
| `POST /v1/bike/details` | `{ company, model }` | `BikeDetailsResponse` |
| `POST /v1/bike/review` · `/offer` · `/ceneo` · `/decathlon` · `/used` | `{ company, model }` | review / offers |

`BikeReviewResponse` also carries an aggregate `rating` (0–10, weighted across curated review sources) and `sources_used` count; `ReviewSection` renders these as a rating bar with a "Rating from X sources" caption above the expert-review prose.
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
