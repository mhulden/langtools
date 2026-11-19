"""Per-kind oracle hooks (issue #34 step A): legacy spectrogram data unchanged, kinds bound."""

import fnmatch
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from oracle import compare, run_reference, summarize
from oracle.compare import _validate_candidate, evidence_sha256
from oracle.generate_fixtures import generate
from oracle.kinds import (
    KINDS,
    SPECTROGRAM,
    OracleKind,
    get_kind,
    kind_of,
    require_kind,
    stamp,
)

ORACLE = Path(__file__).resolve().parents[1]


def fake_script(inp: Path, out: Path, settings: dict) -> str:
    return f"IN {inp}\nOUT {out}\nSETTINGS {json.dumps(settings, sort_keys=True)}\n"


FAKE = OracleKind(
    name="fake",
    settings={"gain": 1.0},
    output_suffix=".Fake",
    generate=f"{__name__}:fake_script",
    script_for=f"{__name__}:fake_script",
    export=f"{__name__}:fake_script",
    compare_capture=f"{__name__}:fake_script",
    candidate_file=f"{__name__}:fake_script",
    render=f"{__name__}:fake_script",
    primary_module="fake.module",
)


def _fake_praat_run(cmd, **kwargs):
    if "--version" in cmd:
        return SimpleNamespace(returncode=0, stdout="test", stderr="")
    for line in Path(cmd[-1]).read_text(encoding="utf-8").splitlines():
        if line.startswith("OUT "):
            Path(line[4:]).write_text("reference output\n", encoding="utf-8")
    return SimpleNamespace(returncode=0, stdout="", stderr="")


