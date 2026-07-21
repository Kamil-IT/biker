# TODO-005 — Citation Footnote Chips (Google AI Overview Style)

## Goal
Render citations on the description (and/or review explanation) as small source chips shown below each paragraph — similar to Google AI Overviews — instead of bare URLs or plain text.

## Behaviour
- After each paragraph that has associated citations, render a row of chip badges.
- Each chip shows the source domain (e.g. "bikemagazine.com") and is a clickable external link.
- On hover: show full URL as tooltip.
- Chips use the existing terracotta accent colour (`--color-accent`) as a subtle border/tint.

## Current state
- `BikeDescription` in `src/types.ts` has `segments: TextSegment[]` where each segment can carry `citations: DescriptionCitation[]`.
- Review `explanation` is a plain string with no embedded citation data — chips there would use the top-level `ref[]` array applied to the whole block.

## Scope
### Frontend
- `src/components/BikeDetailsView.tsx` (or a new `DescriptionCard.tsx`) — after rendering each `TextSegment`, if `segment.citations` is non-empty render a `<CitationChips>` row.
- New `src/components/CitationChips.tsx` — renders the chip row; accepts `citations: DescriptionCitation[]`.
- For the review section: render one chip row below the explanation paragraph using `ref[]` from `BikeReviewResponse`.

### Backend
- No changes.

## Acceptance criteria
- [ ] Description paragraphs with citations show a chip row underneath.
- [ ] Review explanation shows chips for each URL in `ref[]`.
- [ ] Chips are clickable external links (open in new tab).
- [ ] Chip shows domain name, not full URL.
- [ ] Matches design system colours (terracotta accent, card background).
