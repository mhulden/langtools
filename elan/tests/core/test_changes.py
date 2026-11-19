from __future__ import annotations

import pytest
from lxml import etree

from elan_ng.core.changes import (
    ChangeConflict,
    ChangeSet,
    Insert,
    Recorder,
    Remove,
    SetAttribute,
)
from elan_ng.core.constraints import ConstraintEngine
from elan_ng.core.model import Document, TimeSlot

from .helpers import simple, snapshot


def test_primitives_and_inverse_preserve_identity_order_and_opaque_residue() -> None:
    doc = simple()
    annotation = doc.annotations()[0]
    annotation.residue.children.append((0, etree.fromstring(b"<unknown>value</unknown>")))
    before = snapshot(doc)
    with Recorder(doc) as r:
        r.set(annotation, "value", "changed")
        r.set(annotation, "ext_ref", "er1")
        r.remove(doc.tiers[0].annotations, annotation)
        r.remove(doc.time_order, doc.time_order[1])
        r.remove(doc.time_order, doc.time_order[0])
        changes = r.finish("Delete", checked=False)
    assert snapshot(doc) == before
    changes.apply(doc)
    after = snapshot(doc)
    changes.inverse().apply(doc)
    assert snapshot(doc) == before
    changes.apply(doc)
    assert snapshot(doc) == after


def test_recorder_exception_rolls_back_partial_plan() -> None:
    doc = simple()
    before = snapshot(doc)
    with pytest.raises(RuntimeError), Recorder(doc) as r:
        r.set(doc.annotations()[0], "value", "temporary")
        r.remove(doc.time_order, doc.time_order[0])
        raise RuntimeError("planning failed")
    assert snapshot(doc) == before


def test_changeset_conflict_rolls_back_already_applied_operations() -> None:
    doc = simple()
    annotation = doc.annotations()[0]
    changes = ChangeSet(
        doc,
        (
            SetAttribute(annotation, "value", "original", "new"),
            Remove(doc.time_order, 0, TimeSlot("not-the-same-slot", 100), 2),
        ),
    )
    before = snapshot(doc)
    with pytest.raises(ChangeConflict):
        changes.apply(doc)
    assert snapshot(doc) == before


def test_validation_failure_is_atomic() -> None:
    doc = simple()
    before = snapshot(doc)
    changes = ChangeSet(doc, (SetAttribute(doc.time_order[0], "value", 100, 300),), checked=True)
    with pytest.raises(ChangeConflict):
        changes.apply(doc)
    assert snapshot(doc) == before


def test_document_binding_and_stale_list_preconditions() -> None:
    doc = simple()
    with pytest.raises(ChangeConflict):
        ChangeSet(doc).apply(Document())
    with pytest.raises(ChangeConflict):
        Insert(doc.time_order, -1, TimeSlot("bad"), 2).apply()
    with pytest.raises(ChangeConflict):
        Insert(doc.time_order, 0, TimeSlot("bad"), 1).apply()
    assert len(doc.time_order) == 2


def test_recorder_lifecycle_and_noop() -> None:
    doc = simple()
    r = Recorder(doc)
    with pytest.raises(ChangeConflict):
        r.set(doc, "author", "new")
    with r:
        r.set(doc, "author", "")
        assert r.finish("No op").operations == ()
    with pytest.raises(ChangeConflict):
        r.finish("Too late")


def test_unsorted_tier_is_an_invariant_failure_and_rolls_back() -> None:
    doc = simple()
    ConstraintEngine(doc).create("root", 300, 400).apply(doc)
    before = snapshot(doc)
    first, second = doc.tiers[0].annotations
    changes = ChangeSet(
        doc,
        (
            Remove(doc.tiers[0].annotations, 0, first, 2),
            Insert(doc.tiers[0].annotations, 1, first, 1),
        ),
        checked=True,
    )
    with pytest.raises(ChangeConflict, match="annotation-order"):
        changes.apply(doc)
    assert snapshot(doc) == before
    assert doc.tiers[0].annotations == [first, second]
