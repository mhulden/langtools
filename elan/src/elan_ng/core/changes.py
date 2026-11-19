"""Reversible, identity-preserving primitives for an in-memory document.

Operations retain the original objects, including opaque XML residue. A change set is
bound to one document and rolls back applied operations on failure. It is session data,
not a serialization format. Plan edits with Recorder; leaving its context always restores
the starting state, whether planning succeeds or raises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from types import TracebackType
from typing import Protocol, TypeVar

from elan_ng.core.model import AlignableAnnotation, Document
from elan_ng.core.validate import validate

T = TypeVar("T")


class ChangeConflict(ValueError):
    """The target no longer matches an operation's expected state."""


class Operation(Protocol):
    def apply(self) -> None: ...

    def inverse(self) -> Operation: ...


@dataclass(frozen=True)
class SetAttribute:
    target: object
    name: str
    before: object
    after: object

    def apply(self) -> None:
        current = getattr(self.target, self.name)
        if current is not self.before and current != self.before:
            raise ChangeConflict(f"stale attribute: {self.name}")
        setattr(self.target, self.name, self.after)

    def inverse(self) -> SetAttribute:
        return SetAttribute(self.target, self.name, self.after, self.before)


@dataclass(frozen=True)
class Insert[T]:
    target: list[T]
    index: int
    item: T
    length: int

    def apply(self) -> None:
        if len(self.target) != self.length or not 0 <= self.index <= self.length:
            raise ChangeConflict("stale list insertion")
        self.target.insert(self.index, self.item)

    def inverse(self) -> Remove[T]:
        return Remove(self.target, self.index, self.item, self.length + 1)


@dataclass(frozen=True)
class Remove[T]:
    target: list[T]
    index: int
    item: T
    length: int

    def apply(self) -> None:
        if (
            len(self.target) != self.length
            or not 0 <= self.index < self.length
            or self.target[self.index] is not self.item
        ):
            raise ChangeConflict("stale list removal")
        self.target.pop(self.index)

    def inverse(self) -> Insert[T]:
        return Insert(self.target, self.index, self.item, self.length - 1)


def check_invariants(doc: Document) -> None:
    # Loaded unused slots are legal session state: I3 removes them on save. Do not
    # silently prune unrelated slots while editing, or exact undo would lose data.
    problems = [p for p in validate(doc) if p.code != "unused-slot"]
    positions = {slot: i for i, slot in enumerate(doc.time_order)}
    reversed_slots = any(
        positions.get(a.begin, -1) >= positions.get(a.end, -1)
        for a in doc.annotations()
        if isinstance(a, AlignableAnnotation)
    )
    unordered_annotations = any(
        first > second
        for tier in doc.tiers
        for first, second in pairwise(
            [
                positions.get(a.begin, -1)
                for a in tier.annotations
                if isinstance(a, AlignableAnnotation)
            ]
        )
    )
    details = [p.code for p in problems]
    if reversed_slots:
        details.append("slot-order")
    if unordered_annotations:
        details.append("annotation-order")
    if details:
        raise ChangeConflict(f"document invariants failed: {', '.join(details)}")


@dataclass(frozen=True)
class ChangeSet:
    document: Document
    operations: tuple[Operation, ...] = ()
    label: str = "Edit"
    checked: bool = False

    def apply(self, document: Document) -> None:
        if document is not self.document:
            raise ChangeConflict("change set belongs to another document")
        done: list[Operation] = []
        try:
            for operation in self.operations:
                operation.apply()
                done.append(operation)
            if self.checked:
                check_invariants(document)
        except Exception:
            for operation in reversed(done):
                operation.inverse().apply()
            raise

    def inverse(self) -> ChangeSet:
        return ChangeSet(
            self.document,
            tuple(op.inverse() for op in reversed(self.operations)),
            self.label,
            self.checked,
        )


@dataclass
class Recorder:
    document: Document
    _operations: list[Operation] = field(default_factory=list, init=False)
    _active: bool = field(default=False, init=False)

    def __enter__(self) -> Recorder:
        if self._active or self._operations:
            raise ChangeConflict("recorder cannot be reused")
        self._active = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            for operation in reversed(self._operations):
                operation.inverse().apply()
        finally:
            self._active = False

    def record(self, operation: Operation) -> None:
        if not self._active:
            raise ChangeConflict("use recorder inside its context")
        operation.apply()
        self._operations.append(operation)

    def set(self, target: object, name: str, value: object) -> None:
        before = getattr(target, name)
        if before != value:
            self.record(SetAttribute(target, name, before, value))

    def insert(self, target: list[T], index: int, item: T) -> None:
        self.record(Insert(target, index, item, len(target)))

    def remove(self, target: list[T], item: T) -> None:
        index = next(i for i, existing in enumerate(target) if existing is item)
        self.record(Remove(target, index, item, len(target)))

    def finish(self, label: str, *, checked: bool = True) -> ChangeSet:
        if not self._active:
            raise ChangeConflict("recorder is not active")
        if checked:
            check_invariants(self.document)
        return ChangeSet(self.document, tuple(self._operations), label, checked)
