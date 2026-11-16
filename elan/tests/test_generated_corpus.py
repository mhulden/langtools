"""Round-trip checks on generated files (REIMPLEMENTATION.md §6.2, checks 1, 2 and 4).

The documents come from tests/eafgen.py and are built in code. Check 3 (schema validity) is
left to test_roundtrip.py, which already has the schema. The large files are built and
serialized once per session (``large_bytes``, ``hierarchy_bytes``), not once per test.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from eafgen import (
    LARGE_TIERS,
    build_large,
    build_large_hierarchy,
    build_text_edge_cases,
    hierarchy_bytes,
    large_bytes,
)
from elan_ng.core.model import Document
from elan_ng.core.structure import analyze
from elan_ng.core.validate import validate
from elan_ng.io.eaf_reader import parse_eaf
from elan_ng.io.eaf_writer import write_eaf

from eafcompare import canonical, first_difference

# Each case: (build the document, its serialized bytes). The bytes come from the same
# deterministic builder, cached for the large files.
Case = tuple[Callable[[], Document], Callable[[], bytes]]

CASES = [
    pytest.param(
        (lambda: build_large(5_000, LARGE_TIERS), lambda: large_bytes(5_000)), id="large_5000"
    ),
    pytest.param(
        (lambda: build_large(50_000, LARGE_TIERS), lambda: large_bytes(50_000)),
        id="large_50000",
        marks=pytest.mark.perf,
    ),
    pytest.param(
        (lambda: build_large_hierarchy(1_250, LARGE_TIERS), lambda: hierarchy_bytes(1_250)),
        id="hierarchy_5000",
    ),
    pytest.param(
        (lambda: build_text_edge_cases(), lambda: write_eaf(build_text_edge_cases())),
        id="text_edge_cases",
    ),
]


def _assert_same(before: bytes, after: bytes) -> None:
    a, b = canonical(before), canonical(after)
    assert a == b, first_difference(a, b)


def _values(doc: Document) -> list[tuple[str, str, str]]:
    return [(tier.id, ann.id, ann.value) for tier in doc.tiers for ann in tier.annotations]


@pytest.mark.parametrize("case", CASES)
def test_generated_round_trip_is_semantically_exact(case: Case) -> None:
    _, serialized = case
    first = serialized()
    _assert_same(first, write_eaf(parse_eaf(first)))


@pytest.mark.parametrize("case", CASES)
def test_generated_writing_is_idempotent(case: Case) -> None:
    _, serialized = case
    once = write_eaf(parse_eaf(serialized()))
    assert write_eaf(parse_eaf(once)) == once


@pytest.mark.parametrize("case", CASES)
def test_generated_text_values_survive_exactly(case: Case) -> None:
    build, serialized = case
    assert _values(parse_eaf(serialized())) == _values(build())


def test_hierarchy_file_is_clean_and_fully_timed() -> None:
    doc = parse_eaf(hierarchy_bytes(1_250))
    assert len(doc.annotations()) == 5_000
    structure = analyze(doc)
    assert validate(doc, structure) == []
    # every annotation, including the symbolic translations, gets times from analyze
    assert all(a in structure.times for a in doc.annotations())


def test_hierarchy_words_split_their_segment_at_the_midpoint() -> None:
    doc = parse_eaf(hierarchy_bytes(1_250))
    structure = analyze(doc)
    root = doc.tiers[0].annotations[0]
    begin, end = structure.times[root]
    words = doc.tier("tier00_words")
    translation = doc.tier("tier00_translation")
    assert words is not None and translation is not None
    first, second = words.annotations[0], words.annotations[1]
    middle = (begin + end) / 2
    assert structure.times[first] == (begin, middle)
    assert structure.times[second] == (middle, end)
    assert structure.times[translation.annotations[0]] == (begin, end)
