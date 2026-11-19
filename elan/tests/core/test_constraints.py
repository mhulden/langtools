from __future__ import annotations

import pytest

from elan_ng.core.changes import check_invariants
from elan_ng.core.constraints import ConstraintEngine, EditRejected
from elan_ng.core.model import (
    AlignableAnnotation,
    Language,
    RefAnnotation,
    RefLink,
    RefLinkSet,
    Stereotype,
    Tier,
    TierType,
    TimeSlot,
)
from elan_ng.core.structure import analyze
from elan_ng.core.undo import UndoStack
from elan_ng.io.eaf_reader import parse_eaf, read_eaf
from elan_ng.io.eaf_writer import write_eaf

from .helpers import simple, snapshot
from support import DATA


def test_R1_creates_two_new_slots_sorted_and_exact_inverse() -> None:
    doc = simple()
    engine = ConstraintEngine(doc)
    before = snapshot(doc)
    changes = engine.create("root", 0, 100, "héllo<&>")
    assert snapshot(doc) == before  # planning has no model side effects
    changes.apply(doc)
    assert [a.value for a in doc.annotations()] == ["héllo<&>", "original"]
    assert [s.value for s in doc.time_order] == [0, 100, 100, 200]
    assert doc.annotations()[0].end is not doc.annotations()[1].begin
    check_invariants(doc)
    changes.inverse().apply(doc)
    assert snapshot(doc) == before


@pytest.mark.parametrize("begin,end", [(10, 10), (20, 10)])
def test_R2_rejects_empty_or_reversed_selection(begin: int, end: int) -> None:
    doc = simple()
    before = snapshot(doc)
    with pytest.raises(EditRejected, match="R2"):
        ConstraintEngine(doc).create("root", begin, end)
    assert snapshot(doc) == before


def test_R1_ids_skip_other_xml_ids_and_are_not_reused_after_undo() -> None:
    doc = simple()
    doc.languages.append(Language("a2"))
    engine, stack = ConstraintEngine(doc), UndoStack(doc)
    stack.execute(engine.create("root", 300, 400))
    assert doc.annotations()[-1].id == "a3"
    stack.undo()
    stack.execute(engine.create("root", 300, 400))
    assert doc.annotations()[-1].id == "a4"
    assert doc.header.get_property("lastUsedAnnotationId") is None  # written on save


def test_D1_D2_cascade_deletes_entire_tree_and_restores_residue() -> None:
    doc = read_eaf(DATA / "edge_cases.eaf")
    doc.ref_link_sets.clear()  # D6 link repair is explicitly outside M2a.
    before = snapshot(doc)
    structure = analyze(doc)
    target = doc.annotation_index()["a1"][1]
    descendants = {target}
    pending = [target]
    while pending:
        for child in structure.children.get(pending.pop(), []):
            descendants.add(child)
            pending.append(child)
    changes = ConstraintEngine(doc).delete("a1")
    assert snapshot(doc) == before
    changes.apply(doc)
    assert not descendants.intersection(doc.annotations())
    check_invariants(doc)
    changes.inverse().apply(doc)
    assert snapshot(doc) == before


def test_D2_keeps_shared_slots_and_unrelated_unused_slots() -> None:
    doc = simple()
    first, last = doc.time_order
    extra = TimeSlot("ts3", 300)
    orphan = TimeSlot("orphan", 400)
    doc.time_order.extend([extra, orphan])
    doc.tiers[0].annotations.append(AlignableAnnotation("a2", begin=last, end=extra))
    changes = ConstraintEngine(doc).delete("a1")
    changes.apply(doc)
    assert doc.time_order == [last, extra, orphan]
    changes.inverse().apply(doc)
    assert doc.time_order == [first, last, extra, orphan]


def test_D7_clears_cve_ref_without_changing_structure() -> None:
    doc = read_eaf(DATA / "minimal.eaf")
    annotation = doc.annotation_index()["a5"][1]
    before = snapshot(doc)
    changes = ConstraintEngine(doc).clear_value("a5")
    changes.apply(doc)
    assert annotation.value == "" and annotation.cve_ref is None
    assert len(doc.annotations()) == 5
    changes.inverse().apply(doc)
    assert snapshot(doc) == before


def test_M1_shared_boundaries_move_users_and_interpolated_descendants() -> None:
    doc = read_eaf(DATA / "minimal.eaf")
    engine = ConstraintEngine(doc)
    before = snapshot(doc)
    changes = engine.retime("a1", 900, 2600)
    assert snapshot(doc) == before
    changes.apply(doc)
    structure = analyze(doc)
    assert structure.times[doc.annotation_index()["a2"][1]] == (900, 1750)
    assert structure.times[doc.annotation_index()["a3"][1]] == (1750, 2600)
    changes.inverse().apply(doc)
    assert snapshot(doc) == before


