"""Read EAF 2.7-3.0 into the core model (REIMPLEMENTATION.md §3.1, §3.2).

Everything the model does not cover is kept as residue. Pre-2.8 controlled vocabularies
(CV_ENTRY) are converted to the multilingual form with language "und", which is what
ELAN does when it saves an old file as 3.0.
"""

from __future__ import annotations

import copy
import uuid
from collections import Counter
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path

from elan_ng.core.model import (
    AlignableAnnotation,
    Constraint,
    ControlledVocabulary,
    CVEntry,
    CVEValue,
    Document,
    ExternalRef,
    Header,
    LangText,
    Language,
    LexiconRef,
    License,
    LinkedFileDescriptor,
    Locale,
    MediaDescriptor,
    Property,
    RefAnnotation,
    RefLink,
    RefLinkSet,
    Residue,
    Stereotype,
    Tier,
    TierType,
    TimeSlot,
)
from elan_ng.core.structure import analyze
from elan_ng.core.validate import Problem, Severity, validate
from elan_ng.io.xmlutil import (
    Element,
    keep_text_residue,
    parse,
    split_attrs,
    walk_children,
)

UND_LANGUAGE = Language(
    id="und",
    definition="http://cdb.iso.org/lg/CDB-00130975-001",
    label="undetermined (und)",
)


class EAFError(ValueError):
    """The file is not an EAF document we can read."""


def read_eaf(path: str | Path, *, diagnostics: list[Problem] | None = None) -> Document:
    return parse_eaf(Path(path).read_bytes(), diagnostics=diagnostics)


def parse_eaf(data: bytes, *, diagnostics: list[Problem] | None = None) -> Document:
    """Load EAF, normalizing safe alignable-tier order before edits begin.

    Only otherwise valid, fully resolved documents are normalized. Unused slots are
    preserved and do not block ordering. Malformed/ambiguous documents retain their
    original order. An optional diagnostics list receives validation findings and a
    warning for each normalized tier. Reference-tier order and residue anchors stay
    as imported; residue inside an annotation travels with that annotation.
    """
    try:
        root = parse(data)
    except Exception as exc:  # lxml raises XMLSyntaxError; keep the message
        raise EAFError(f"not well-formed XML: {exc}") from exc
    if root.tag != "ANNOTATION_DOCUMENT":
        raise EAFError(f"root element is {root.tag!r}, expected 'ANNOTATION_DOCUMENT'")
    doc = _Reader().document(root)
    _normalize_annotation_order(doc, diagnostics)
    return doc


def _order_problems(doc: Document) -> list[Problem]:
    """Conservative import gate; do not guess how to repair invalid time/parent data."""
    problems: list[Problem] = []
    for slot_id, count in Counter(s.id for s in doc.time_order).items():
        if count > 1:
            problems.append(
                Problem(
                    "duplicate-slot-id",
                    Severity.ERROR,
                    "ambiguous time slot id",
                    (slot_id,),
                )
            )
    for slot in doc.time_order:
        if "TIME_VALUE" in slot.residue.attrs or (slot.value is not None and slot.value < 0):
            problems.append(
                Problem(
                    "invalid-time-value",
                    Severity.ERROR,
                    "invalid time slot value",
                    (slot.id,),
                )
            )
    if problems:
        return problems
    by_id = {t.id: t for t in doc.tiers}
    checked: set[str] = set()
    for tier in doc.tiers:
        path: set[str] = set()
        current: Tier | None = tier
        while current is not None and current.id not in checked:
            if current.id in path:
                problems.append(
                    Problem(
                        "tier-cycle",
                        Severity.ERROR,
                        "cyclic tier ancestry",
                        (current.id,),
                    )
                )
                break
            path.add(current.id)
            current = by_id.get(current.parent_ref) if current.parent_ref is not None else None
        checked.update(path)
    if problems:
        return problems
    try:
        structure = analyze(doc)
        problems.extend(validate(doc, structure))
    except (OverflowError, RecursionError) as exc:
        return [Problem("normalization-skipped", Severity.ERROR, str(exc))]
    positions = {slot: i for i, slot in enumerate(doc.time_order)}
    for tier in doc.tiers:
        for annotation in tier.annotations:
            parent = structure.parent.get(annotation)
            if parent is not None and structure.tier_of[parent].id != tier.parent_ref:
                problems.append(
                    Problem(
                        "wrong-parent-tier",
                        Severity.ERROR,
                        "annotation refers to a parent on the wrong tier",
                        (annotation.id,),
                    )
                )
            if annotation not in structure.times:
                problems.append(
                    Problem(
                        "unresolved-time",
                        Severity.ERROR,
                        "annotation time is unresolved",
                        (annotation.id,),
                    )
                )
            if (
                isinstance(annotation, AlignableAnnotation)
                and doc.stereotype_of(tier) in (None, Stereotype.INCLUDED_IN)
                and (annotation.begin.value is None or annotation.end.value is None)
            ):
                problems.append(
                    Problem(
                        "unaligned-boundary",
                        Severity.ERROR,
                        "root or Included In annotation has an unaligned boundary",
                        (annotation.id,),
                    )
                )
            if isinstance(annotation, AlignableAnnotation) and (
                positions.get(annotation.begin, -1) >= positions.get(annotation.end, -1)
            ):
                problems.append(
                    Problem(
                        "slot-order",
                        Severity.ERROR,
                        "begin slot does not precede end slot",
                        (annotation.id,),
                    )
                )
    return problems


