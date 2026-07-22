# Remove Aggregate Rating Bar from Review Section

## Description

Remove the horizontal rating bar (visual progress bar) from the bike review section's aggregate rating display. The bar currently shows a visual representation of the 0–10 rating score.

## What to Remove

From the review section, remove:
- The terracotta/orange horizontal bar that visualizes the rating value (currently showing 6.9/10)
- Keep the numeric rating (6.9 /10) and "Rating from 5 sources" text

## Location

Frontend review display in `src/components/BikeDetailsShared.tsx` or `src/components/ReviewSection.tsx` (whichever renders the rating bar).

## Acceptance Criteria

- [x] Rating bar is no longer visible
- [x] Numeric score (e.g., "6.9 /10") remains displayed
- [x] "Rating from 5 sources" text remains displayed
- [x] Visual layout adjusts appropriately
- [x] Works on both bike review and equipment review sections

## Implementation

**Commit:** `e058b6007c776bb936a88242cffa7579a1486eb5`

Removed 6 lines from `frontend/src/components/BikeDetailsShared.tsx`:
- Removed the outer container `div` with progress bar styling
- Removed the inner animated width div that displayed the visual bar
- Kept the "Aggregate rating" label, numeric score, and "Rating from X sources" text

The aggregate rating section now displays as a clean text-based display without the visual progress bar.
