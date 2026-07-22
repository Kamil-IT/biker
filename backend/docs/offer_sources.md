# Bike Retail & Classifieds Sources — Research (TODO-006)

This document is a curated, documented allowlist of bicycle retail and classifieds
websites that the **generic offer endpoint (TODO-007)** can search. It is research
only — there is no application code here. Each site is evaluated for the attributes
that matter to a Claude `web_search` + optional Playwright scraping pipeline:

- **Geography** — the primary market the site serves (Poland / EU / Global).
- **Catalog type** — new retail, used classifieds, marketplace, price comparison, or mixed.
- **Login required** — whether prices and stock are visible to an anonymous visitor.
- **Rendering** — whether product/listing pages are usable from server-side HTML
  (cheap to scrape) or require a JavaScript render (needs Playwright, like the
  existing `olx_image_fetcher.py` / `bike_photos_finder.py` flows).

The existing backend already integrates four sources — **Allegro** (`/v1/bike/offer`),
**OLX** (`/v1/bike/used`), **Ceneo** (`/v1/bike/ceneo`), and **Decathlon**
(`/v1/bike/decathlon`) — each via a single Claude `web_search` call and, for OLX and
manufacturer photo pages, a Playwright scrape. This research extends that set with
additional retail and classifieds candidates so TODO-007 can offer a broader, ranked
allowlist.

## Evaluated Sites

| # | Name | Base domain | Geography | Catalog type | Login for price/stock | Rendering | Notes |
|---|------|-------------|-----------|--------------|-----------------------|-----------|-------|
| 1 | Allegro | allegro.pl | Poland | Marketplace (new + used) | No | JS-heavy (SPA) | **In use** (`/v1/bike/offer`). Largest PL marketplace; huge bike inventory; anti-bot / rate limiting is aggressive — prefer `web_search` over direct scraping. |
| 2 | OLX | olx.pl | Poland | Used classifieds | No | JS-heavy | **In use** (`/v1/bike/used`). Peer-to-peer used listings; photos already scraped via Playwright from `*.apollo.olxcdn.com`. City data available per listing. |
| 3 | Ceneo | ceneo.pl | Poland | Price comparison | No | Server-side HTML (mostly) | **In use** (`/v1/bike/ceneo`). Aggregates offers from many PL shops; good for a "best price" signal; no photos currently pulled. |
| 4 | Decathlon | decathlon.pl | Poland / Global | New retail (own brands) | No | JS-heavy (SPA) | **In use** (`/v1/bike/decathlon`). Own brands (Rockrider, Triban, Van Rysel, Elops, Btwin). Reliable stock/price. PL storefront relevant to users. |
| 5 | Sprzedajemy | sprzedajemy.pl | Poland | Used classifieds | No | Server-side HTML | Second-tier PL classifieds after OLX. Lower volume but genuine private used listings; static pages are easy to read. Good secondary used source. |
| 6 | Rowery.pl / Centrum Rowerowe | centrumrowerowe.pl | Poland | New retail | No | Server-side HTML | Large PL online bike shop; broad catalog of mainstream brands; prices visible; feeds Ceneo. Strong PL new-retail candidate. |
| 7 | Sklep Rowerowy (bike shops via Google) | various .pl | Poland | New retail | No | Mixed | Long tail of PL shops (e.g. bikeshop.pl, rowerowy.eu). Best reached through `web_search` rather than a fixed domain. |
| 8 | Bike-Discount | bike-discount.de | Germany / EU | New retail | No | Server-side HTML | Very large EU catalog (Radon house brand + major brands). Ships to PL. Prices in EUR, visible without login. Static, scrapeable. Strong EU candidate. |
| 9 | Rose Bikes | rosebikes.pl / rosebikes.com | Germany / EU (PL storefront) | New retail (own + parts) | No | JS-heavy | German direct-to-consumer; has a localized PL storefront with PLN pricing. Configurable bikes complicate a single canonical price. |
| 10 | Canyon | canyon.com | Germany / Global | New retail (manufacturer, direct) | No | JS-heavy (SPA) | Direct-to-consumer only (no dealers). Authoritative spec + MSRP source. Ships to PL. Already used as a details/photo reference in the codebase. |
| 11 | Trek | trekbikes.com | USA / Global | New retail (manufacturer) | No | JS-heavy | Manufacturer MSRP + spec authority. Sold through dealers, so on-site "buy" is region-dependent; good for spec/price reference, weak for live PL stock. |
| 12 | Specialized | specialized.com | USA / Global | New retail (manufacturer) | No | JS-heavy | Same profile as Trek — authoritative MSRP/spec, dealer-distributed. Good reference, not a live PL offer source. |
| 13 | Wiggle | wiggle.com | Global (UK) | New retail | No | JS-heavy | **Effectively defunct** — Wiggle/CRC went into administration (2023–2024); site historically redirected/closed. Do **not** allowlist. Kept here as an evaluated-and-rejected candidate. |
| 14 | Chain Reaction Cycles | chainreactioncycles.com | Global (UK) | New retail | No | JS-heavy | Same parent as Wiggle; same administration fate. **Rejected** — unreliable availability. |
| 15 | BikeExchange | bikeexchange.com / .de | Global / EU | Marketplace (new + used, dealer) | No | JS-heavy | Dealer-and-marketplace aggregator. Weak/absent PL coverage; inconsistent inventory. Low priority — reference only. |
| 16 | bikesalon | bikesalon.pl | Poland | New retail | No | Server-side HTML | Established PL online + brick-and-mortar shop; broad brand catalog; prices visible; feeds Ceneo. Solid PL new-retail secondary. |