def test_M1_included_in_retime_and_parent_boundary_rejection() -> None:
    doc = read_eaf(DATA / "edge_cases.eaf")
    engine = ConstraintEngine(doc)
    annotation = doc.annotation_index()["a15"][1]
    changes = engine.retime("a15", 100, 500)
    changes.apply(doc)
    assert analyze(doc).times[annotation] == (100, 500)
    before = snapshot(doc)
    with pytest.raises(EditRejected):
        engine.retime("a15", 3100, 3200)
    assert snapshot(doc) == before


@pytest.mark.parametrize("begin,end", [(200, 200), (300, 200)])
def test_M9_rejects_invalid_duration_atomically(begin: int, end: int) -> None:
    doc = simple()
    before = snapshot(doc)
    with pytest.raises(EditRejected, match="M9"):
        ConstraintEngine(doc).retime("a1", begin, end)
    assert snapshot(doc) == before


def test_M1_reorders_slots_across_other_root_trees() -> None:
    doc = simple()
    first, last = TimeSlot("ts3", 300), TimeSlot("ts4", 400)
    doc.time_order.extend([first, last])
    doc.tiers.append(
        Tier(
            "other",
            "root",
            annotations=[
                AlignableAnnotation("a2", begin=first, end=last),
            ],
        )
    )
    changes = ConstraintEngine(doc).retime("a1", 350, 450)
    before = snapshot(doc)
    changes.apply(doc)
    assert [s.value for s in doc.time_order] == [300, 350, 400, 450]
    changes.inverse().apply(doc)
    assert snapshot(doc) == before


def test_B2_slot_placement_respects_aligned_neighbours_before_display_time() -> None:
    doc = read_eaf(DATA / "edge_cases.eaf")
    doc.tiers.append(Tier("free", "utterance"))
    # Use the actual independent tier type rather than depending on fixture spelling.
    doc.tiers[-1].type_ref = doc.tiers[0].type_ref
    before = snapshot(doc)
    changes = ConstraintEngine(doc).create("free", 2000, 2100)
    changes.apply(doc)
    aligned = [s.value for s in doc.time_order if s.value is not None]
    assert aligned == sorted(aligned)
    check_invariants(doc)
    changes.inverse().apply(doc)
    assert snapshot(doc) == before


def test_B2_equal_boundaries_and_unaligned_slots_in_search_window() -> None:
    doc = read_eaf(DATA / "minimal.eaf")
    doc.tiers.append(Tier("free", doc.tiers[0].type_ref))
    changes = ConstraintEngine(doc).create("free", 1700, 1800)
    changes.apply(doc)
    slots = doc.time_order
    assert [s.value for s in slots] == [1000, 1700, None, 1800, 2500]
    check_invariants(doc)


def test_unsupported_collisions_subdivision_and_cross_links_are_explicit() -> None:
    doc = read_eaf(DATA / "minimal.eaf")
    engine = ConstraintEngine(doc)
    before = snapshot(doc)
    for rule, action in [
        ("R3-R5", lambda: engine.create(doc.tiers[0].id, 1500, 2000)),
        ("R6-R12", lambda: engine.create(doc.tiers[1].id, 1500, 1600)),
        ("D3", lambda: engine.delete("a2")),
        ("M7/M8", lambda: engine.retime("a2", 1100, 1600)),
        ("M1", lambda: engine.retime("a4", 1100, 1600)),
        ("M10", lambda: engine.retime("a1", -10, 2000)),
    ]:
        with pytest.raises(EditRejected) as error:
            action()
        assert error.value.rule == rule
        assert snapshot(doc) == before
    doc.ref_link_sets.append(RefLinkSet({}, [RefLink("cross", {"REF1": "a1", "REF2": "a2"})]))
    with pytest.raises(EditRejected, match="D6"):
        engine.delete("a1")


def test_M2_translation_requiring_independent_descendant_slots_is_rejected() -> None:
    doc = read_eaf(DATA / "edge_cases.eaf")
    before = snapshot(doc)
    with pytest.raises(EditRejected, match="M2"):
        ConstraintEngine(doc).retime("a1", 100, 3100)
    assert snapshot(doc) == before


def test_M6_collision_is_rejected_instead_of_trimming_sibling() -> None:
    doc = simple()
    engine, stack = ConstraintEngine(doc), UndoStack(doc)
    stack.execute(engine.create("root", 300, 400))
    before = snapshot(doc)
    with pytest.raises(EditRejected):
        engine.retime("a1", 150, 350)
    assert snapshot(doc) == before


def test_D4_direct_symbolic_subdivision_delete_is_rejected() -> None:
    doc = simple()
    doc.tier_types.append(TierType("symbolic", constraint=Stereotype.SYMBOLIC_SUBDIVISION))
    doc.tiers.append(
        Tier(
            "symbolic",
            "symbolic",
            parent_ref="root",
            annotations=[
                RefAnnotation("a2", ref="a1"),
            ],
        )
    )
    with pytest.raises(EditRejected, match="D4"):
        ConstraintEngine(doc).delete("a2")


