"""Registry of analysis kinds the oracle can capture and compare (issue #34, step A).

Each kind names its hooks as ``"module:attribute"`` strings, resolved lazily, so this module
stays standard-library only and the runner can be used without the candidate's dependencies.

Spectrogram is the legacy kind: its manifests, evidence, candidate files and comparisons keep
their exact original bytes and never carry a ``kind`` field. Data without ``kind`` is read as
spectrogram. Every other kind writes an explicit, normalized ``kind`` into its manifest,
evidence, candidate identity and comparison, so it is part of the canonical evidence hash and
data of one kind cannot be reused for another.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

HERE = Path(__file__).resolve().parent
LEGACY_KIND = "spectrogram"


@dataclass(frozen=True)
class OracleKind:
    """Hooks and defaults for one analysis kind."""

    name: str
    settings: Mapping[str, object]
    output_suffix: str
    generate: str  # (output: Path) -> manifest dict
    script_for: str  # (input: Path, output: Path, settings: dict) -> Praat script text
    export: str  # (inputs: Path, output: Path) -> None; may import the candidate package
    compare_capture: str  # (entry, oracle_dir, candidate_dir, *, atol, rtol, manifest_sha256)
    candidate_file: str  # (fixture name: str) -> candidate file name used for provenance
    render: str  # (evidence: dict, comparison: dict) -> Markdown
    primary_module: str  # candidate module whose hash must appear in candidate_source
    candidate_modules: tuple[str, ...] = field(default_factory=tuple)

    @property
    def legacy(self) -> bool:
        return self.name == LEGACY_KIND

    def hook(self, name: str) -> Callable:
        module, _, attribute = getattr(self, name).partition(":")
        return getattr(importlib.import_module(module), attribute)

    def directory(self, base: str) -> Path:
        """Default local directory: legacy names for spectrogram, else ``<base>-<kind>``."""
        return HERE / (base if self.legacy else f"{base}-{self.name}")

    def comparison_path(self) -> Path:
        return HERE / ("comparison.json" if self.legacy else f"comparison-{self.name}.json")


SPECTROGRAM = OracleKind(
    name=LEGACY_KIND,
    settings=MappingProxyType(
        {
            "window_length_s": 0.005,
            "maximum_frequency_hz": 5000.0,
            "time_step_s": 0.002,
            "frequency_step_hz": 20.0,
            "window_shape": "Gaussian",
        }
    ),
    output_suffix=".Spectrogram",
    generate="oracle.generate_fixtures:generate",
    script_for="oracle.run_reference:script_for",
    export="oracle.export_candidate:export",
    compare_capture="oracle.compare:compare_capture",
    candidate_file="oracle.compare:spectrogram_candidate_file",
    render="oracle.summarize:render",
    primary_module="langtools_praat.analysis.spectrogram",
    candidate_modules=(
        "langtools_praat.analysis.spectrogram",
        "langtools_praat.analysis.contracts",
        "langtools_praat.model.sound",
        "langtools_praat.model.time",
        "langtools_praat.errors",
    ),
)

KINDS: dict[str, OracleKind] = {SPECTROGRAM.name: SPECTROGRAM}


def get_kind(name: str) -> OracleKind:
    """Look up a kind by user-supplied name (case and surrounding space are ignored)."""
    if not isinstance(name, str):
        raise ValueError(f"Analysis kind must be a string, not {type(name).__name__}")
    normalized = name.strip().lower()
    if normalized not in KINDS:
        raise ValueError(f"Unknown analysis kind {name!r}; known: {', '.join(sorted(KINDS))}")
    return KINDS[normalized]


def kind_of(record: Mapping) -> str:
    """Kind recorded in a manifest, evidence, candidate or comparison object.

    A missing ``kind`` means legacy spectrogram data. A recorded kind must be exactly a
    registered, normalized name; anything else is rejected rather than guessed.
    """
    if not isinstance(record, Mapping):
        raise ValueError("Oracle data must be a JSON object")
    if "kind" not in record:
        return LEGACY_KIND
    value = record["kind"]
    if not isinstance(value, str) or value not in KINDS:
        raise ValueError(f"Invalid or unknown recorded analysis kind: {value!r}")
    return value


def require_kind(record: Mapping, kind: OracleKind, what: str) -> None:
    """Raise if ``record`` belongs to a different kind than ``kind``."""
    found = kind_of(record)
    if found != kind.name:
        raise ValueError(f"{what} is {found!r} data, not {kind.name!r}; cross-kind reuse rejected")


def stamp(data: dict, kind: OracleKind) -> dict:
    """Return ``data`` with an explicit ``kind`` first, except for legacy spectrogram data."""
    return data if kind.legacy else {"kind": kind.name, **data}
