# Bike brand & model dataset

`docs/bike-brands-models.json` — **1,553 brands** and **4,599 models**, aggregated from
openly-licensed or publicly-published sources on 2026-07-23.

Per-source raw files live in `docs/sources/` and are regenerable independently.

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
| Shopify storefront `/products.json` | models | 3,188 | Public storefront JSON |
| Specialized PL product sitemap | models | 1,252 | Public sitemap, URLs only |
| Wikidata SPARQL | models | 159 | **CC0 1.0** |

Only 95 of the 1,553 brands carry any models — the Bike Index list is a brand *gazetteer*, and
model data was obtainable for a small subset of it.

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

- **Colour and size variants inflate model counts.** Some Shopify shops (Lectric, Squid, Surly)
  publish each variant as a separate product. Rows are deduped on `(brand, model, source)`,
  which collapsed 621 Specialized duplicates, but titles that differ by a colour word survive as
  separate rows. Normalising titles to bare model names would need a further pass.
- **173 rows are `confidence: "low"`** — overwhelmingly Specialized framesets and frame kits
  (real named models, but not complete bikes), plus ~10 ambiguous slugs where Specialized reuses
  a bike name for footwear (Hellga, Ruze).
- **845 Specialized sitemap URLs were unusable** — they carry no model slug at all
  (`/pl/p/<id>` form), so no name is derivable without crawling the pages.
- **Bike Index's data licence is unstated.** Fine for local lookups and brand normalisation;
  bulk redistribution needs their permission first.
- **Coverage is skewed to English-language direct-to-consumer brands.** The big volume
  manufacturers (Trek, Giant, Cube, Canyon, Merida) are absent — Trek publishes sitemaps but
  they contain zero complete-bike product pages, and the others are not on Shopify.

## Regenerating

Each `docs/sources/*.json` file is produced independently and records its own `source_url`,
`licence` and `retrieved` date. Re-run a collector, then re-run the merge to rebuild
`bike-brands-models.json`.

## Intended use

A **ground-truth spine** for validating LLM output. The search and details finders currently
have no authoritative list to check `(brand, model)` against, so a hallucinated model name is
indistinguishable from a real one. The brand gazetteer in particular can normalise
`SearchRequest.brand` before any finder runs.
