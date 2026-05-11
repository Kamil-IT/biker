# Next Steps

## Finding Offers

### Marketplace Integrations
- [ ] **Allegro** — blocked: offer listing endpoint requires a verified app; not implementing for now ([restriction details](https://developer.allegro.pl/news/get-offers-listing-tylko-dla-zweryfikowanych-aplikacji-GRax4oVgrs1))
- [ ] **OLX** — waiting for account approval
- [ ] **Amazon** — todo (https://developer.amazon.com/docs/app-submission-api/auth.html)
- [ ] Research popular bicycle websites (e.g. Wiggle, Chain Reaction Cycles, Trek, Canyon, Specialized, BikeExchange)
- [ ] Implement generic web search with a curated allowlist of bicycle retail/classifieds sites to return a live offer list per bike model

## Describing a Bike

### Prompt & Component Search
- [ ] Add tests for the component-search prompt (`bike_details_finder.py` / `app/prompts/bike_details_*.md`)

### Data & Caching
- [ ] Add SQLite database to cache searches and component results, enabling deeper follow-up queries without re-fetching
  - Tables: `search_cache`, `bike_details_cache`, keyed by query / (company + model)

### Reviews & Ranking
- [ ] Find cycling forums with bike reviews (e.g. BikeRadar, MTBR, Reddit r/cycling, Velominati)
- [ ] Add a **bike rank / rating** field derived from aggregated forum/review data

## Bike Search by Categories

### Testing
- [ ] Add tests for the category-scoring prompt (`anthropic_scorer.py` / `app/prompts/<category>.md`)
