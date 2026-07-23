"""Pure unit tests for the TODO-018 review aggregation rules (backend/app/bike_review_finder.py).

No network, no live server, no Anthropic API key needed: ANTHROPIC_API_KEY is
stubbed below *before* importing app.bike_review_finder, because that module
constructs an AsyncAnthropic() client at import time (module-level `_client`).
AsyncAnthropic() itself does not validate the key eagerly, but a stub is set
anyway so this file works even if that changes upstream, and so it never
depends on a real .env being present.

Covers the two TODO-018 gaps:
  - source-disagreement rule (_aggregate_rating): spread > DISAGREEMENT_THRESHOLD
    anchors to Tier 1 (else Tier 2) instead of the weighted mean; the note text
    (_disagreement_note); malformed per_source entries are skipped, not raised.
  - ref priority ordering (_order_ref): Tier 1 -> Tier 2 -> Tier 3, stable
    within a tier, unknown URLs pushed to the end.

Run:
    cd backend
    python -m pytest scripts/test_review_aggregation.py -v
"""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy-key-not-real")

from app.bike_review_finder import (  # noqa: E402
    DISAGREEMENT_THRESHOLD,
    _aggregate_rating,
    _disagreement_note,
    _order_ref,
)


def _source(type_, score, url=None, source=None):
    entry = {"type": type_, "score": score}
    if url is not None:
        entry["url"] = url
    if source is not None:
        entry["source"] = source
    return entry


# --------------------------------------------------------------------------
# _aggregate_rating — agreeing case (regression guard on the TODO-014 mean)
# --------------------------------------------------------------------------


def test_agreeing_sources_use_weighted_mean_exactly():
    per_source = [
        _source("pro_numeric", 8, url="https://bikeradar.com/a"),
        _source("pro_qualitative", 7, url="https://pinkbike.com/a"),
        _source("community", 6, url="https://reddit.com/a"),
    ]
    # weighted_sum = 8*3 + 7*2 + 6*1 = 44; weight_total = 6; mean = 44/6 = 7.3333...
    expected_mean = round((8 * 3 + 7 * 2 + 6 * 1) / 6, 1)
    assert expected_mean == 7.3

    rating, sources_used, info = _aggregate_rating(per_source)

    assert rating == expected_mean
    assert sources_used == 3
    assert info["disagreement"] is False


# --------------------------------------------------------------------------
# _aggregate_rating — disagreement rule
# --------------------------------------------------------------------------


def test_disagreement_anchors_to_tier1_not_weighted_mean():
    per_source = [
        _source("pro_numeric", 9, url="https://bikeradar.com/a"),
        _source("community", 4, url="https://reddit.com/a"),
    ]
    # spread = 9 - 4 = 5 > 3.0 threshold
    weighted_mean = round((9 * 3 + 4 * 1) / 4, 1)

    rating, sources_used, info = _aggregate_rating(per_source)

    assert info["disagreement"] is True
    assert info["anchor_tier"] == "pro_numeric"
    assert rating == 9.0
    assert rating != weighted_mean
    assert sources_used == 2  # unchanged by the disagreement rule


def test_disagreement_anchors_to_tier2_when_no_tier1_present():
    per_source = [
        _source("pro_qualitative", 9, url="https://pinkbike.com/a"),
        _source("community", 4, url="https://reddit.com/a"),
    ]
    weighted_mean = round((9 * 2 + 4 * 1) / 3, 1)

    rating, sources_used, info = _aggregate_rating(per_source)

    assert info["disagreement"] is True
    assert info["anchor_tier"] == "pro_qualitative"
    assert rating == 9.0
    assert rating != weighted_mean
    assert sources_used == 2


def test_disagreement_anchor_is_mean_of_multiple_tier1_sources():
    per_source = [
        _source("pro_numeric", 9, url="https://bikeradar.com/a"),
        _source("pro_numeric", 8, url="https://cyclingweekly.com/a"),
        _source("community", 3, url="https://reddit.com/a"),
    ]
    # spread = 9 - 3 = 6 > 3.0
    rating, sources_used, info = _aggregate_rating(per_source)

    assert info["disagreement"] is True
    assert info["anchor_tier"] == "pro_numeric"
    assert rating == round((9 + 8) / 2, 1) == 8.5
    assert sources_used == 3


def test_no_professional_source_falls_back_to_zero_without_crashing():
    per_source = [
        _source("community", 8, url="https://reddit.com/a"),
        _source("community", 2, url="https://mtbr.com/a"),
    ]
    rating, sources_used, info = _aggregate_rating(per_source)

    assert rating == 0.0
    assert sources_used == 0
    assert info["disagreement"] is False


