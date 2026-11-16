"""Deterministic builders for generated round-trip files (REIMPLEMENTATION.md §6.2).

Each builder returns an elan_ng ``Document`` built in code, so no large file has to be stored
in the repository. The builders use no randomness, so every call gives the same document.
``large_bytes`` and ``hierarchy_bytes`` cache the serialized large files, so a test session
builds and writes each size only once.

Run this file to write the same documents as .eaf files:

    uv run python tests/eafgen.py OUTPUT_FOLDER
"""

from __future__ import annotations

import argparse
import functools
from collections.abc import Sequence
from pathlib import Path

from elan_ng.core.model import (
    AlignableAnnotation,
    Document,
    RefAnnotation,
    Stereotype,
    Tier,
    TierType,
    TimeSlot,
)
from elan_ng.io.eaf_writer import write_eaf

SEGMENT_TYPE = "segment"
WORD_TYPE = "word"  # Time Subdivision of a segment
TRANSLATION_TYPE = "translation"  # Symbolic Association with a segment
SPAN_MS = 400  # duration of each generated annotation
LARGE_TIERS = 30
LARGE_SIZES = (5_000, 50_000)

# One tier per case, named after the case. The values cover the §6.2 text edge cases.
TEXT_EDGE_CASES: dict[str, str] = {
    "empty": "",
    "multiline": "first line\nsecond line\n\n  indented third line",
    "emoji": "smile \U0001f600 and thumbs \U0001f44d",
    "rare_script": "Gothic \U00010330\U00010331\U00010332",
    "rtl_arabic": "مرحبا بالعالم",
    "rtl_hebrew": "שלום עולם",
    "very_long": "segment " * 1_500,  # 12,000 characters
    "xml_special": "Tom & Jerry <tag> \"quoted\" 'single' a &amp; b",
}


def _new_document() -> Document:
    doc = Document(author="elan-ng generated corpus")
    doc.tier_types.append(TierType(id=SEGMENT_TYPE, time_alignable="true"))
    return doc


def _add_segment_tier(
    doc: Document,
    all_slots: list[TimeSlot],
    tier_id: str,
    values: Sequence[str],
    first_annotation_no: int,
) -> None:
    """Add a time-aligned tier with one annotation per value.

    Consecutive annotations in the tier share a boundary slot, as ELAN-made files do.
    Slot ids continue from the slots already in ``all_slots``.
    """
    first_slot_no = len(all_slots) + 1
    boundaries = [
        TimeSlot(f"ts{first_slot_no + k}", value=k * SPAN_MS) for k in range(len(values) + 1)
    ]
    tier = Tier(id=tier_id, type_ref=SEGMENT_TYPE)
    for k, value in enumerate(values):
        tier.annotations.append(
            AlignableAnnotation(
                id=f"a{first_annotation_no + k}",
                value=value,
                begin=boundaries[k],
                end=boundaries[k + 1],
            )
        )
    all_slots.extend(boundaries)
    doc.tiers.append(tier)


def _finish(doc: Document, all_slots: list[TimeSlot]) -> Document:
    doc.time_order = sorted(all_slots, key=lambda slot: slot.value or 0)
    return doc


def build_large(n_annotations: int, n_tiers: int) -> Document:
    """A document with ``n_annotations`` time-aligned annotations spread over ``n_tiers`` tiers.

    Tiers get the same number of annotations, or one more for the first remainder tiers.
    Values are ``"word N"``, where N is the 1-based annotation number.
    """
    if n_tiers < 1:
        raise ValueError("n_tiers must be at least 1")
    doc = _new_document()
    all_slots: list[TimeSlot] = []
    done = 0
    for tier_no in range(n_tiers):
        count = n_annotations // n_tiers + (1 if tier_no < n_annotations % n_tiers else 0)
        values = [f"word {done + k + 1}" for k in range(count)]
        _add_segment_tier(doc, all_slots, f"tier{tier_no:02d}", values, done + 1)
        done += count
    return _finish(doc, all_slots)


@functools.cache
def large_bytes(n_annotations: int, n_tiers: int = LARGE_TIERS) -> bytes:
    """``build_large`` serialized with ``write_eaf``, built once per argument pair."""
    return write_eaf(build_large(n_annotations, n_tiers))


