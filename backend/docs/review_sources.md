# Curated Review Sources

The curated sources used by `/v1/bike/review` to aggregate a bike `rating`.
Each source is classified by `type`, which determines its weight in the
weighted-mean aggregation (see `app/bike_review_finder.py`).

> Note: this file was authored under TODO-014 to keep the review-rating feature
> self-contained. TODO-013 is the canonical research task for the source list;
> if that document supersedes this one, reconcile them on merge.

## Sources

| # | Source | Domain | Type | Weight |
|---|--------|--------|------|--------|
| 1 | BikeRadar | bikeradar.com | `pro_numeric` | 3× |
| 2 | Cyclingnews | cyclingnews.com | `pro_numeric` | 3× |
| 3 | Pinkbike | pinkbike.com | `pro_numeric` | 3× |
| 4 | Bicycling | bicycling.com | `pro_numeric` | 3× |
| 5 | Cycling Weekly | cyclingweekly.com | `pro_qualitative` | 2× |
| 6 | BikeRumor | bikerumor.com | `pro_qualitative` | 2× |
| 7 | Global Cycling Network (GCN) | globalcyclingnetwork.com | `pro_qualitative` | 2× |
| 8 | Reddit (r/bikes, r/mtb, r/cycling, r/whichbike) | reddit.com | `community` | 1× |
| 9 | Vital MTB / Bike Forums | vitalmtb.com, bikeforums.net | `community` | 1× |

## Classification

- **`pro_numeric`** — professional outlets that publish an explicit numeric
  rating (e.g. 4.5/5 stars). Highest trust → **3× weight**.
- **`pro_qualitative`** — professional prose reviews without a fixed numeric
  scale; a 0–10 score is estimated from the verdict. → **2× weight**.
- **`community`** — forums and aggregated user reviews. Useful for real-world
  longevity/value signal but noisier. → **1× weight**.

## Aggregation

For each source that returns a usable review, Claude reports a per-source
0–10 `score` tagged with its `type`. The backend computes:

```
rating = Σ(score × weight) / Σ(weight)      # normalised to 0–10, 1 decimal
sources_used = count of contributing sources
```

**A non-zero `rating` requires at least one professional source**
(`pro_numeric` or `pro_qualitative`). If only community sources are found,
`rating` is `0.0` and `sources_used` is `0`.
