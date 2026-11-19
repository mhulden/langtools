"""M2a edit planning from REIMPLEMENTATION.md §2.2; no ELAN source is used.

Implemented: R1/R2, D1/D2/D7 and non-colliding M1/M9. Other rule families are
explicitly rejected, including edits that would require their propagation semantics.
Plans leave the document untouched; execute them through a per-document UndoStack.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass

from elan_ng.core.changes import ChangeConflict, ChangeSet, Recorder, check_invariants
from elan_ng.core.ids import last_used_annotation_id
from elan_ng.core.model import (
    AlignableAnnotation,
    Annotation,
    Document,
    Stereotype,
    Tier,
    TimeSlot,
)
from elan_ng.core.structure import analyze


class EditRejected(ValueError):
    def __init__(self, rule: str, reason: str) -> None:
        self.rule = rule
        super().__init__(f"{rule}: {reason}")


def _strings(value: object) -> set[str]:
    """Conservatively reserve strings throughout the model, including xsd:ID fields.

    This also skips IDs used by languages, slots, vocabularies and preserved attributes,
    unlike annotation-only allocation. Opaque XML nodes are never inspected or copied.
    """
    if isinstance(value, str):
        return {value}
    if is_dataclass(value) and not isinstance(value, type):
        return set().union(*(_strings(getattr(value, f.name)) for f in fields(value)))
    if isinstance(value, (list, tuple)):
        return set().union(*(_strings(item) for item in value))
    if isinstance(value, dict):
        return set().union(*(_strings(item) for item in value.values()))
    return set()


def slot_insertion_index(
    doc: Document, value: int, display_times: dict[TimeSlot, float] | None = None
) -> int:
    """B2: aligned neighbours bound the search, then consider unaligned display times.

    Interpolated times need not be monotonic across different tier trees. Searching the
    entire display-time array can therefore put 2000 ms before an aligned 1500 ms slot.
    Equal aligned values precede the inserted slot; existing slot order stays intact.
    """
    lower = 0
    upper = len(doc.time_order)
    for i, slot in enumerate(doc.time_order):
        if slot.value is None:
            continue
        if slot.value <= value:
            lower = i + 1
        else:
            upper = i
            break
    times = analyze(doc).slot_times if display_times is None else display_times
    for i in range(lower, upper):
        if times.get(doc.time_order[i], float("inf")) > value:
            return i
    return upper


class ConstraintEngine:
    """One engine per document session, so abandoned/undone IDs are never reused."""

    def __init__(self, document: Document) -> None:
        self.document = document
        self._last_annotation = last_used_annotation_id(document)
        self._last_slot = 0
        self._reserved: set[str] = set()

    def _ready(self) -> None:
        try:
            check_invariants(self.document)
        except ChangeConflict as exc:
            raise EditRejected("precondition", str(exc)) from exc
        times = analyze(self.document).times
        if any(a not in times for a in self.document.annotations()):
            raise EditRejected("precondition", "annotation times cannot be resolved")

    def _tier(self, tier_id: str) -> Tier:
        tier = self.document.tier(tier_id)
        if tier is None:
            raise EditRejected("target", f"unknown tier {tier_id!r}")
        return tier

    def _annotation(self, annotation_id: str) -> tuple[Tier, AlignableAnnotation | Annotation]:
        entry = self.document.annotation_index().get(annotation_id)
        if entry is None:
            raise EditRejected("target", f"unknown annotation {annotation_id!r}")
        return entry

    def _allocate(self, *, slot: bool = False) -> str:
        self._reserved.update(_strings(self.document))
        while True:
            if slot:
                self._last_slot += 1
                candidate = f"ts{self._last_slot}"
            else:
                self._last_annotation = (
                    max(self._last_annotation, last_used_annotation_id(self.document)) + 1
                )
                candidate = f"a{self._last_annotation}"
            if candidate not in self._reserved:
                self._reserved.add(candidate)
                return candidate

    def _finish(self, recorder: Recorder, label: str, rule: str) -> ChangeSet:
        try:
            return recorder.finish(label)
        except ChangeConflict as exc:
            raise EditRejected(rule, str(exc)) from exc

    def unsupported(self, rule: str) -> None:
        raise EditRejected(rule, "not implemented in M2a")

    def create(self, tier_id: str, begin: int, end: int, value: str = "") -> ChangeSet:
        self._ready()
        tier = self._tier(tier_id)
        if tier.parent_ref is not None:
            self.unsupported("R6-R12")
        if begin >= end:
            raise EditRejected("R2", "selection must have positive duration")
        if begin < 0:
            self.unsupported("M10")
        structure = analyze(self.document)
        if any(b < end and begin < e for a in tier.annotations for b, e in [structure.times[a]]):
            self.unsupported("R3-R5")
        annotation_id = self._allocate()
        first = TimeSlot(self._allocate(slot=True), begin)
        last = TimeSlot(self._allocate(slot=True), end)
        annotation = AlignableAnnotation(annotation_id, value, begin=first, end=last)
        with Recorder(self.document) as recorder:
            for slot in (first, last):
                assert slot.value is not None
                recorder.insert(
                    self.document.time_order, slot_insertion_index(self.document, slot.value), slot
                )
            position = next(
                (i for i, a in enumerate(tier.annotations) if structure.times[a][0] >= begin),
                len(tier.annotations),
            )
            recorder.insert(tier.annotations, position, annotation)
            # Keep allocation high-water state in this session. The existing writer
            # updates lastUsedAnnotationId on save (§3.1.3); undo must not capture
            # header lists that saving may independently extend with URN metadata.
            return self._finish(recorder, "Create annotation", "R1")

    def clear_value(self, annotation_id: str) -> ChangeSet:
        self._ready()
        _, annotation = self._annotation(annotation_id)
        with Recorder(self.document) as recorder:
            recorder.set(annotation, "value", "")
            recorder.set(annotation, "cve_ref", None)
            return self._finish(recorder, "Clear annotation value", "D7")

    def delete(self, annotation_id: str) -> ChangeSet:
        self._ready()
        tier, annotation = self._annotation(annotation_id)
        stereotype = self.document.stereotype_of(tier)
        if stereotype is Stereotype.TIME_SUBDIVISION:
            self.unsupported("D3")
        if stereotype is Stereotype.SYMBOLIC_SUBDIVISION:
            self.unsupported("D4")
        structure = analyze(self.document)
        removed = {annotation}
        pending = [annotation]
        while pending:
            for child in structure.children.get(pending.pop(), []):
                if child not in removed:
                    removed.add(child)
                    pending.append(child)
        ids = {a.id for a in removed}
        if any(
            ids.intersection(link.refs()) for s in self.document.ref_link_sets for link in s.links
        ):
            self.unsupported("D6")
        endpoints = {
            s for a in removed if isinstance(a, AlignableAnnotation) for s in (a.begin, a.end)
        }
        with Recorder(self.document) as recorder:
            for affected_tier in self.document.tiers:
                for existing in list(affected_tier.annotations):
                    if existing in removed:
                        recorder.remove(affected_tier.annotations, existing)
            used = {
                s
                for a in self.document.annotations()
                if isinstance(a, AlignableAnnotation)
                for s in (a.begin, a.end)
            }
            for slot in list(self.document.time_order):
                if slot in endpoints and slot not in used:
                    recorder.remove(self.document.time_order, slot)
            return self._finish(recorder, "Delete annotation and descendants", "D1/D2")

    def retime(self, annotation_id: str, begin: int, end: int) -> ChangeSet:
        self._ready()
        tier, annotation = self._annotation(annotation_id)
        if begin >= end:
            raise EditRejected("M9", "begin must precede end")
        if begin < 0:
            self.unsupported("M10")
        stereotype = self.document.stereotype_of(tier)
        if not isinstance(annotation, AlignableAnnotation):
            raise EditRejected("M1", "reference annotations cannot be retimed")
        if stereotype not in (None, Stereotype.INCLUDED_IN):
            self.unsupported("M7/M8")
        first, last = annotation.begin, annotation.end
        if first.value is None or last.value is None:
            raise EditRejected("M1", "unaligned boundaries cannot be retimed directly")
        if (first.value, last.value) == (begin, end):
            return ChangeSet(self.document, label="Change annotation time", checked=True)
        before = analyze(self.document)
        descendants: set[Annotation] = set()
        pending: list[Annotation] = [annotation]
        while pending:
            for child in before.children.get(pending.pop(), []):
                if child not in descendants:
                    descendants.add(child)
                    pending.append(child)
        if begin - first.value == end - last.value != 0 and any(
            isinstance(a, AlignableAnnotation)
            and any(s.value is not None and s not in (first, last) for s in (a.begin, a.end))
            for a in descendants
        ):
            self.unsupported("M2")
        with Recorder(self.document) as recorder:
            recorder.set(first, "value", begin)
            recorder.set(last, "value", end)
            # Resolve while both anchors are still listed. Resolving halfway through
            # reinsertion would strand unaligned subdivision slots without an anchor.
            display_times = analyze(self.document).slot_times
            for slot in (first, last):
                recorder.remove(self.document.time_order, slot)
            for slot in (first, last):
                assert slot.value is not None
                recorder.insert(
                    self.document.time_order,
                    slot_insertion_index(self.document, slot.value, display_times),
                    slot,
                )
            after = analyze(self.document)
            if before.parent != after.parent:
                raise EditRejected("M3/M4", "retiming would reparent or trim descendants")
            # Slot users on other tiers can move too. Record every changed position
            # so both the edited tier and shared-slot users keep §3.1.3 order, while
            # the inverse restores the exact original list objects and ordering.
            positions = {slot: i for i, slot in enumerate(self.document.time_order)}
            for affected_tier in self.document.tiers:
                ordered = sorted(
                    affected_tier.annotations,
                    key=lambda a: positions[a.begin] if isinstance(a, AlignableAnnotation) else -1,
                )
                for index, existing in enumerate(ordered):
                    if affected_tier.annotations[index] is not existing:
                        recorder.remove(affected_tier.annotations, existing)
                        recorder.insert(affected_tier.annotations, index, existing)
            return self._finish(recorder, "Change annotation time", "M1/M3-M6")
