"""Per-document linear undo history; saving marks a point without clearing history."""

from __future__ import annotations

from elan_ng.core.changes import ChangeConflict, ChangeSet
from elan_ng.core.model import Document


class UndoStack:
    def __init__(self, document: Document) -> None:
        self.document = document
        self._history: list[ChangeSet] = []
        self._position = 0
        self._saved: int | None = 0

    @property
    def can_undo(self) -> bool:
        return self._position > 0

    @property
    def can_redo(self) -> bool:
        return self._position < len(self._history)

    @property
    def dirty(self) -> bool:
        return self._saved != self._position

    def mark_saved(self) -> None:
        self._saved = self._position

    def execute(self, changes: ChangeSet) -> None:
        if changes.document is not self.document:
            raise ChangeConflict("undo history belongs to another document")
        if not changes.operations:
            return
        changes.apply(self.document)
        if self._saved is not None and self._saved > self._position:
            self._saved = None
        del self._history[self._position :]
        self._history.append(changes)
        self._position += 1

    def undo(self) -> bool:
        if not self.can_undo:
            return False
        self._history[self._position - 1].inverse().apply(self.document)
        self._position -= 1
        return True

    def redo(self) -> bool:
        if not self.can_redo:
            return False
        self._history[self._position].apply(self.document)
        self._position += 1
        return True

    def clear(self) -> None:
        """Discard session history (e.g. after closing a document)."""
        self._history.clear()
        self._position = 0
        self._saved = 0
