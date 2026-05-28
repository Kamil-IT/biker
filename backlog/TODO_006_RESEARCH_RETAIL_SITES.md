# TODO-006 — Research Bike Retail / Classifieds Sites

## Goal
Produce a curated, documented allowlist of bicycle retail and classifieds websites that the generic offer endpoint (TODO-007) can search. Research-only — no application code.

## Behaviour / Deliverable
- Investigate popular bike retail + classifieds sites and document, per site:
  - name, base domain, geography (PL / EU / global),
  - catalog type (new retail / used classifieds / marketplace),
  - whether prices & stock are visible without login,
  - whether product pages render server-side (scrapeable) or require JS (Playwright).
- Candidate sites to evaluate (extend as needed): Wiggle, Chain Reaction Cycles, Trek, Canyon, Specialized, BikeExchange, Decathlon, Rose Bikes, bike-discount.de, Allegro, OLX, Sprzedajemy, Ceneo.
- Recommend a final allowlist (domain list) + priority/ranking for TODO-007.

## Scope
- New doc: `backend/docs/offer_sources.md` (curated allowlist + per-site notes). No endpoint changes.

## Acceptance criteria
- [ ] Doc lists ≥10 evaluated sites with the attributes above.
- [ ] A final recommended allowlist (domains) is called out explicitly.
- [ ] Notes which sites are JS-only (need Playwright) vs static HTML.
- [ ] Output feeds directly into TODO-007.