def test_D2_deletes_included_in_endpoints_without_touching_parent() -> None:
    doc = read_eaf(DATA / "edge_cases.eaf")
    before = snapshot(doc)
    annotation = doc.annotation_index()["a15"][1]
    assert isinstance(annotation, AlignableAnnotation)
    endpoints = {annotation.begin, annotation.end}
    changes = ConstraintEngine(doc).delete("a15")
    changes.apply(doc)
    assert not endpoints.intersection(doc.time_order)
    assert "a1" in doc.annotation_index()
    changes.inverse().apply(doc)
    assert snapshot(doc) == before


def test_M1_shared_slot_moves_adjacent_annotation_boundary() -> None:
    doc = simple()
    first, shared = doc.time_order
    last = TimeSlot("ts3", 300)
    doc.time_order.append(last)
    doc.tiers[0].annotations.append(AlignableAnnotation("a2", begin=shared, end=last))
    changes = ConstraintEngine(doc).retime("a1", 100, 250)
    changes.apply(doc)
    assert analyze(doc).times[doc.annotations()[1]] == (250, 300)
    assert doc.annotations()[0].begin is first
    check_invariants(doc)


def test_abandoned_plan_reserves_its_id_and_retime_noop_is_empty() -> None:
    doc = simple()
    engine = ConstraintEngine(doc)
    engine.create("root", 300, 400)  # deliberately not applied
    changes = engine.create("root", 300, 400)
    changes.apply(doc)
    assert doc.annotations()[-1].id == "a3"
    assert not engine.retime("a1", 100, 200).operations


@pytest.mark.parametrize("action", ["create", "delete", "clear", "retime"])
def test_unknown_targets_are_rejected_without_mutating_document(action: str) -> None:
    doc = simple()
    before = snapshot(doc)
    engine = ConstraintEngine(doc)
    with pytest.raises(EditRejected, match="target"):
        if action == "create":
            engine.create("missing", 300, 400)
        elif action == "delete":
            engine.delete("missing")
        elif action == "clear":
            engine.clear_value("missing")
        else:
            engine.retime("missing", 300, 400)
    assert snapshot(doc) == before


@pytest.mark.parametrize("problem", ["reversed-order", "unresolved-times"])
def test_malformed_input_is_rejected_without_repairing_or_dropping_data(problem: str) -> None:
    doc = simple()
    if problem == "reversed-order":
        doc.time_order.reverse()
    else:
        for slot in doc.time_order:
            slot.value = None
    before = snapshot(doc)
    with pytest.raises(EditRejected, match="precondition"):
        ConstraintEngine(doc).clear_value("a1")
    assert snapshot(doc) == before


@pytest.mark.parametrize("kind", ["root", "included", "shared-root"])
@pytest.mark.parametrize("target,begin,end", [("a1", 500, 600), ("a2", 0, 50)])
def test_M1_jump_over_sibling_preserves_tier_order_and_exact_undo(
    kind: str,
    target: str,
    begin: int,
    end: int,
) -> None:
    doc = simple()
    ConstraintEngine(doc).create("root", 300, 400).apply(doc)
    tier = doc.tiers[0]
    first, second = tier.annotations
    assert isinstance(first, AlignableAnnotation) and isinstance(second, AlignableAnnotation)
    if kind == "included":
        outer_begin, outer_end = TimeSlot("outer-begin", 0), TimeSlot("outer-end", 1000)
        doc.time_order.insert(0, outer_begin)
        doc.time_order.append(outer_end)
        tier.parent_ref = "parent"
        tier.type_ref = "included"
        doc.tier_types.append(TierType("included", constraint=Stereotype.INCLUDED_IN))
        doc.tiers.insert(
            0,
            Tier(
                "parent",
                "root",
                annotations=[
                    AlignableAnnotation("parent-ann", begin=outer_begin, end=outer_end),
                ],
            ),
        )
    elif kind == "shared-root":
        doc.tiers.append(
            Tier(
                "shared",
                "root",
                annotations=[
                    AlignableAnnotation("shared1", begin=first.begin, end=first.end),
                    AlignableAnnotation("shared2", begin=second.begin, end=second.end),
                ],
            )
        )
    engine, stack = ConstraintEngine(doc), UndoStack(doc)
    before = snapshot(doc)
    changes = engine.retime(target, begin, end)
    assert snapshot(doc) == before
    changes.apply(doc)
    after = snapshot(doc)
    assert [a.id for a in tier.annotations] == ["a2", "a1"]
    if kind == "shared-root":
        assert [a.id for a in doc.tiers[-1].annotations] == ["shared2", "shared1"]
    check_invariants(doc)
    loaded = parse_eaf(write_eaf(doc))
    loaded_tier = loaded.tier("root")
    assert loaded_tier is not None
    assert [a.id for a in loaded_tier.annotations] == ["a2", "a1"]
    changes.inverse().apply(doc)
    assert snapshot(doc) == before
    stack.execute(changes)
    assert snapshot(doc) == after
    assert stack.undo() and snapshot(doc) == before
    assert stack.redo() and snapshot(doc) == after
    if kind != "included":
        new_begin, new_end = (450, 475) if target == "a1" else (75, 95)
        stack.execute(engine.create("root", new_begin, new_end, "inserted"))
        assert [a.value for a in tier.annotations][1] == "inserted"
        check_invariants(doc)
