"""EAF persistence is semantic equality; undo separately requires exact session state."""

from pathlib import Path

import pytest

from elan_ng.core.changes import check_invariants
from elan_ng.core.constraints import ConstraintEngine
from elan_ng.core.undo import UndoStack
from elan_ng.io.eaf_reader import parse_eaf, read_eaf
from elan_ng.io.eaf_writer import save_eaf, write_eaf

from .helpers import simple, snapshot
from eafcompare import canonical
from support import DATA


@pytest.mark.parametrize("fixture", ["minimal.eaf", "edge_cases.eaf", "nested_subdivision_4.eaf"])
def test_edited_document_saves_and_loads_without_losing_semantics(
    fixture: str,
    tmp_path: Path,
) -> None:
    doc = read_eaf(DATA / fixture)
    engine, stack = ConstraintEngine(doc), UndoStack(doc)
    initial = snapshot(doc)
    stack.execute(engine.create(doc.tiers[0].id, 10000, 11000, "ñ <&>"))
    created_id = next(a.id for a in doc.annotations() if a.value == "ñ <&>")
    stack.execute(engine.retime(created_id, 12000, 13000))
    stack.execute(engine.clear_value(doc.annotations()[0].id))
    edited = snapshot(doc)
    data = write_eaf(doc)
    assert snapshot(doc) == edited  # non-mutating serialization
    assert canonical(write_eaf(parse_eaf(data))) == canonical(data)
    while stack.can_undo:
        stack.undo()
    assert snapshot(doc) == initial
    while stack.can_redo:
        stack.redo()
    assert snapshot(doc) == edited
    # Real save can add URN/date metadata: compare that saved state semantically,
    # while confirming save does not clear the undo history.
    target = tmp_path / "edited.eaf"
    save_eaf(doc, target)
    stack.mark_saved()
    loaded = read_eaf(target)
    assert canonical(write_eaf(loaded)) == canonical(target.read_bytes())
    check_invariants(loaded)
    assert stack.can_undo and not stack.dirty
    stack.undo()
    assert stack.dirty


def test_save_adds_header_metadata_without_breaking_existing_undo(tmp_path: Path) -> None:
    doc = simple()  # no URN or lastUsedAnnotationId yet
    engine, stack = ConstraintEngine(doc), UndoStack(doc)
    stack.execute(engine.create("root", 300, 400))
    save_eaf(doc, tmp_path / "new.eaf")
    stack.mark_saved()
    saved_header = snapshot(doc.header)
    assert stack.undo() and len(doc.annotations()) == 1
    assert snapshot(doc.header) == saved_header and stack.dirty
    assert stack.redo() and len(doc.annotations()) == 2
    assert snapshot(doc.header) == saved_header and not stack.dirty
