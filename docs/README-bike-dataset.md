# Bike brand & model dataset

`docs/bike-brands-models.json` — **1,550 brands** and **4,055 models**, aggregated from
openly-licensed or publicly-published sources on 2026-07-23.

Per-source raw files live in `docs/sources/` and are regenerable independently. The merged
file is built from them by `scripts/build_bike_dataset.py`, which also normalises the model
titles — never hand-edit the merged file, re-run the script.

## What this is not

**It is not a list of every bicycle ever made.** No such database exists, and the reasons are
structural rather than a gap someone could fill:

- **No VIN equivalent.** Every manufacturer invents its own serial-number format in its own
  location; many handmade and pre-war frames carry no serial at all. Cross-manufacturer
  aggregation has no common key.
- **The historical record is physically incomplete.** Schwinn's records prior to 1948-08-18 were
  destroyed in a factory fire. Pre-1990 models survive largely as scanned PDF catalogues
  (Velobase, V-CC, bulgier.net) — an OCR project, not a crawl.
- **No authority ever attempted it.** Wikidata holds 132 bicycle items. Open Products Facts
  returns zero for bicycles. EPREL explicitly excludes bicycles and e-bikes. National registers
  are theft registries, and registration is mandatory nowhere in the EU.

For scale: global production is ~130M bikes/year. The largest commercial catalogue on earth
(99 Spokes, 139,027 models) covers roughly 0.1% of a single year's output.

## Sources included

| Source | Provides | Count | Licence |
|---|---|---:|---|
| Bike Index API v3 | brands | 1,495 | Software AGPL-3.0; **data licence unstated** |
| Shopify storefront `/products.json` | models | 2,661 | Public storefront JSON |
| Specialized PL product sitemap | models | 1,251 | Public sitemap, URLs only |
| Wikidata SPARQL | models | 143 | **CC0 1.0** |

Only 91 of the 1,550 brands carry any models — the Bike Index list is a brand *gazetteer*, and
model data was obtainable for a small subset of it.

## Normalisation

Raw collector output was not usable as-is. `scripts/build_bike_dataset.py` applies these
passes and records the counts under `normalisation` in the output file:

| Pass | Rows | What it fixes |
|---|---:|---|
| `variants_collapsed` | 1,079 | Colour/spec variants sharing a base title (`4130 All-Road - Alpine Bloom`, `- Root Beer` → `4130 All-Road`) |
| `brand_prefix_stripped` | 815 | Model name repeating the brand (`Bombtrack Arise` → `Arise`) |
| `year_lifted` | 297 | `(2026)` in the title moved into the `year` field |
| `dropped_component` | 70 | Parts/apparel that leaked past the collector filter |
| `bundle_suffix_cut` | 32 | Promo bundles (`XP Trike2 750 + FREE Cargo Package…`) |
| `generic_lead_dropped` | 22 | Leading generic segment (`Bicycle - R1 - Pebble` → `R1 - Pebble`) |
| `dropped_qid` | 16 | Wikidata rows whose label was an unresolved `Q…` id |
| `region_tag_stripped` | 12 | Trailing locale tag (`… eTrike [CA]`) |

Rows whose title changed keep the original under `raw_title`. Collapsed rows carry a
`variants` count.

Note on the component filter: the **title wins over `product_type`**. Some storefronts file
every product under a bike-ish type — State Bicycle Co. lists Fizik saddles as
`product_type: "Bicycles"` — so a bike-ish type cannot clear a part-ish title. Frameset kits
are exempt and kept with `confidence: "low"`.

## Sources deliberately excluded

Licensing, not capability, is what caps this dataset:

- **99 Spokes** (139,027 models) — Terms forbid accessing the site to "build a similar or
  competitive website", which describes this project exactly. Their `robots.txt` additionally
  carries a hard `Disallow` for ClaudeBot by name plus `Content-Signal: ai-train=no`, an express
  EU DSM Art. 4 reservation of rights. **Licensing via `data@99spokes.com` is the only
  legitimate route to this data.**
- **Geometry Geeks** (~9,000) — ToS explicitly bans systematic or automated collection.
- **Bike Insights** — ToS bars obtaining data by means not intentionally made available
  (permissive `robots.txt` notwithstanding).
- **Bicycle Blue Book** — ToS bars commercial use and comparative analysis for publication.

## Schema

```jsonc
{
  "schema_version": "1.0",
  "generated": "2026-07-23",
  "sources": [ { "id", "name", "url", "licence", "retrieved", "provides" } ],
  "excluded_sources": [ { "name", "models", "reason" } ],
  "stats": { "brands_total", "brands_with_models", "models_total", "models_by_source", "models_low_confidence" },
  "brands": [
    { "name", "short_name", "company_url", "sources": ["bikeindex", ...], "model_count" }
  ],
  "models": [
    { "brand", "model", "year", "url", "source", "confidence", "ref",
      "price", "currency", "product_type", "country" }
  ]
}
```

Every model row carries a `source` id that joins to `sources[].id`, so the licence trail
survives into the merged file. `year` is null for all rows except Wikidata (27 of 159) —
none of the catalogue sources expose model year in a URL or product title.

## Known limitations

- **Colour variants are only partly collapsed.** The collapse keys on a `" - "` or `"(…)"`
  separator, so `4130 All-Road - Root Beer` merges but `XP Trike2 750 Dusk Blue` does not —
  the colour is embedded with no separator. **~200 rows (4%) still contain a colour word**,
  concentrated in Salsa (55), Lectric (42) and Specialized (25). Fixing this needs a colour
  vocabulary, which was not attempted: some models legitimately contain a colour word, so a
  generic strip would corrupt real names.
- **366 rows are `confidence: "low"`** — overwhelmingly framesets and frame kits (real named
  models, but not complete bikes), plus ~10 ambiguous Specialized slugs where a bike name is
  reused for footwear (Hellga, Ruze).
- **Brand is the storefront's house brand, not the product's maker.** For multi-brand shops
  this misattributes third-party goods; most such rows were components and are now dropped,
  but the mapping is still wrong in principle.
- **845 Specialized sitemap URLs were unusable** — they carry no model slug at all
  (`/pl/p/<id>` form), so no name is derivable without crawling the pages.
- **Bike Index's data licence is unstated.** Fine for local lookups and brand normalisation;
  bulk redistribution needs their permission first.
- **Coverage is skewed to English-language direct-to-consumer brands.** The big volume
  manufacturers (Trek, Giant, Cube, Canyon, Merida) are absent — Trek publishes sitemaps but
  they contain zero complete-bike product pages, and the others are not on Shopify.

## Regenerating

Each `docs/sources/*.json` file is produced independently and records its own `source_url`,
`licence` and `retrieved` date. After refreshing any of them, rebuild the merged file:

```bash
python scripts/build_bike_dataset.py
```

The script is deterministic — same inputs give the same output — and re-validates the JSON it
writes before exiting.

## Intended use

A **ground-truth spine** for validating LLM output. The search and details finders currently
have no authoritative list to check `(brand, model)` against, so a hallucinated model name is
indistinguishable from a real one. The brand gazetteer in particular can normalise
`SearchRequest.brand` before any finder runs.
