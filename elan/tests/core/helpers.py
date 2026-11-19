"""Exact session-state checks, deliberately independent from EAF normalization."""

from dataclasses import fields, is_dataclass

from lxml import etree

from elan_ng.core.model import AlignableAnnotation, Document, Tier, TierType, TimeSlot


def snapshot(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return (
            type(value),
            id(value),
            tuple((f.name, snapshot(getattr(value, f.name))) for f in fields(value)),
        )
    if isinstance(value, list):
        return (id(value), tuple(snapshot(item) for item in value))
    if isinstance(value, dict):
        return (id(value), tuple((k, snapshot(v)) for k, v in value.items()))
    if isinstance(value, tuple):
        return tuple(snapshot(item) for item in value)
    if isinstance(value, etree._Element):
        return (id(value), etree.tostring(value))
    return value


def simple() -> Document:
    begin, end = TimeSlot("ts1", 100), TimeSlot("ts2", 200)
    return Document(
        time_order=[begin, end],
        tiers=[
            Tier(
                "root",
                "root",
                annotations=[
                    AlignableAnnotation("a1", "original", begin=begin, end=end),
                ],
            )
        ],
        tier_types=[TierType("root", time_alignable="true")],
    )
