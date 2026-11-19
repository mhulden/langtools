"""3,000 generated edit sequences, with a separate disk-persistence gate."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from elan_ng.core.changes import check_invariants
from elan_ng.core.constraints import ConstraintEngine, EditRejected
from elan_ng.core.model import RefAnnotation, Stereotype, Tier, TierType
from elan_ng.core.undo import UndoStack
from elan_ng.io.eaf_reader import read_eaf

from .helpers import snapshot
from support import DATA

COMMAND = st.tuples(
    st.sampled_from(["create", "clear", "delete", "retime", "undo", "redo", "save"]),
    st.integers(0, 99),
    st.integers(-2, 40),
    st.integers(-1, 10),
    st.text(alphabet="ab ñé<&>\n", max_size=6),
)


@settings(max_examples=3000, deadline=None, derandomize=True)
@given(
    depth=st.integers(0, 3),
    roots=st.integers(1, 3),
    commands=st.lists(COMMAND, min_size=1, max_size=15),
)
def test_3000_edit_sequences_have_exact_inverse_undo_redo_and_valid_trees(
    depth: int,
    roots: int,
    commands: list[tuple[str, int, int, int, str]],
) -> None:
    doc = read_eaf(DATA / "minimal.eaf")
    for i in range(roots):
        doc.tiers.append(Tier(f"free{i}", doc.tiers[0].type_ref))
    # Vary tree depth as well as forest width; descendants contain optional fields.
    doc.tier_types.append(TierType("assoc", constraint=Stereotype.SYMBOLIC_ASSOCIATION))
    parent_tier, parent_id = doc.tiers[0].id, "a1"
    for i in range(depth):
        annotation = RefAnnotation(f"generated{i}", value="ñ", ref=parent_id, ext_ref="opaque")
        tier = Tier(f"child{i}", "assoc", parent_ref=parent_tier, annotations=[annotation])
        doc.tiers.append(tier)
        parent_tier, parent_id = tier.id, annotation.id
    engine, stack = ConstraintEngine(doc), UndoStack(doc)
    states = [snapshot(doc)]
    # Every generated sequence includes a successful edit, even if the random tail
    # contains only undo/redo or deliberately unsupported requests.
    seed = engine.create("free0", 5000, 5100, "seed")
    seed.apply(doc)
    seeded = snapshot(doc)
    seed.inverse().apply(doc)
    assert snapshot(doc) == states[0]
    stack.execute(seed)
    assert snapshot(doc) == seeded
    states.append(seeded)
    position = 1
    for command, selector, start, duration, value in commands:
        before = snapshot(doc)
        if command == "undo":
            assert stack.undo() == (position > 0)
            position = max(0, position - 1)
            assert snapshot(doc) == states[position]
        elif command == "redo":
            assert stack.redo() == (position + 1 < len(states))
            position = min(position + 1, len(states) - 1)
            assert snapshot(doc) == states[position]
        elif command == "save":
            stack.mark_saved()
            assert not stack.dirty and snapshot(doc) == before
        else:
            annotations = doc.annotations()
            try:
                if command == "create":
                    tier_id = [doc.tiers[0].id, *[f"free{i}" for i in range(roots)]][
                        selector % (roots + 1)
                    ]
                    changes = engine.create(tier_id, start * 100, (start + duration) * 100, value)
                elif not annotations:
                    continue
                elif command == "clear":
                    changes = engine.clear_value(annotations[selector % len(annotations)].id)
                elif command == "delete":
                    changes = engine.delete(annotations[selector % len(annotations)].id)
                else:
                    changes = engine.retime(
                        annotations[selector % len(annotations)].id,
                        start * 100,
                        (start + duration) * 100,
                    )
            except EditRejected:
                assert snapshot(doc) == before
                continue
            assert snapshot(doc) == before
            changes.apply(doc)
            after = snapshot(doc)
            check_invariants(doc)
            changes.inverse().apply(doc)
            assert snapshot(doc) == before
            stack.execute(changes)
            assert snapshot(doc) == after
            if changes.operations:
                states[position + 1 :] = [after]
                position += 1
        check_invariants(doc)
    final_position = position
    while stack.can_undo:
        assert stack.undo()
        position -= 1
        assert snapshot(doc) == states[position]
    while position < final_position:
        assert stack.redo()
        position += 1
        assert snapshot(doc) == states[position]
