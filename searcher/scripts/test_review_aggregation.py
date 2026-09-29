"""Pure unit tests for the TODO-018 review aggregation rules, now in searcher/app/review_finder.py (TODO-037).

Ported from backend/scripts/test_review_aggregation.py when the review finder
moved into the searcher; the assertions are unchanged, so they pin the rating
logic to what the backend computed. No network, no CLI run, no database.

Covers:
  - source-disagreement rule (_aggregate_rating): spread > DISAGREEMENT_THRESHOLD
    anchors to Tier 1 (else Tier 2) instead of the weighted mean; the note text
    (_disagreement_note); malformed per_source entries are skipped, not raised.
  - ref priority ordering (_order_ref): Tier 1 -> Tier 2 -> Tier 3, stable
    within a tier, unknown URLs pushed to the end.
  - build_review: <cite> stripping, disagreement sentence appended, score clamp,
    fallback review without an explanation.

Run:
    cd searcher
    python -m pytest scripts/test_review_aggregation.py -v
"""

from app.review_finder import (
    DISAGREEMENT_THRESHOLD,
    EXPLANATION_MAX_LEN,
    FALLBACK,
    _aggregate_rating,
    _disagreement_note,
    _order_ref,
    build_review,
    is_safe_review_url,
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


# --------------------------------------------------------------------------
# build_review — the CLI answer -> BikeReview (searcher only)
# --------------------------------------------------------------------------


def test_build_review_strips_cite_orders_ref_and_appends_disagreement_note():
    per_source = [
        _source("community", 4, url="https://reddit.com/a"),
        _source("pro_numeric", 9, url="https://bikeradar.com/a"),
    ]
    data = {
        "score": 8,
        "explanation": 'Dobry <cite index="1-2">rower</cite>.',
        "per_source": per_source,
        "ref": ["https://reddit.com/a", "https://bikeradar.com/a"],
    }
    lt = chr(60)  # the web-search citation markup: <cite index="…">…</cite>
    data["explanation"] = f'Dobry {lt}cite index="1-2">rower{lt}/cite>.'

    review = build_review(data)

    assert review.explanation == f"Dobry rower. {_disagreement_note(_aggregate_rating(per_source)[2])}"
    assert review.ref == ["https://bikeradar.com/a", "https://reddit.com/a"]
    assert review.rating == 9.0
    assert review.sources_used == 2
    assert review.score == 8


def test_build_review_clamps_score_and_keeps_empty_result():
    review = build_review({"score": 14, "explanation": "Brak źródeł.", "per_source": [], "ref": []})

    assert review.score == 10
    assert review.ref == []
    assert review.rating == 0.0
    assert review.sources_used == 0


def test_build_review_drops_banned_domains_before_aggregation():
    per_source = [
        _source("pro_numeric", 2, url="https://escapecollective.com/review/x"),
        _source("pro_qualitative", 3, url="https://shop.velominati.com/y"),
        _source("pro_numeric", 1, source="www.escapecollective.com"),  # no url: judged by source
        _source("pro_numeric", 8, url="https://www.bikeradar.com/a"),
        _source("community", 7, url="https://notescapecollective.com/a"),  # look-alike, not banned
    ]
    data = {
        "score": 8,
        "explanation": "Recenzja.",
        "per_source": per_source,
        "ref": [
            "https://www.escapecollective.com/review/x",
            "https://notescapecollective.com/a",
            "https://shop.velominati.com/y",
            "https://www.bikeradar.com/a",
        ],
    }

    review = build_review(data)

    # only bikeradar (8, x3) and the look-alike (7, x1) count: no disagreement, weighted mean
    assert review.sources_used == 2
    assert review.rating == round((8 * 3 + 7 * 1) / 4, 1)
    assert review.explanation == "Recenzja."
    assert review.ref == ["https://www.bikeradar.com/a", "https://notescapecollective.com/a"]


def test_is_safe_review_url():
    assert is_safe_review_url("https://www.bikeradar.com/a")
    assert is_safe_review_url("http://forumrowerowe.org/t/1")
    for bad in (
        "javascript:alert(1)",
        "data:text/html,x",
        "ftp://bikeradar.com/a",
        "//bikeradar.com/a",
        "bikeradar.com/a",
        "/reviews/a",
        "https://",
        " https://bikeradar.com/a",
        "https://escapecollective.com/a",
        "https://" + "a" * 2048,
        "",
        None,
        123,
    ):
        assert not is_safe_review_url(bad), bad


def test_build_review_drops_unsafe_urls_before_aggregation():
    per_source = [
        _source("pro_numeric", 1, url="javascript:alert(1)"),
        _source("pro_numeric", 2, url="data:text/html,x"),
        _source("pro_numeric", 2),  # no url at all
        _source("pro_numeric", 8, url="https://www.bikeradar.com/a"),
    ]
    data = {
        "score": 8,
        "explanation": "Recenzja.",
        "per_source": per_source,
        "ref": ["javascript:alert(1)", "https://www.bikeradar.com/a", "reddit.com/r/x", 42],
    }

    review = build_review(data)

    assert review.sources_used == 1
    assert review.rating == 8.0
    assert review.explanation == "Recenzja."  # the bad low scores never triggered a disagreement
    assert review.ref == ["https://www.bikeradar.com/a"]


def test_build_review_caps_explanation_length_keeping_the_disagreement_note():
    long_text = "x" * 10_000
    plain = build_review({"score": 5, "explanation": long_text, "per_source": [], "ref": []})
    assert len(plain.explanation) == EXPLANATION_MAX_LEN

    per_source = [
        _source("pro_numeric", 9, url="https://bikeradar.com/a"),
        _source("community", 2, url="https://reddit.com/a"),
    ]
    split = build_review({"score": 5, "explanation": long_text, "per_source": per_source, "ref": []})
    note = _disagreement_note(_aggregate_rating(per_source)[2])
    assert len(split.explanation) <= EXPLANATION_MAX_LEN
    assert split.explanation.endswith(note)


def test_build_review_without_explanation_is_the_fallback():
    assert build_review({"score": 7, "per_source": [], "ref": []}) == FALLBACK
    assert FALLBACK.explanation == "Recenzja niedostępna."