def build_large_hierarchy(n_segments: int, n_tiers: int) -> Document:
    """Like ``build_large``, but every root tier also has two child tiers.

    Each of the ``n_segments`` root annotations gets two words on a Time Subdivision child
    (their shared inner boundary is an unaligned slot, so ``analyze`` has to interpolate it)
    and one translation on a Symbolic Association child. The document therefore has
    ``4 * n_segments`` annotations. Root tiers are ``tierNN``, children ``tierNN_words`` and
    ``tierNN_translation``. Values are ``"word N"`` on the roots, ``"word N.1"`` and
    ``"word N.2"`` on the words and ``"translation N"`` on the translations.
    """
    if n_tiers < 1:
        raise ValueError("n_tiers must be at least 1")
    doc = _new_document()
    doc.tier_types.append(
        TierType(id=WORD_TYPE, time_alignable="true", constraint=Stereotype.TIME_SUBDIVISION)
    )
    doc.tier_types.append(
        TierType(
            id=TRANSLATION_TYPE, time_alignable="false", constraint=Stereotype.SYMBOLIC_ASSOCIATION
        )
    )
    # Unaligned slots have no time to sort by; this key puts each one between its neighbours.
    sort_key: dict[TimeSlot, float] = {}
    all_slots: list[TimeSlot] = []
    next_annotation = n_segments + 1  # roots take a1..aN, children continue after them
    done = 0
    for tier_no in range(n_tiers):
        count = n_segments // n_tiers + (1 if tier_no < n_segments % n_tiers else 0)
        root_id = f"tier{tier_no:02d}"
        values = [f"word {done + k + 1}" for k in range(count)]
        first_new_slot = len(all_slots)
        _add_segment_tier(doc, all_slots, root_id, values, done + 1)
        for slot in all_slots[first_new_slot:]:
            sort_key[slot] = float(slot.value or 0)
        roots = doc.tiers[-1].annotations

        words = Tier(id=f"{root_id}_words", type_ref=WORD_TYPE, parent_ref=root_id)
        translations = Tier(
            id=f"{root_id}_translation", type_ref=TRANSLATION_TYPE, parent_ref=root_id
        )
        for root in roots:
            assert isinstance(root, AlignableAnnotation)
            middle = TimeSlot(f"ts{len(all_slots) + 1}")
            all_slots.append(middle)
            sort_key[middle] = sort_key[root.begin] + SPAN_MS / 2
            for part, (begin, end) in enumerate(((root.begin, middle), (middle, root.end)), 1):
                words.annotations.append(
                    AlignableAnnotation(
                        id=f"a{next_annotation}",
                        value=f"{root.value}.{part}",
                        begin=begin,
                        end=end,
                    )
                )
                next_annotation += 1
            translations.annotations.append(
                RefAnnotation(
                    id=f"a{next_annotation}",
                    value=root.value.replace("word", "translation"),
                    ref=root.id,
                )
            )
            next_annotation += 1
        doc.tiers.extend([words, translations])
        done += count
    doc.time_order = sorted(all_slots, key=lambda slot: sort_key[slot])
    return doc


@functools.cache
def hierarchy_bytes(n_segments: int, n_tiers: int = LARGE_TIERS) -> bytes:
    """``build_large_hierarchy`` serialized with ``write_eaf``, built once per argument pair."""
    return write_eaf(build_large_hierarchy(n_segments, n_tiers))


def build_text_edge_cases() -> Document:
    """One time-aligned tier per entry of ``TEXT_EDGE_CASES``, with one annotation each."""
    doc = _new_document()
    all_slots: list[TimeSlot] = []
    for annotation_no, (tier_id, value) in enumerate(TEXT_EDGE_CASES.items(), start=1):
        _add_segment_tier(doc, all_slots, tier_id, [value], annotation_no)
    return _finish(doc, all_slots)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write the generated test files as .eaf.")
    parser.add_argument("folder", type=Path, help="output folder (created if missing)")
    args = parser.parse_args(argv)
    args.folder.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Document] = {
        f"generated_large_{size}.eaf": build_large(size, LARGE_TIERS) for size in LARGE_SIZES
    }
    for size in LARGE_SIZES:
        outputs[f"generated_hierarchy_{size}.eaf"] = build_large_hierarchy(size // 4, LARGE_TIERS)
    outputs["generated_text_edge_cases.eaf"] = build_text_edge_cases()
    for name, doc in outputs.items():
        path = args.folder / name
        path.write_bytes(write_eaf(doc))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