class KindRegistryTests(unittest.TestCase):
    def test_get_kind_normalizes_case_and_space_and_rejects_unknown(self):
        self.assertIs(get_kind(" Spectrogram "), SPECTROGRAM)
        for bad in ("intensity", "", 3):
            with self.assertRaises(ValueError):
                get_kind(bad)

    def test_absent_kind_is_spectrogram_and_recorded_kind_must_be_canonical(self):
        self.assertEqual(kind_of({}), "spectrogram")
        self.assertEqual(kind_of({"kind": "spectrogram"}), "spectrogram")
        for bad in (" spectrogram", "Spectrogram", "fake", None, 1):
            with self.assertRaises(ValueError):
                kind_of({"kind": bad})

    def test_legacy_kind_is_not_stamped_and_keeps_legacy_paths(self):
        data = {"schema": "x"}
        self.assertIs(stamp(data, SPECTROGRAM), data)
        self.assertEqual(SPECTROGRAM.directory("captures"), ORACLE / "captures")
        self.assertEqual(SPECTROGRAM.comparison_path(), ORACLE / "comparison.json")
        with tempfile.TemporaryDirectory() as tmp:
            manifest = generate(Path(tmp))
            self.assertNotIn("kind", manifest)
            self.assertNotIn('"kind"', (Path(tmp) / "manifest.json").read_text(encoding="utf-8"))

    def test_new_kind_is_stamped_first_and_uses_separate_ignored_paths(self):
        self.assertEqual(list(stamp({"schema": "x"}, FAKE)), ["kind", "schema"])
        paths = [
            FAKE.directory("generated").name + "/",
            FAKE.directory("captures").name + "/",
            FAKE.directory("candidate").name + "/",
            FAKE.comparison_path().name,
        ]
        self.assertEqual(
            paths, ["generated-fake/", "captures-fake/", "candidate-fake/", "comparison-fake.json"]
        )
        patterns = [
            line.strip()
            for line in (ORACLE / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        for path in paths:
            self.assertTrue(any(fnmatch.fnmatch(path, p) for p in patterns), path)

    def test_hooks_resolve_to_the_existing_spectrogram_functions(self):
        self.assertIs(SPECTROGRAM.hook("script_for"), run_reference.script_for)
        self.assertIs(SPECTROGRAM.hook("compare_capture"), compare.compare_capture)
        self.assertIs(SPECTROGRAM.hook("render"), summarize.render)
        self.assertEqual(dict(SPECTROGRAM.settings), run_reference.SETTINGS)

    def test_runner_and_comparison_modules_stay_standard_library_only(self):
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "import oracle.kinds, oracle.run_reference, oracle.generate_fixtures,"
            " oracle.compare, oracle.summarize;"
            "assert 'numpy' not in sys.modules and 'langtools_praat' not in sys.modules"
        )
        subprocess.run([sys.executable, "-c", code, str(ORACLE.parent)], check=True)


class KindBindingTests(unittest.TestCase):
    def _capture(self, tmp: Path, kind: OracleKind, manifest_kind: str | None) -> dict:
        inputs = tmp / "inputs"
        inputs.mkdir()
        wav = inputs / "a.wav"
        wav.write_bytes(b"audio")
        manifest = {
            "schema": "test",
            "files": [
                {
                    "name": "a",
                    "file": "a.wav",
                    "sha256": hashlib.sha256(b"audio").hexdigest(),
                    "expected_reference_status": "capture",
                }
            ],
        }
        if manifest_kind is not None:
            manifest = {"kind": manifest_kind, **manifest}
        (inputs / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        praat = tmp / "praat"
        praat.write_bytes(b"binary")
        pin = tmp / "pin.json"
        pin.write_text(json.dumps({"sha256": hashlib.sha256(b"binary").hexdigest()}))
        with (
            patch.dict(KINDS, {"fake": FAKE}),
            patch("oracle.run_reference.subprocess.run", side_effect=_fake_praat_run),
            patch("oracle.run_reference.project_commit", return_value="0" * 40),
            patch("builtins.print"),
        ):
            return run_reference.run(praat, pin, inputs, tmp / "out", 5, kind)

    def test_new_kind_evidence_binds_kind_into_its_canonical_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence = self._capture(Path(tmp), FAKE, "fake")
            saved = json.loads((Path(tmp) / "out" / "evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(list(evidence)[0], "kind")
        self.assertEqual(saved["kind"], "fake")
        self.assertNotIn("pr17_head_when_scoped", saved)
        self.assertEqual(saved["settings"], {"gain": 1.0})
        self.assertEqual(saved["runs"][0]["output"], "a.Fake")
        unbound = {k: v for k, v in saved.items() if k != "kind"}
        self.assertNotEqual(evidence_sha256(saved), evidence_sha256(unbound))

    def test_legacy_spectrogram_evidence_has_original_fields_and_no_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence = self._capture(Path(tmp), SPECTROGRAM, None)
        self.assertEqual(
            list(evidence),
            [
                "schema",
                "utc",
                "reference_pin",
                "reference_current_sha256",
                "source_commit",
                "pr17_head_when_scoped",
                "os",
                "cpu",
                "python",
                "settings",
                "fixture_manifest_sha256",
                "runs",
            ],
        )

    def test_runner_rejects_a_manifest_of_another_kind(self):
        for kind, manifest_kind in ((SPECTROGRAM, "fake"), (FAKE, None), (FAKE, "spectrogram")):
            with self.subTest(kind=kind.name, manifest=manifest_kind):
                with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
                    self._capture(Path(tmp), kind, manifest_kind)

    def test_spectrogram_comparison_rejects_a_candidate_of_another_kind(self):
        with patch.dict(KINDS, {"fake": FAKE}):
            for bad in ("fake", "Spectrogram", 7):
                result = _validate_candidate(
                    {}, {"kind": bad}, channel="mono", manifest_sha256="b" * 64
                )
                self.assertEqual(result["status"], "candidate_identity_mismatch")
                self.assertEqual(result["field"], "kind")

    def test_compare_cli_rejects_evidence_of_another_kind(self):
        cases = (
            ({"kind": "fake", "runs": []}, "spectrogram"),
            ({"runs": []}, "fake"),
            ({"runs": []}, "intensity"),
        )
        for evidence, requested in cases:
            with self.subTest(evidence=evidence.get("kind"), requested=requested):
                with tempfile.TemporaryDirectory() as tmp:
                    (Path(tmp) / "evidence.json").write_text(json.dumps(evidence))
                    argv = [
                        "compare",
                        "--kind",
                        requested,
                        "--oracle",
                        tmp,
                        "--candidate",
                        tmp,
                        "--output",
                        str(Path(tmp) / "comparison.json"),
                    ]
                    with (
                        patch.dict(KINDS, {"fake": FAKE}),
                        patch.object(sys, "argv", argv),
                        patch("sys.stderr"),
                        self.assertRaises(SystemExit),
                    ):
                        compare.main()
                    self.assertFalse((Path(tmp) / "comparison.json").exists())

    def test_render_rejects_cross_kind_evidence_or_comparison(self):
        with patch.dict(KINDS, {"fake": FAKE}):
            for evidence, comparison in (({"kind": "fake"}, {}), ({}, {"kind": "fake"})):
                with self.assertRaisesRegex(ValueError, "cross-kind"):
                    summarize.render(evidence, comparison)

    def test_require_kind_names_both_kinds(self):
        with patch.dict(KINDS, {"fake": FAKE}), self.assertRaisesRegex(ValueError, "fake.*spectro"):
            require_kind({"kind": "fake"}, SPECTROGRAM, "Thing")


if __name__ == "__main__":
    unittest.main()
