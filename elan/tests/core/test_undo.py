import pytest

from elan_ng.core.changes import ChangeConflict
from elan_ng.core.constraints import ConstraintEngine
from elan_ng.core.undo import UndoStack

from .helpers import simple, snapshot


def test_history_undo_redo_save_and_branching() -> None:
    doc = simple()
    engine, stack = ConstraintEngine(doc), UndoStack(doc)
    before = snapshot(doc)
    assert not stack.undo() and not stack.redo() and not stack.dirty
    stack.execute(engine.create("root", 300, 400, "second"))
    after = snapshot(doc)
    assert stack.dirty
    stack.mark_saved()
    assert not stack.dirty
    assert stack.undo() and snapshot(doc) == before and stack.dirty
    assert stack.redo() and snapshot(doc) == after and not stack.dirty
    stack.undo()
    stack.execute(engine.clear_value("a1"))
    assert stack.dirty and not stack.can_redo
    stack.undo()
    assert stack.dirty  # the saved branch was discarded


def test_histories_are_separate_and_failed_execute_keeps_redo() -> None:
    doc = simple()
    engine, stack = ConstraintEngine(doc), UndoStack(doc)
    changes = engine.clear_value("a1")
    with pytest.raises(ChangeConflict):
        UndoStack(simple()).execute(changes)
    stack.execute(changes)
    stack.undo()
    stale = engine.retime("a1", 110, 210)
    doc.time_order.pop()
    with pytest.raises(ChangeConflict):
        stack.execute(stale)
    assert stack.can_redo and not stack.can_undo


def test_noop_does_not_dirty_or_discard_redo_and_clear_drops_history() -> None:
    doc = simple()
    engine, stack = ConstraintEngine(doc), UndoStack(doc)
    stack.execute(engine.clear_value("a1"))
    stack.mark_saved()
    stack.execute(engine.clear_value("a1"))
    assert not stack.dirty
    stack.clear()
    assert not stack.can_undo and not stack.can_redo and not stack.dirty


def test_failed_undo_retains_history_and_does_not_change_other_fields() -> None:
    doc = simple()
    engine, stack = ConstraintEngine(doc), UndoStack(doc)
    stack.execute(engine.clear_value("a1"))
    doc.annotations()[0].value = "external change"
    before = snapshot(doc)
    with pytest.raises(ChangeConflict):
        stack.undo()
    assert snapshot(doc) == before and stack.can_undo and not stack.can_redo
