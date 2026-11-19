# Praat reference oracle / original fixtures

**Scope:** verify [PR #17](https://github.com/mhulden/langtools/pull/17) spectrogram behavior against a pinned **actual Praat executable**; no changes to `analysis/`, `gui/`, `media/`, or existing algorithms. This package does **not** claim numerical parity before capture.

## Mac setup (macOS 12 / Apple Silicon)

1. Install Praat from <https://praat.org/download_mac.html>. The official site currently offers **7.0.03 (8 November 2026)** and explicitly lists macOS 12 and ARM64 support. Keep the downloaded DMG outside Git. The script executable is normally `/Applications/Praat.app/Contents/MacOS/Praat`.
2. From `langtools/praat/` run the standard-library-only setup and harness tests (no `uv` needed):

   ```bash
   python3 -m unittest discover -s oracle/tests -v
   python3 -m oracle.generate_fixtures
   python3 -m oracle.run_reference pin
   python3 -m oracle.run_reference capture
   ```

   **Note:** `python3` must be 3.12+ for the actual candidate implementation, but the generator and oracle scripts use only the standard library. You may use your existing Python 3.11 for fixture generation/capture if needed; `export_candidate` requires the repository's pinned environment.

3. Inspect `oracle/captures/evidence.json` for per-file exit codes. If Praat 7's script trust protection prevents writing output, inspect the error: do not turn off security protections indiscriminately. You can run/approve the generated scripts as trusted files in the Praat GUI if required. A `failed` status is not a reference measurement.
4. To compare numerical outputs, check out **PR #17** or wait until it merges, so `langtools_praat.analysis.spectrogram` exists. Within `praat/` then run:

   ```bash
   uv sync
   uv run python -m oracle.export_candidate
   uv run python -m oracle.compare
   ```

   `uv` can be installed using the lightweight command from the official documentation (`curl -LsSf https://astral.sh/uv/install.sh | sh`), rather than triggering a slow Homebrew source build. Do not run the candidate on `main` if spectrogram.py is absent.

## Outputs and schemas

- `oracle/generated/manifest.json`: original fixture provenance, PCM16 encoding, deterministic seed and SHA256 of each WAV. Ten fixtures: silence, impulse, 1 kHz sine, 1/1.2 kHz dual-tone (5 ms and 30 ms Gaussian settings), chirp, seeded noise, 12 ms valid short sine, 8 ms deliberately invalid short sine, stereo different left/right frequencies.
- `oracle/local_reference_pin.json`: SHA256 and reported version of local Praat binary; never commit its machine-specific executable path.
- `oracle/captures/*.Spectrogram`: **raw, unedited** Praat text exports.
- `oracle/captures/evidence.json`: executable hash/version, project source commit, OS/CPU, command+script, fixture hashes, output hashes, settings, statuses.
- `oracle/candidate/*.json`: candidate time/frequency axes, frame-major power, candidate display endpoints, or error.
- `oracle/comparison.json`: axis differences, elementwise error counts, max absolute/relative error and tolerance values.

**Orientations:** Praat `z[frequency][time]`, candidate `power[time][frequency]`. `oracle.compare` transposes explicitly. No resampling/interpolation is allowed in the comparison.

**Policy:** The defaults `atol=1e-9` and `rtol=1e-4` are exploratory **comparison thresholds**, not established parity tolerances. Capture actual discrepancy magnitudes before selecting final acceptance thresholds. PCM16 conversion / scaling is documented and must be considered when interpreting low-level power.

**Important limitation:** The `short_invalid` 8 ms signal is expected to fail a 10 ms physical Gaussian window; the runner records the actual result and does not turn failure into a pass automatically. Stereo is exported by the candidate for left/right/combined but the simple Praat `To Spectrogram` command may combine channels by a different rule; treat the latter as an open reference question, not verified parity. Display defaults are still **candidates**; raw Spectrogram text alone does not prove editor or Paint defaults. To resolve D04, record GUI dialogs/screenshots or use an explicit script/GUI oracle separately and describe the evidence.

## Analysis kinds (issue #34)

`oracle/kinds.py` registers one record per analysis kind: default settings, reference output suffix, and hooks for fixture generation, the Praat script, candidate export, per-capture comparison, the provenance candidate file and the report. Every CLI takes `--kind` (default `spectrogram`).

- **Spectrogram is the legacy kind.** Its manifests, evidence, candidate files, comparisons and report are byte-identical to the pre-registry output and carry no `kind` field. Data without `kind` is read as spectrogram.
- **Every other kind** writes an explicit normalized `kind` first in its manifest, evidence, candidate identity and comparison. Because it is inside the evidence object, it is bound into `oracle_evidence_sha256`.
- **Cross-kind reuse is rejected:** the runner checks the manifest kind, `compare` checks the evidence kind against `--kind`, the spectrogram comparison rejects candidates of another kind, and `render` rejects evidence or comparisons of another kind. Unknown or non-canonical kind strings are errors.
- **Separate namespaces:** non-legacy kinds default to `generated-<kind>/`, `captures-<kind>/`, `candidate-<kind>/` and `comparison-<kind>.json`, all Git-ignored.

Only `spectrogram` is registered so far; Intensity is #34 step B.

## Maintainer workflow

Create a scoped issue and draft PR first, linking #17 and asking @Comet-Chaser-99 to agree fixture schema and comparison tolerances. Do not commit copyrighted/restricted recordings or downloaded Praat executables. Commit the generator, runner, comparator, test and verification docs only; generated outputs are ignored until reviewed for size/privacy and reproducibility.
