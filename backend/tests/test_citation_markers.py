"""Inline citation markers must resolve to a real source.

The prompt asks the model to write [1], [2] beside claims taken from the
retrieved passages, and the UI renders the numbered source list from the
structured citations field. A marker with no matching entry claims provenance
the system cannot show, which is worse than no marker.

Seen on staging: "دکتر آرمان رهگذر چه نقشی دارد؟" answered with "[1] [3]" and an
empty citation list. The markers came from the previous turn's answer through
the conversation history, not from anything this turn retrieved. The same
happens when an answer cites [7] after five passages were retrieved.
"""

from backend.execution.service import strip_unbacked_citations

SOURCES = [{"doc_id": "a", "title": "one"}, {"doc_id": "b", "title": "two"}]


def test_markers_with_no_sources_at_all_are_removed() -> None:
    text = "بودجه **۹۸ میلیارد ریال** است [1] و [3]."
    assert strip_unbacked_citations(text, []) == "بودجه **۹۸ میلیارد ریال** است."


def test_markers_beyond_the_source_count_are_removed() -> None:
    text = "پاسخ [1] و [7] است."
    assert strip_unbacked_citations(text, SOURCES) == "پاسخ [1] است."


def test_markers_that_resolve_are_kept_verbatim() -> None:
    text = "پاسخ [1] و [2] است."
    assert strip_unbacked_citations(text, SOURCES) == text


def test_persian_digit_markers_are_understood() -> None:
    """The model answers in Persian and writes ۱ as readily as 1."""
    # [۱] resolves to source 1 and stays; [۹] resolves to nothing and goes.
    text = "پاسخ [۱] و [۹] است."
    assert strip_unbacked_citations(text, SOURCES) == "پاسخ [۱] است."


def test_a_real_answer_is_left_alone() -> None:
    text = "## نتیجه\n\nقرارداد با تأمین‌کننده تک‌منبع XR-9 تمدید شد [1] [2]."
    assert strip_unbacked_citations(text, SOURCES) == text


def test_removing_a_marker_does_not_leave_a_dangling_space() -> None:
    """The tidying is part of the fix: a visible hole looks like a bug."""
    assert strip_unbacked_citations("این یک آزمایش است [1] .", []) == "این یک آزمایش است."


def test_brackets_that_are_not_markers_survive() -> None:
    text = "نسخهٔ [بتا] و بازهٔ [الف] دست‌نخورده می‌ماند."
    assert strip_unbacked_citations(text, []) == text
