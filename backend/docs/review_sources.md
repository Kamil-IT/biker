# Cycling Review Sources

## Scope & use case

This document maps the cycling review landscape — professional magazines, community
forums, and video channels — to support two features:

1. **`POST /v1/bike/review`** (`app/prompts/bike_review.md`, `app/bike_review_finder.py`)
   — the endpoint runs a single `web_search` call and synthesises an overall score (0–10)
   with an explanation and source URLs.
2. **TODO-014 (bike rating field)** — an aggregate numeric rating that should lean on
   sources which publish their *own* numeric scores so our synthesis stays grounded
   rather than invented.

The goal here is a curated allowlist: which domains to prefer when steering `web_search`,
how much to trust each, and how to weight them when combining multiple opinions into one
number. We favour sources with **publicly accessible** reviews (no hard paywall), a
track record of **consistent, methodical** testing, and — where possible — a **published
numeric score** we can anchor to.

Two structural facts shaped the recommendations below:

- **CyclingTips is dead.** Outside Inc. shut it down in late 2022/2023 and most of its
  archive is now inaccessible. Its former staff founded **Escape Collective**, which is
  fully member-funded (paywalled). Prefer Escape Collective only for reputation context;
  do not rely on it as a scrapeable public source.
- **Pinkbike / MTBR are Outside Inc. properties** and remain the dominant open MTB
  review + community platforms.

## Source table

| Name | Domain | Type | Coverage | Language | Numeric score | Reliability | Notes |
|---|---|---|---|---|---|---|---|
| BikeRadar | bikeradar.com | Pro magazine | Road / MTB / Gravel / E-bike (mixed) | English | **Yes** — /5 stars | **High** | Explicit, documented 5-star methodology (performance vs rivals, cost, durability, "want" factor). Free to read. Best single anchor source. |
| Cycling Weekly | cyclingweekly.com | Pro magazine | Road / Gravel / E-bike | English | **Yes** — /5 or /10 | **High** | Long-running UK road-focused press; structured verdicts. Free. Already appears in the prompt's example. |
| BikePerfect | bikeperfect.com | Pro magazine | MTB / Gravel / E-MTB | English | **Yes** — /5 stars | **High** | Future plc sister site to BikeRadar; consistent scoring, gravel & trail focus. Free. |
| Pinkbike | pinkbike.com | Magazine + Forum | MTB / E-MTB (some gravel) | English | Partial — comparative "Field Test" rankings, not always /5 | **High** | Largest MTB platform; rigorous multi-tester Field Tests. Reviews & forums public, no login to read. Rankings > absolute scores. |
| MTBR | mtbr.com | Forum / Community | MTB / E-MTB | English | No (community sentiment) | **Medium** | Deep long-tail owner threads; excellent for reliability/longevity signal. Public to read. Noisy — aggregate sentiment, not single posts. |
| BikeMag / Bike Magazine | bikemag.com | Pro magazine | MTB / Gravel | English | Occasional | **Medium-High** | Editorial long-form reviews; less systematic numeric scoring than BikeRadar. Free. |
| GCN (Global Cycling Network) | gcn.com / youtube | YouTube / Blog | Road / Gravel / E-bike | English | No (qualitative) | **Medium-High** | Professional, high production; verdicts are narrative not numeric. Good for ride-feel context; hard to scrape a number. |
| Escape Collective | escapecollective.com | Pro magazine (member) | Road / Gravel / E-bike | English | Rarely | **High (content) / Low (access)** | Ex-CyclingTips team, respected. **Paywalled** — treat as reputation context only, not a primary scrapeable source. |
| Reddit — r/bicycling, r/MTB, r/RoadBikes, r/ebikes, r/gravelcycling | reddit.com | Community | Mixed (subreddit-specific) | English | No | **Medium** | Large, current, candid owner opinion & reliability reports. Public. Highly variable quality — use as corroboration, never sole source. |
| Velominati | velominati.com | Blog / Community | Road (culture bias) | English | No | **Low-Medium** | Cycling culture/etiquette more than product testing. Rarely useful for a model verdict. Deprioritise. |
| Forum Rowerowe | forumrowerowe.org | Forum / Community | Mixed (MTB / Road / commuter) | Polish | No | **Medium** | Largest general Polish cycling forum. Valuable for PL-market models & local pricing sentiment. Public to read. |
| BikeStats.pl | bikestats.pl | Forum / Community | Mixed | Polish | No | **Medium** | Polish brand/model discussion, geometry & spec talk. Public. |
| Poland Bike Forum / Bike Łódź | polandbikeforum.pl · bikelodz.pl | Forum / Community | Mixed | Polish | No | **Low-Medium** | Smaller regional PL communities; thin coverage per model. Corroboration only. |