def test_sources_used_counts_all_consulted_sources_regardless_of_rule():
    agreeing = [
        _source("pro_numeric", 8, url="https://bikeradar.com/a"),
        _source("pro_qualitative", 7, url="https://pinkbike.com/a"),
        _source("community", 7, url="https://reddit.com/a"),
    ]
    disagreeing = [
        _source("pro_numeric", 9, url="https://bikeradar.com/a"),
        _source("pro_qualitative", 8, url="https://pinkbike.com/a"),
        _source("community", 2, url="https://reddit.com/a"),
    ]
    _, used_agree, info_agree = _aggregate_rating(agreeing)
    _, used_disagree, info_disagree = _aggregate_rating(disagreeing)

    assert info_agree["disagreement"] is False
    assert info_disagree["disagreement"] is True
    assert used_agree == used_disagree == 3


def test_spread_exactly_threshold_is_not_a_disagreement():
    per_source = [
        _source("pro_numeric", 8, url="https://bikeradar.com/a"),
        _source("community", 5, url="https://reddit.com/a"),
    ]
    spread = 8 - 5
    assert spread == DISAGREEMENT_THRESHOLD  # exactly at the boundary

    rating, sources_used, info = _aggregate_rating(per_source)

    assert info["disagreement"] is False
    assert info["spread"] == DISAGREEMENT_THRESHOLD
    # falls through to the ordinary weighted mean, not the anchor
    assert rating == round((8 * 3 + 5 * 1) / 4, 1)


def test_malformed_entries_are_skipped_without_raising():
    per_source = [
        "not a dict",
        {"type": "pro_numeric"},  # missing score
        {"type": "unknown_tier", "score": 7},  # unknown type
        {"type": "pro_numeric", "score": "not-a-number"},  # unparseable score
        _source("pro_numeric", 8, url="https://bikeradar.com/a"),
        _source("community", 4, url="https://reddit.com/a"),
    ]
    # spread = 8 - 4 = 4 > 3.0 -> disagreement, anchored to the one valid pro_numeric entry
    rating, sources_used, info = _aggregate_rating(per_source)

    assert sources_used == 2  # only the two well-formed entries counted
    assert info["disagreement"] is True
    assert rating == 8.0


def test_disagreement_note_contains_spread_and_endpoint_scores():
    per_source = [
        _source("pro_numeric", 9, url="https://bikeradar.com/a"),
        _source("community", 4, url="https://reddit.com/a"),
    ]
    _, _, info = _aggregate_rating(per_source)

    note = _disagreement_note(info)

    assert "9" in note  # high endpoint
    assert "4" in note  # low endpoint
    assert "5" in note  # spread = 9 - 4


# --------------------------------------------------------------------------
# _order_ref — priority ordering
# --------------------------------------------------------------------------


def test_order_ref_reorders_pro_numeric_before_pro_qualitative_before_community():
    per_source = [
        _source("community", 6, url="https://reddit.com/a"),
        _source("pro_numeric", 8, url="https://bikeradar.com/a"),
        _source("pro_qualitative", 7, url="https://pinkbike.com/a"),
    ]
    # deliberately unsorted, community first, matching the model's likely emission order
    refs = ["https://reddit.com/a", "https://bikeradar.com/a", "https://pinkbike.com/a"]

    ordered = _order_ref(refs, per_source)

    assert ordered == [
        "https://bikeradar.com/a",
        "https://pinkbike.com/a",
        "https://reddit.com/a",
    ]


def test_order_ref_puts_unknown_urls_last_and_keeps_relative_order():
    per_source = [
        _source("pro_numeric", 8, url="https://bikeradar.com/a"),
    ]
    refs = [
        "https://unknown-one.example/a",
        "https://bikeradar.com/a",
        "https://unknown-two.example/a",
    ]

    ordered = _order_ref(refs, per_source)

    assert ordered == [
        "https://bikeradar.com/a",
        "https://unknown-one.example/a",
        "https://unknown-two.example/a",
    ]


def test_order_ref_is_stable_within_a_tier():
    per_source = [
        _source("community", 6, url="https://reddit.com/a"),
        _source("community", 5, url="https://mtbr.com/a"),
        _source("pro_numeric", 9, url="https://bikeradar.com/a"),
    ]
    refs = [
        "https://reddit.com/a",
        "https://mtbr.com/a",
        "https://bikeradar.com/a",
    ]

    ordered = _order_ref(refs, per_source)

    # bikeradar (tier 1) moves to the front; the two community URLs keep
    # their original relative order (reddit before mtbr)
    assert ordered == [
        "https://bikeradar.com/a",
        "https://reddit.com/a",
        "https://mtbr.com/a",
    ]