def _normalize_annotation_order(doc: Document, diagnostics: list[Problem] | None) -> None:
    positions = {slot: i for i, slot in enumerate(doc.time_order)}
    candidates: list[tuple[Tier, list[AlignableAnnotation]]] = []
    for tier in doc.tiers:
        annotations = [a for a in tier.annotations if isinstance(a, AlignableAnnotation)]
        if len(annotations) != len(tier.annotations):
            continue  # reference-only and malformed mixed tiers keep their imported order
        if any(a > b for a, b in pairwise(positions.get(a.begin, -1) for a in annotations)):
            candidates.append((tier, annotations))
    # Normal, already ordered reads retain their existing fast path. A requested
    # report still checks the input, even when no normalization is needed.
    if not candidates and diagnostics is None:
        return
    problems = _order_problems(doc)
    if diagnostics is not None:
        diagnostics.extend(problems)
    if any(p.code != "unused-slot" for p in problems):
        return
    for tier, annotations in candidates:
        ordered = sorted(annotations, key=lambda a: positions[a.begin])
        tier.annotations[:] = ordered
        if diagnostics is not None:
            diagnostics.append(
                Problem(
                    "annotation-order-normalized",
                    Severity.WARNING,
                    "alignable annotations normalized by begin-slot order",
                    (tier.id,),
                )
            )