## Final Recommended Allowlist

Ordered by priority for TODO-007. Tier 1 = already integrated and proven; Tier 2 =
high-value additions to implement next; Tier 3 = reference/spec authorities and
optional long-tail.

**Tier 1 — already integrated (keep):**
1. `allegro.pl` — marketplace, widest PL new + used inventory.
2. `olx.pl` — primary PL used classifieds (with Playwright photo scrape).
3. `ceneo.pl` — PL price-comparison / best-price signal.
4. `decathlon.pl` — reliable PL new retail (own brands).

**Tier 2 — recommended new sources for TODO-007:**
5. `bike-discount.de` — large EU catalog, static HTML, ships to PL, EUR pricing.
6. `centrumrowerowe.pl` — large PL new-retail shop, static HTML.
7. `sprzedajemy.pl` — secondary PL used classifieds, static HTML.
8. `bikesalon.pl` — established PL new-retail shop, static HTML.
9. `rosebikes.pl` — EU direct-to-consumer with a PLN storefront.

**Tier 3 — spec / MSRP reference authorities (not live PL stock):**
10. `canyon.com` — direct-to-consumer manufacturer, authoritative spec/MSRP.
11. `trekbikes.com` — manufacturer MSRP/spec reference.
12. `specialized.com` — manufacturer MSRP/spec reference.

**Rejected (do not allowlist):** `wiggle.com`, `chainreactioncycles.com` (both defunct
after administration), `bikeexchange.com` (negligible PL coverage).

## Rendering Method (Playwright vs Static HTML)

The generic offer endpoint should reach every source through a Claude `web_search`
call first — that avoids most anti-bot friction. Playwright is only needed when we
must scrape **images or JS-rendered prices** directly from a URL the search returned.

**Static / server-side HTML — cheap, no Playwright needed for scraping:**
- `ceneo.pl` (mostly)
- `sprzedajemy.pl`
- `centrumrowerowe.pl`
- `bikesalon.pl`
- `bike-discount.de`

**JS-heavy — require Playwright if scraping the page directly (mirror
`olx_image_fetcher.py` / `bike_photos_finder.py`, `headless=False`):**
- `allegro.pl`
- `olx.pl` (already handled this way for photos)
- `decathlon.pl`
- `rosebikes.pl`
- `canyon.com`, `trekbikes.com`, `specialized.com`
- `bikeexchange.com`

**Login:** none of the recommended sources require login to see price or stock —
all prices are visible to anonymous visitors. No credentialed scraping is required.

## Integration Recommendations for TODO-007

- **Search-first, scrape-second.** Reuse the existing pattern: one Claude
  `web_search_20250305` call per source with a per-source system prompt
  (`app/prompts/bike_offer_<source>.md`), then Playwright only for photos on JS-heavy
  domains. This is exactly how `bike_offer_finder.py`, `bike_offer_ceneo_finder.py`,
  and `bike_offer_decathlon_finder.py` already work.
- **Config-driven allowlist.** Store the allowlist (domain, tier, `is_used` flag,
  `needs_playwright` flag, `currency`) as data so a generic endpoint can iterate the
  sources instead of hard-coding one finder per site.
- **Split new vs used.** Tier 1/2 sources map cleanly onto the frontend's
  `MergedOffersSection`, which already splits offers by each offer's `is_new` flag.
  Mark `olx.pl` and `sprzedajemy.pl` as used-only; the rest as new.
- **Currency.** `bike-discount.de` and `rosebikes.com` may return EUR — carry a
  currency field per offer rather than assuming PLN.
- **Caching.** Follow the SQLite-cache rule in `CLAUDE.md`: only `set_cached` on the
  happy path and only when `result.offers` is non-empty, keyed on
  `{company, model, source}`.
- **Prioritize Tier 1 + Tier 2** for the first cut; treat Tier 3 manufacturer sites as
  an MSRP/spec fallback, not a live-stock source.
