"""Safe import ordering is distinct from changing malformed annotation semantics."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

import pytest
from lxml import etree

from eafgen import large_bytes
from elan_ng.core.changes import check_invariants
from elan_ng.core.constraints import ConstraintEngine, EditRejected
from elan_ng.core.model import AlignableAnnotation, Document
from elan_ng.core.structure import analyze, symbolic_order
from elan_ng.core.undo import UndoStack
from elan_ng.core.validate import Problem, Severity, validate
from elan_ng.io.eaf_reader import parse_eaf, read_eaf
from elan_ng.io.eaf_writer import save_eaf, write_eaf

from .helpers import snapshot
from eafcompare import canonical
from support import DATA


def _ids(doc: Document, tier_id: str) -> list[str]:
    tier = doc.tier(tier_id)
    assert tier is not None
    return [a.id for a in tier.annotations]


def test_import_normalizes_alignable_tiers_and_reports_each_changed_tier() -> None:
    diagnostics: list[Problem] = []
    doc = read_eaf(DATA / "out_of_order.eaf", diagnostics=diagnostics)
    assert _ids(doc, "root") == ["a1", "a2"]
    assert _ids(doc, "included") == ["c1", "c2"]
    assert _ids(doc, "words") == ["w1", "w2"]
    assert {p.ids for p in diagnostics if p.code == "annotation-order-normalized"} == {
        ("root",),
        ("included",),
        ("words",),
    }
    assert validate(doc) == []
    check_invariants(doc)
    assert _ids(doc, "gloss") == ["r2", "r1"]
    assert _ids(doc, "chain") == ["q2", "q1"]
    chain = doc.tier("chain")
    assert chain is not None
    assert [[a.id for a in group] for group in symbolic_order(chain, analyze(doc)).values()] == [
        ["q1", "q2"],
    ]
    annotations = doc.annotation_index()
    w1, w2 = annotations["w1"][1], annotations["w2"][1]
    assert isinstance(w1, AlignableAnnotation) and isinstance(w2, AlignableAnnotation)
    assert w1.end is w2.begin and w1.end.value is None


def test_normalization_only_permutes_annotation_wrappers_and_preserves_residue() -> None:
    data = (DATA / "out_of_order.eaf").read_bytes()
    expected = etree.fromstring(data)
    # Reference-only tiers stay as authored. Unknown tier nodes keep their positional
    # anchors, while each whole annotation wrapper travels with all its own residue.
    for name in ("root", "included", "words"):
        tier = expected.find(f"TIER[@TIER_ID='{name}']")
        assert tier is not None
        indices = [i for i, child in enumerate(tier) if child.tag == "ANNOTATION"]
        left, right = (tier[i] for i in indices)
        tier.remove(left)
        tier.remove(right)
        tier.insert(indices[0], right)
        tier.insert(indices[1], left)
    doc = parse_eaf(data)
    assert canonical(write_eaf(doc)) == canonical(etree.tostring(expected))
    a1, a2 = doc.annotation_index()["a1"][1], doc.annotation_index()["a2"][1]
    assert a1.value == "ñ & <hello>\nsecond line" and a2.value == ""
    assert a2.ext_ref == "er1" and a2.lang_ref == "eng"
    assert a1.wrapper_residue.attrs["FUTURE_WRAPPER"] == "early"
    assert a2.value_residue.attrs["FUTURE_VALUE"] == "late"
    tier = doc.tier("root")
    assert tier is not None and all(anchor == 1 for anchor, _ in tier.residue.children)


def test_imported_order_supports_edits_exact_undo_and_disk_round_trip(tmp_path: Path) -> None:
    doc = read_eaf(DATA / "out_of_order.eaf")
    before = snapshot(doc)
    engine, stack = ConstraintEngine(doc), UndoStack(doc)
    stack.execute(engine.create("root", 1500, 1600, "new"))
    stack.execute(engine.retime("a2", 1700, 1800))
    edited = snapshot(doc)
    assert stack.undo() and stack.undo() and snapshot(doc) == before
    assert stack.redo() and stack.redo() and snapshot(doc) == edited
    path = tmp_path / "normalized.eaf"
    save_eaf(doc, path)
    diagnostics: list[Problem] = []
    loaded = read_eaf(path, diagnostics=diagnostics)
    assert diagnostics == []
    assert canonical(write_eaf(loaded)) == canonical(path.read_bytes())
    assert _ids(loaded, "root") == _ids(doc, "root")
    check_invariants(loaded)


@pytest.mark.parametrize(
    "problem,code",
    [
        ("overlap", "overlap"),
        ("empty", "empty-interval"),
        ("missing-slot", "unknown-slot"),
        ("missing-parent", "unknown-parent"),
        ("duplicate-id", "duplicate-id"),
        ("slot-order", "time-order"),
        ("duplicate-slot", "duplicate-slot-id"),
        ("invalid-time", "invalid-time-value"),
        ("unresolved-time", "unresolved-time"),
        ("cycle", "tier-cycle"),
        ("negative-time", "invalid-time-value"),
        ("unaligned-root", "unaligned-boundary"),
        ("wrong-parent-tier", "wrong-parent-tier"),
    ],
)
def test_malformed_or_ambiguous_input_retains_order_and_diagnostics(
    problem: str,
    code: str,
) -> None:
    root = etree.fromstring((DATA / "out_of_order.eaf").read_bytes())
    early = root.find(".//ALIGNABLE_ANNOTATION[@ANNOTATION_ID='a1']")
    assert early is not None
    if problem == "overlap":
        early.set("TIME_SLOT_REF2", "ts7")
    elif problem == "empty":
        early.set("TIME_SLOT_REF2", "ts0")
    elif problem == "missing-slot":
        early.set("TIME_SLOT_REF2", "missing")
    elif problem == "unaligned-root":
        early.set("TIME_SLOT_REF1", "u")
    elif problem == "wrong-parent-tier":
        reference = root.find(".//REF_ANNOTATION[@ANNOTATION_ID='r1']")
        assert reference is not None
        reference.set("ANNOTATION_REF", "c1")
    elif problem in ("missing-parent", "cycle"):
        tier = root.find("TIER[@TIER_ID='included']")
        assert tier is not None
        tier.set("PARENT_REF", "missing" if problem == "missing-parent" else "included")
    elif problem == "duplicate-id":
        early.set("ANNOTATION_ID", "a2")
    elif problem == "duplicate-slot":
        slot = root.find(".//TIME_SLOT[@TIME_SLOT_ID='ts1']")
        assert slot is not None
        slot.set("TIME_SLOT_ID", "ts0")
    else:
        for slot in root.iter("TIME_SLOT"):
            if problem == "unresolved-time":
                slot.attrib.pop("TIME_VALUE", None)
            elif slot.get("TIME_SLOT_ID") == "ts1":
                value = {"slot-order": "1500", "negative-time": "-1"}.get(
                    problem,
                    "bad integer",
                )
                slot.set("TIME_VALUE", value)
    diagnostics: list[Problem] = []
    doc = parse_eaf(etree.tostring(root), diagnostics=diagnostics)
    assert _ids(doc, "root") == ["a2", "a2" if problem == "duplicate-id" else "a1"]
    assert _ids(doc, "included") == ["c2", "c1"]
    assert code in {p.code for p in diagnostics}
    assert "annotation-order-normalized" not in {p.code for p in diagnostics}
    before = snapshot(doc)
    with pytest.raises(EditRejected):
        ConstraintEngine(doc).clear_value("a2")
    assert snapshot(doc) == before
    without_report = parse_eaf(etree.tostring(root))
    assert _ids(without_report, "root") == _ids(doc, "root")
    assert _ids(without_report, "included") == ["c2", "c1"]


def test_unused_slots_are_preserved_and_do_not_prevent_normalization() -> None:
    data = (
        (DATA / "out_of_order.eaf")
        .read_bytes()
        .replace(
            b"</TIME_ORDER>",
            b'<TIME_SLOT TIME_SLOT_ID="orphan" TIME_VALUE="2000"/></TIME_ORDER>',
        )
    )
    diagnostics: list[Problem] = []
    doc = parse_eaf(data, diagnostics=diagnostics)
    assert _ids(doc, "root") == ["a1", "a2"]
    assert doc.time_order[-1].id == "orphan"
    assert "unused-slot" in {p.code for p in diagnostics}
    check_invariants(doc)


def test_normalization_is_idempotent_and_does_not_clear_existing_diagnostics() -> None:
    previous = Problem("previous-report", Severity.WARNING, "existing caller diagnostic")
    diagnostics = [previous]
    first = read_eaf(DATA / "out_of_order.eaf", diagnostics=diagnostics)
    assert diagnostics[0] is previous and len(diagnostics) == 4
    data = write_eaf(first)
    later: list[Problem] = []
    assert write_eaf(parse_eaf(data, diagnostics=later)) == data
    assert later == []


def test_original_problem_fixture_keeps_its_validation_findings() -> None:
    diagnostics: list[Problem] = []
    doc = read_eaf(DATA / "problems.eaf", diagnostics=diagnostics)
    original_findings = validate(doc)
    assert diagnostics[: len(original_findings)] == original_findings
    assert {"overlap", "empty-interval", "unknown-type", "time-order"} <= {
        p.code for p in diagnostics
    }


def test_unrepresentable_display_time_does_not_prevent_lossless_import() -> None:
    huge = b"1" + b"0" * 400
    data = (
        (DATA / "out_of_order.eaf")
        .read_bytes()
        .replace(
            b'TIME_VALUE="1400"',
            b'TIME_VALUE="' + huge + b'"',
        )
    )
    diagnostics: list[Problem] = []
    doc = parse_eaf(data, diagnostics=diagnostics)
    assert _ids(doc, "root") == ["a2", "a1"]
    assert doc.time_order[-1].value == int(huge)
    assert [p.code for p in diagnostics] == ["normalization-skipped"]


@pytest.mark.perf
def test_normalizing_5000_reversed_annotations_meets_import_hard_limit() -> None:
    root = etree.fromstring(large_bytes(5000))
    for tier in root.iter("TIER"):
        tier[:] = reversed(list(tier))
    data = etree.tostring(root)
    start = perf_counter()
    doc = parse_eaf(data)
    elapsed = perf_counter() - start
    print(f"\nnormalize 5000 imported annotations: {elapsed:.3f} s (hard limit 3.0 s)")
    assert len(doc.annotations()) == 5000
    check_invariants(doc)
    assert elapsed < 3.0  # same open-time hard limit as tests/test_performance.py (§6.5)