class _Reader:
    def __init__(self) -> None:
        self.slots: dict[str, TimeSlot] = {}
        self.needs_und = False

    def document(self, root: Element) -> Document:
        known, residue = split_attrs(root, ["AUTHOR", "DATE", "VERSION", "FORMAT"])
        doc = Document(
            author=known.get("AUTHOR", ""),
            date=known.get("DATE", ""),
            version=known.get("VERSION", "3.0"),
            format=known.get("FORMAT"),
            source_version=known.get("VERSION"),
        )
        doc.root_extra = residue.attrs
        doc.prolog = [copy.deepcopy(n) for n in reversed(list(root.itersiblings(preceding=True)))]
        doc.epilog = [copy.deepcopy(n) for n in root.itersiblings()]
        # TIME_ORDER must be read before tiers refer to it, but EAF guarantees that order.
        handlers = {
            "LICENSE": lambda el: doc.licenses.append(self.license(el)),
            "HEADER": lambda el: setattr(doc, "header", self.header(el)),
            "TIME_ORDER": lambda el: self.time_order(el, doc),
            "TIER": lambda el: doc.tiers.append(self.tier(el)),
            "LINGUISTIC_TYPE": lambda el: doc.tier_types.append(self.tier_type(el)),
            "LOCALE": lambda el: doc.locales.append(self.locale(el)),
            "LANGUAGE": lambda el: doc.languages.append(self.language(el)),
            "CONSTRAINT": lambda el: doc.constraints.append(self.constraint(el)),
            "CONTROLLED_VOCABULARY": lambda el: doc.vocabularies.append(self.vocabulary(el)),
            "LEXICON_REF": lambda el: doc.lexicon_refs.append(self.lexicon_ref(el)),
            "REF_LINK_SET": lambda el: doc.ref_link_sets.append(self.ref_link_set(el)),
            "EXTERNAL_REF": lambda el: doc.external_refs.append(self.external_ref(el)),
        }
        walk_children(root, doc.residue, handlers)
        if self.needs_und and not any(lang.id == "und" for lang in doc.languages):
            doc.languages.append(
                Language(UND_LANGUAGE.id, UND_LANGUAGE.definition, UND_LANGUAGE.label)
            )
        return doc

    # -- header ----------------------------------------------------------------------

    def license(self, el: Element) -> License:
        known, residue = split_attrs(el, ["LICENSE_URL"])
        keep_text_residue(el, residue)
        return License(text=el.text or "", url=known.get("LICENSE_URL"), residue=residue)

    def header(self, el: Element) -> Header:
        known, residue = split_attrs(el, ["MEDIA_FILE", "TIME_UNITS"])
        header = Header(
            media_file=known.get("MEDIA_FILE"),
            time_units=known.get("TIME_UNITS"),
            residue=residue,
        )

        def media(child: Element) -> None:
            names = [
                "MEDIA_URL",
                "RELATIVE_MEDIA_URL",
                "MIME_TYPE",
                "TIME_ORIGIN",
                "EXTRACTED_FROM",
            ]
            values, rest = split_attrs(child, names)
            walk_children(child, rest, {})
            header.media.append(
                MediaDescriptor(
                    media_url=values.get("MEDIA_URL", ""),
                    mime_type=values.get("MIME_TYPE", ""),
                    relative_media_url=values.get("RELATIVE_MEDIA_URL"),
                    time_origin=_int_or_none(values.get("TIME_ORIGIN"), rest, "TIME_ORIGIN"),
                    extracted_from=values.get("EXTRACTED_FROM"),
                    residue=rest,
                )
            )

        def linked(child: Element) -> None:
            names = ["LINK_URL", "RELATIVE_LINK_URL", "MIME_TYPE", "TIME_ORIGIN", "ASSOCIATED_WITH"]
            values, rest = split_attrs(child, names)
            walk_children(child, rest, {})
            header.linked_files.append(
                LinkedFileDescriptor(
                    link_url=values.get("LINK_URL", ""),
                    mime_type=values.get("MIME_TYPE", ""),
                    relative_link_url=values.get("RELATIVE_LINK_URL"),
                    time_origin=_int_or_none(values.get("TIME_ORIGIN"), rest, "TIME_ORIGIN"),
                    associated_with=values.get("ASSOCIATED_WITH"),
                    residue=rest,
                )
            )

        def prop(child: Element) -> None:
            values, rest = split_attrs(child, ["NAME"])
            keep_text_residue(child, rest)
            header.properties.append(Property(values.get("NAME"), child.text or "", rest))

        walk_children(
            el,
            header.residue,
            {"MEDIA_DESCRIPTOR": media, "LINKED_FILE_DESCRIPTOR": linked, "PROPERTY": prop},
        )
        return header

    # -- time and tiers --------------------------------------------------------------

    def time_order(self, el: Element, doc: Document) -> None:
        _, residue = split_attrs(el, [])
        doc.time_order_residue = residue

        def slot(child: Element) -> None:
            values, rest = split_attrs(child, ["TIME_SLOT_ID", "TIME_VALUE"])
            walk_children(child, rest, {})
            slot_id = values.get("TIME_SLOT_ID", "")
            value = _int_or_none(values.get("TIME_VALUE"), rest, "TIME_VALUE")
            time_slot = TimeSlot(slot_id, value, rest)
            self.slots[slot_id] = time_slot
            doc.time_order.append(time_slot)

        walk_children(el, residue, {"TIME_SLOT": slot})

    def tier(self, el: Element) -> Tier:
        names = [
            "TIER_ID",
            "PARTICIPANT",
            "ANNOTATOR",
            "LINGUISTIC_TYPE_REF",
            "DEFAULT_LOCALE",
            "PARENT_REF",
            "EXT_REF",
            "LANG_REF",
        ]
        values, residue = split_attrs(el, names)
        tier = Tier(
            id=values.get("TIER_ID", ""),
            type_ref=values.get("LINGUISTIC_TYPE_REF", ""),
            parent_ref=values.get("PARENT_REF"),
            participant=values.get("PARTICIPANT"),
            annotator=values.get("ANNOTATOR"),
            default_locale=values.get("DEFAULT_LOCALE"),
            lang_ref=values.get("LANG_REF"),
            ext_ref=values.get("EXT_REF"),
            residue=residue,
        )
        walk_children(el, residue, {"ANNOTATION": lambda a: self.annotation(a, tier)})
        return tier

    def annotation(self, el: Element, tier: Tier) -> None:
        _, wrapper_residue = split_attrs(el, [])
        found: list[AlignableAnnotation | RefAnnotation] = []

        def alignable(child: Element) -> None:
            names = [
                "ANNOTATION_ID",
                "EXT_REF",
                "LANG_REF",
                "CVE_REF",
                "TIME_SLOT_REF1",
                "TIME_SLOT_REF2",
                "SVG_REF",
            ]
            values, residue = split_attrs(child, names)
            annotation = AlignableAnnotation(
                id=values.get("ANNOTATION_ID", ""),
                ext_ref=values.get("EXT_REF"),
                lang_ref=values.get("LANG_REF"),
                cve_ref=values.get("CVE_REF"),
                begin=self._slot(values.get("TIME_SLOT_REF1", "")),
                end=self._slot(values.get("TIME_SLOT_REF2", "")),
                svg_ref=values.get("SVG_REF"),
                residue=residue,
            )
            self._value(child, annotation)
            found.append(annotation)

        def reference(child: Element) -> None:
            names = [
                "ANNOTATION_ID",
                "EXT_REF",
                "LANG_REF",
                "CVE_REF",
                "ANNOTATION_REF",
                "PREVIOUS_ANNOTATION",
            ]
            values, residue = split_attrs(child, names)
            annotation = RefAnnotation(
                id=values.get("ANNOTATION_ID", ""),
                ext_ref=values.get("EXT_REF"),
                lang_ref=values.get("LANG_REF"),
                cve_ref=values.get("CVE_REF"),
                ref=values.get("ANNOTATION_REF", ""),
                previous=values.get("PREVIOUS_ANNOTATION"),
                residue=residue,
            )
            self._value(child, annotation)
            found.append(annotation)

        walk_children(
            el,
            wrapper_residue,
            {"ALIGNABLE_ANNOTATION": alignable, "REF_ANNOTATION": reference},
        )
        if not found:
            # An <ANNOTATION> without content is invalid; keep it whole on the tier.
            tier.residue.children.append((len(tier.annotations), el))
            return
        found[0].wrapper_residue = wrapper_residue
        tier.annotations.extend(found)

    def _value(self, el: Element, annotation: AlignableAnnotation | RefAnnotation) -> None:
        def value(child: Element) -> None:
            _, rest = split_attrs(child, [])
            keep_text_residue(child, rest)
            annotation.value = child.text or ""
            annotation.value_residue = rest

        walk_children(el, annotation.residue, {"ANNOTATION_VALUE": value})

    def _slot(self, slot_id: str) -> TimeSlot:
        slot = self.slots.get(slot_id)
        if slot is None:
            # Dangling reference: keep it as an unaligned slot so the file still loads;
            # validation reports it.
            slot = TimeSlot(slot_id)
            self.slots[slot_id] = slot
        return slot

    # -- types, languages, vocabularies ----------------------------------------------

    def tier_type(self, el: Element) -> TierType:
        names = [
            "LINGUISTIC_TYPE_ID",
            "TIME_ALIGNABLE",
            "CONSTRAINTS",
            "GRAPHIC_REFERENCES",
            "CONTROLLED_VOCABULARY_REF",
            "EXT_REF",
            "LEXICON_REF",
        ]
        values, residue = split_attrs(el, names)
        walk_children(el, residue, {})
        constraint_text = values.get("CONSTRAINTS")
        constraint: Stereotype | None = None
        if constraint_text is not None:
            try:
                constraint = Stereotype(constraint_text)
            except ValueError:
                residue.attrs["CONSTRAINTS"] = constraint_text
        return TierType(
            id=values.get("LINGUISTIC_TYPE_ID", ""),
            time_alignable=values.get("TIME_ALIGNABLE"),
            constraint=constraint,
            graphic_references=values.get("GRAPHIC_REFERENCES"),
            cv_ref=values.get("CONTROLLED_VOCABULARY_REF"),
            ext_ref=values.get("EXT_REF"),
            lexicon_ref=values.get("LEXICON_REF"),
            residue=residue,
        )

    def locale(self, el: Element) -> Locale:
        values, residue = split_attrs(el, ["LANGUAGE_CODE", "COUNTRY_CODE", "VARIANT"])
        walk_children(el, residue, {})
        return Locale(
            values.get("LANGUAGE_CODE", ""),
            values.get("COUNTRY_CODE"),
            values.get("VARIANT"),
            residue,
        )

    def language(self, el: Element) -> Language:
        values, residue = split_attrs(el, ["LANG_ID", "LANG_DEF", "LANG_LABEL"])
        walk_children(el, residue, {})
        return Language(
            values.get("LANG_ID", ""), values.get("LANG_DEF"), values.get("LANG_LABEL"), residue
        )

    def constraint(self, el: Element) -> Constraint:
        values, residue = split_attrs(el, ["STEREOTYPE", "DESCRIPTION"])
        walk_children(el, residue, {})
        return Constraint(values.get("STEREOTYPE", ""), values.get("DESCRIPTION"), residue)

    def vocabulary(self, el: Element) -> ControlledVocabulary:
        values, residue = split_attrs(el, ["CV_ID", "EXT_REF", "DESCRIPTION"])
        cv = ControlledVocabulary(
            id=values.get("CV_ID", ""), ext_ref=values.get("EXT_REF"), residue=residue
        )
        if "DESCRIPTION" in values:  # pre-2.8 form
            self.needs_und = True
            if values["DESCRIPTION"]:
                cv.descriptions.append(LangText("und", values["DESCRIPTION"]))

        def description(child: Element) -> None:
            attrs, rest = split_attrs(child, ["LANG_REF"])
            keep_text_residue(child, rest)
            cv.descriptions.append(LangText(attrs.get("LANG_REF", ""), child.text or "", rest))

        def entry_ml(child: Element) -> None:
            attrs, rest = split_attrs(child, ["CVE_ID", "EXT_REF"])
            entry = CVEntry(attrs.get("CVE_ID", ""), ext_ref=attrs.get("EXT_REF"), residue=rest)

            def cve_value(value_el: Element) -> None:
                vattrs, vrest = split_attrs(value_el, ["LANG_REF", "DESCRIPTION"])
                keep_text_residue(value_el, vrest)
                entry.values.append(
                    CVEValue(
                        vattrs.get("LANG_REF", ""),
                        value_el.text or "",
                        vattrs.get("DESCRIPTION"),
                        vrest,
                    )
                )

            walk_children(child, rest, {"CVE_VALUE": cve_value})
            cv.entries.append(entry)

        def entry_old(child: Element) -> None:
            self.needs_und = True
            attrs, rest = split_attrs(child, ["CVE_ID", "EXT_REF", "DESCRIPTION"])
            keep_text_residue(child, rest)
            entry_id = attrs.get("CVE_ID") or f"cveid_{uuid.uuid4()}"
            value = CVEValue("und", child.text or "", attrs.get("DESCRIPTION"), rest)
            cv.entries.append(CVEntry(entry_id, [value], attrs.get("EXT_REF")))

        walk_children(
            el,
            residue,
            {"DESCRIPTION": description, "CV_ENTRY_ML": entry_ml, "CV_ENTRY": entry_old},
        )
        return cv

    def lexicon_ref(self, el: Element) -> LexiconRef:
        names = [
            "LEX_REF_ID",
            "NAME",
            "TYPE",
            "URL",
            "LEXICON_ID",
            "LEXICON_NAME",
            "DATCAT_ID",
            "DATCAT_NAME",
        ]
        values, residue = split_attrs(el, names)
        walk_children(el, residue, {})
        return LexiconRef(
            id=values.get("LEX_REF_ID", ""),
            name=values.get("NAME", ""),
            type=values.get("TYPE", ""),
            url=values.get("URL", ""),
            lexicon_id=values.get("LEXICON_ID", ""),
            lexicon_name=values.get("LEXICON_NAME", ""),
            datcat_id=values.get("DATCAT_ID"),
            datcat_name=values.get("DATCAT_NAME"),
            residue=residue,
        )

    def ref_link_set(self, el: Element) -> RefLinkSet:
        link_set = RefLinkSet(attrs={str(k): str(v) for k, v in el.attrib.items()})

        def link(kind: str) -> Callable[[Element], None]:
            def handle(child: Element) -> None:
                rest = Residue()
                keep_text_residue(child, rest)
                link_set.links.append(
                    RefLink(
                        kind,
                        {str(k): str(v) for k, v in child.attrib.items()},
                        child.text or "",
                        rest,
                    )
                )

            return handle

        walk_children(
            el,
            link_set.residue,
            {"CROSS_REF_LINK": link("cross"), "GROUP_REF_LINK": link("group")},
        )
        return link_set

    def external_ref(self, el: Element) -> ExternalRef:
        values, residue = split_attrs(el, ["EXT_REF_ID", "TYPE", "VALUE"])
        walk_children(el, residue, {})
        return ExternalRef(
            values.get("EXT_REF_ID", ""), values.get("TYPE", ""), values.get("VALUE", ""), residue
        )


def _int_or_none(text: str | None, residue: Residue, name: str) -> int | None:
    """Parse an integer attribute. Values we cannot parse are kept verbatim as residue."""
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        residue.attrs[name] = text
        return None