## Final recommended allowlist

Ordered by priority for steering `web_search` and for aggregation:

**Tier 1 — Pro magazines with numeric scores (primary anchors)**
1. `bikeradar.com`
2. `cyclingweekly.com`
3. `bikeperfect.com`

**Tier 2 — Pro / high-quality editorial (strong, less consistently numeric)**
4. `pinkbike.com` (MTB / e-MTB — use its Field Test rankings)
5. `bikemag.com`
6. `gcn.com`

**Tier 3 — Community corroboration (sentiment & reliability, no scores)**
7. `mtbr.com`
8. `reddit.com` (r/bicycling, r/MTB, r/RoadBikes, r/ebikes, r/gravelcycling)
9. `forumrowerowe.org`, `bikestats.pl` (Polish-market signal)

**Exclude / deprioritise:** `escapecollective.com` (paywalled — reputation context only),
`velominati.com` (culture, not testing), regional PL forums (too thin per model).

### Weighting suggestion for the aggregate rating (TODO-014)

When more than one source is available, weight the synthesis so published numeric scores
dominate and community sentiment only nudges:

| Source class | Weight | Rationale |
|---|---|---|
| Tier 1 pro magazine, numeric /5 or /10 | **3×** | Methodical, comparable, anchorable to a real number. |
| Tier 2 pro editorial (Pinkbike/BikeMag/GCN) | **2×** | Expert but qualitative; convert verdict to 0–10 by language. |
| Tier 3 community (forums, Reddit, MTBR) | **1×** | Aggregate sentiment only; never let a single thread swing the score. |

Practical rules:
- **Normalise to 0–10** before combining (a /5 star score ×2; a "4.5/5" → 9).
- Require **at least one Tier 1 or Tier 2** source before emitting a non-zero score;
  community-only evidence caps confidence.
- If sources disagree by more than ~3 points, prefer the Tier 1 number and note the
  spread in the explanation rather than averaging blindly.
- Match coverage to bike type: **MTB/e-MTB → Pinkbike/BikePerfect/MTBR first**;
  **road/gravel → BikeRadar/Cycling Weekly/GCN first**.

## Suggested prompts

The current `app/prompts/bike_review.md` deliberately uses a **single source** ("Base your
response on a single source — one professional review is preferred"). This is a safe,
low-hallucination default and does not need to change for the review endpoint as it stands.

If/when we move to multi-source aggregation (feeding TODO-014), consider these edits:

- **Add a soft allowlist** to the prompt: instruct `web_search` to prefer the Tier 1/2
  domains above and to treat forum/Reddit results as corroboration only.
- **Allow 1–3 sources** instead of exactly one, and keep the `ref` array in
  priority order (best pro source first). The current "exactly one URL" rule in `ref`
  would need to relax to "1–3 URLs, pro sources first".
- **Anchor the score**: when a source publishes its own numeric rating (e.g. BikeRadar /5),
  instruct the model to convert and weight it per the table above rather than inventing a
  number from prose.
- **Coverage routing**: hint the model to bias toward MTB vs road sources based on the
  bike's category, so an MTB gets Pinkbike/MTBR and a road bike gets BikeRadar/Cycling Weekly.
- **Keep the "never fabricate URLs" rule** — it is the most important guardrail and should
  survive any expansion.

Note: expanding `ref` to multiple URLs is a schema-visible change (`BikeReviewResponse.ref`)
and would require updating the review finder, the smoke test in `scripts/test_review.py`,
and the frontend `ReviewSection`. Treat it as part of TODO-014, not a silent tweak here.
