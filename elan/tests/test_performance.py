"""Open and save performance baseline (REIMPLEMENTATION.md §6.5, rows 1-3).

The documents are built in code, so no large file is stored in the repository. Timings are
printed (run pytest with ``-s`` to see them) so they can be followed over time. Only the
3 s limit for opening is a hard failure; the §6.5 targets are reported, not enforced.
The hierarchy file adds child tiers, so the derived-structure pass (``analyze``), which the
editor runs on open, is timed too.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from eafgen import hierarchy_bytes, large_bytes
from elan_ng.core.structure import analyze
from elan_ng.io.eaf_reader import read_eaf
from elan_ng.io.eaf_writer import save_eaf

TOTAL_ANNOTATIONS = 5_000
TIERS = 30

OPEN_HARD_LIMIT_S = 3.0  # hard CI limit (§6.5)
OPEN_TARGET_S = 1.0  # §6.5 target, reported only
SAVE_TARGET_S = 0.5  # §6.5 target, reported only


@pytest.fixture(scope="module")
def perf_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("perf") / "perf_5000.eaf"
    path.write_bytes(large_bytes(TOTAL_ANNOTATIONS, TIERS))
    return path


@pytest.fixture(scope="module")
def hierarchy_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # a quarter of the annotations are roots; each has two words and one translation
    path = tmp_path_factory.mktemp("perf") / "hierarchy_5000.eaf"
    path.write_bytes(hierarchy_bytes(TOTAL_ANNOTATIONS // 4, TIERS))
    return path


@pytest.mark.perf
def test_open_5000_annotations_within_hard_limit(perf_file: Path) -> None:
    start = time.perf_counter()
    doc = read_eaf(perf_file)
    elapsed = time.perf_counter() - start
    count = len(doc.annotations())
    print(
        f"\nopen  {count} annotations in {len(doc.tiers)} tiers: {elapsed:.3f} s "
        f"(target {OPEN_TARGET_S} s, hard limit {OPEN_HARD_LIMIT_S} s)"
    )
    assert count == TOTAL_ANNOTATIONS
    assert elapsed < OPEN_HARD_LIMIT_S


@pytest.mark.perf
def test_save_5000_annotations_and_reopen(perf_file: Path, tmp_path: Path) -> None:
    doc = read_eaf(perf_file)
    target = tmp_path / "saved_5000.eaf"
    start = time.perf_counter()
    save_eaf(doc, target)
    elapsed = time.perf_counter() - start
    print(f"\nsave  {TOTAL_ANNOTATIONS} annotations: {elapsed:.3f} s (target {SAVE_TARGET_S} s)")
    assert len(read_eaf(target).annotations()) == TOTAL_ANNOTATIONS


@pytest.mark.perf
def test_open_and_analyze_5000_annotations_with_child_tiers(hierarchy_file: Path) -> None:
    start = time.perf_counter()
    doc = read_eaf(hierarchy_file)
    opened = time.perf_counter() - start
    structure = analyze(doc)
    total = time.perf_counter() - start
    count = len(doc.annotations())
    print(
        f"\nopen  {count} annotations in {len(doc.tiers)} tiers (with children): {opened:.3f} s, "
        f"plus analyze {total - opened:.3f} s = {total:.3f} s "
        f"(target {OPEN_TARGET_S} s, hard limit {OPEN_HARD_LIMIT_S} s)"
    )
    assert count == TOTAL_ANNOTATIONS
    assert len(structure.times) == TOTAL_ANNOTATIONS
    assert total < OPEN_HARD_LIMIT_S
