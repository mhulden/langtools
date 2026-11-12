# Praat R1 status audit

Snapshot: **2026-11-12**. **R1 is not complete.** This is an evidence map, not a
change to scope, numerical tolerances, acceptance requirements or ownership.
The authoritative requirements remain [the master specification](../REIMPLEMENTATION.md),
especially §2, §17 and §18. No application code changes accompany this audit.

## Baseline and evidence rules

The inspected upstream `main` is
[`7a7bd0b868c08ddaeaa03850e321c23f9a690514`](https://github.com/mhulden/langtools/tree/7a7bd0b868c08ddaeaa03850e321c23f9a690514).
Merged foundations are [#10](https://github.com/mhulden/langtools/pull/10)
(audio/annotation/workspace), [#14](https://github.com/mhulden/langtools/pull/14)
(analysis contracts), and [#16](https://github.com/mhulden/langtools/pull/16)
(playback and graphical tiers). Documentation/configuration work in
[#19](https://github.com/mhulden/langtools/pull/19) does not add product features.

The latest completed `praat` main-branch workflow inspected is
[run 42682583390](https://github.com/mhulden/langtools/actions/runs/42682583390)
at `732195aa900a9ed053ca08b16dcc792b9eafad3a` (success), an ancestor of the
snapshot. The [workflow][ci] runs offscreen tests on Linux, Windows and macOS
with Python 3.12, plus Linux/Python 3.13. This is evidence for that tested
revision; it is not a new test run of the audit snapshot or a manual device test.

“Partial” means inspected implementation and relevant tests exist but the complete
row or gate is unmet. “Contracts only” means types/validation, not a working
algorithm. “Unverified” means the cited evidence does not establish the required
behavior. Test names below identify existing tests; this documentation audit did
not rerun the application suite, oracle captures, hardware tests or benchmarks.

## R1 release matrix (§2)

| Area | Merged implementation and test evidence | Status and remaining R1 gap |
| --- | --- | --- |
| Workspace | [Workspace][workspace] implements typed audio/annotation objects and rename/copy/remove; [command tests][commands-tests] include lifecycle, failed saves and stale edits. [GUI][gui] supplies object selection and details. | **Partial.** A single main-window editor is present; independent editor lifecycle and the complete selection-driven typed action/dialog surface remain incomplete. See [compatibility limits][compat]. |
| Sound | [Audio I/O][audio], [sample axes][time], [waveforms][waveform], [transport][transport]; [audio/time tests][audio-tests] cover sample centers, nonzero domains, PCM16/24/32 round trips, quantization and bounded reads. [Transport tests][transport-tests] cover selected stereo playback, stop position and errors. | **Partial, substantial workflow present.** Real device/loopback timing and pinned-reference playback verification remain open. API sample/time conversion exists; full user-facing query coverage is not established. Declared export limits include integer rates and loss of nonzero WAV origin; retain them in compatibility reporting. |
| Long recordings | [Audio I/O][audio] reads requested frame ranges; [waveforms][waveform] produces min/max summaries. `test_waveform_crosses_read_blocks_with_bounded_memory` in [audio tests][audio-tests] and bounded-prefetch tests in [transport tests][transport-tests] exercise the interfaces. | **Partial evidence for the R1 interface requirement.** A one-hour memory/navigation stress result is unverified. Complete LongSound acceptance is R2, not an extra R1 feature requirement. |
| Spectrum | [Analysis contracts][contracts] and [contract tests][contracts-tests] define settings, grids, masks and provenance. | **Contracts only on main.** Gaussian calculation/display is open in #17; reference evidence is draft #21. Cursor queries and GUI/CLI analysis wiring are absent from these PRs. See the pinned PR table below. |
| Pitch | `PitchSettings`, candidate/result layout and validation in [contracts][contracts]; [tests][contracts-tests] cover chosen/count indices, voicing representation and undefined slots. | **Contracts only.** Filtered-AC algorithm, path decisions, F0/voicing queries, contour integration and differential gates are unimplemented in the inspected tree. |
| Formants | `FormantSettings` and sorted, padded frequency/bandwidth/count results in [contracts][contracts], with [validation tests][contracts-tests]. | **Contracts only.** Burg/resampling pipeline, computed frequency/bandwidth/count queries and reference comparisons are unimplemented. |
| Intensity | `IntensitySettings` and finite/undefined result validation in [contracts][contracts] and [tests][contracts-tests]. | **Contracts only.** Windowed calculation, contour/queries and distinct dB/energy/sones averaging are unimplemented. |
| Annotation | [Models][textgrid-model], [codec][textgrid-io], [commands][commands], [session][session], [graphical tiers][tiers]; [codec][textgrid-tests], [command][commands-tests] and [tier tests][tiers-tests] cover Unicode, full/short interchange, collapsed-caret split, single-mark movement and undo/redo. | **Partial.** Merge/delete (including D03), search, selected-text/range split cases and grouped drags remain missing. Native IME and reference-editor comparisons are unverified. A01–A12 detail follows. |
| Automation | [Python workspace/registry][workspace] and [CLI][cli]; [CLI tests][cli-tests] exercise inspect/create/convert/label/annotation CSV and headless import. | **Partial.** Shared annotation command execution exists; analysis commands, equivalent GUI/Python/CLI numerical output and the complete typed registry remain missing. Native Praat scripting is R2/R3, not an R1 blocker. |
| Export/graphics | [CLI][cli] exports annotation CSV and metadata JSON; [contracts][contracts] provide JSON-serializable analysis provenance records with [tests][contracts-tests]. | **Partial.** Measurement CSV plus an end-to-end settings/provenance JSON export is not implemented. A serializable record is not a working measurement export. Picture/PDF/PNG/SVG work belongs to later releases. |
| Audio transforms | [Audio tests][audio-tests] exercise PCM scaling, not an analysis resampler; [contracts][contracts] expose pre-emphasis settings only. | **Missing R1 primitives.** Analysis-internal resampling/pre-emphasis and their independent scientific tests are not present on main. #17's display pre-emphasis does not establish the pitch/formant resampling pipeline. User-facing transforms remain R2. |
| Voice | [Compatibility report][compat] explicitly describes acoustic analysis and numerical queries as incomplete; the master retains the later voice roadmap. | **Reporting obligation, not an R1 voice algorithm.** Preserve explicit lack of pulse/jitter/shimmer/harmonicity/Voice-report support in the release compatibility matrix. No voice implementation is required to close this R1 row. |
| Synthesis/other | [Demo generator][demo] supplies original synthetic audio for examples; no synthesis product command appears in [CLI][cli] or [GUI][gui]. | **Scope restriction currently respected.** Do not advertise synthesis or other specialized Praat objects as implemented. A fixture generator is not a user-facing synthesis feature. |

## Open work is separate from merged support

| PR and inspected head | Inspected evidence | What it does not close |
| --- | --- | --- |
| [#17](https://github.com/mhulden/langtools/pull/17), `d8adb41c8d0a851f8d942fb324f80348af0035e0` | Two-file diff: [Gaussian calculation/display][spectrogram] and [synthetic tests][spectrogram-tests]. Tests cover tone peak/bandwidth/sidelobes, two-tone resolution, FFT-bin grids, ranges/channels, silence and display/power separation. Ready for review; [run 43281514790](https://github.com/mhulden/langtools/actions/runs/43281514790) has four successful matrix jobs at this head. | Still **open**, not main. No GUI/CLI wiring, cursor queries, asynchronous analysis service or complete oracle gate. Synthetic self-tests do not prove reference parity. |
| [#21](https://github.com/mhulden/langtools/pull/21), `c148e7b41f70f5c8dc5736afa08a3c707e1320cf` | Draft [oracle harness][oracle] and [observed-results report][oracle-report] report a hashed Praat 7.0.03 binary, nine numerical matches and one expected short-input error using generated fixtures. [Run 42697464858](https://github.com/mhulden/langtools/actions/runs/42697464858) failed in Ruff before behavioral tests; its logs report 35 lint errors. | **Exploratory, not accepted parity.** Reported `atol=1e-9`, `rtol=0.0001` are explicitly unratified. Candidate provenance incorrectly names a base commit rather than uniquely identifying the compared algorithm; fix before acceptance. Display/Paint defaults, units interpretation and frequency-step semantics remain unresolved. Captures were not reproduced in this audit; this is one-platform spectrogram evidence, not a complete M0/M3 oracle. |

The #21 report records local capture metadata and references raw evidence not
committed in that PR. Its published summary must remain distinguishable from an
independently reproduced result. Freeze a correct candidate identity and declared
fixture comparison policy before treating those observations as a release gate.

## M0–M4 exit conditions (§18)

| Gate | Evidence already present | Why the exit condition is not yet established |
| --- | --- | --- |
| M0 — reference and contracts | Locked dependencies; explicit time/channel/revision contracts in [interfaces][interfaces] and [contracts][contracts]. #21 adds a candidate oracle manifest/capture path. | A reproducible accepted primary-oracle baseline, ratified budgets, initial reference UI capture set and release-blocking semantics are not all established. D03 remains explicitly unresolved. #21's exploratory capture does not close M0. |
| M1 — headless foundation | Merged #10/#14/#16 supply models, limited registry, WAV/TextGrid I/O, transactional edits, fake transport and original fixtures. The cited successful main workflow exercises three OSes. | The **implemented subset** has cross-platform test evidence, but the whole time/codec/annotation gate is not established: reference interchange, missing split/merge semantics and complete acceptance fixtures remain. Do not equate an early foundation milestone with the complete M1 exit condition. |
| M2 — usable annotation | Native label table, selection, single-mark drag, undo and actual-output adapter; [GUI][gui-tests], [tiers][tiers-tests], [playback GUI][playback-tests] and [adapter tests][portaudio-tests]. | A01–A12 are not all met: no search, boundary merge, grouped drag, recovery or complete reference/IME/device/platform interaction evidence. |
| M3 — validated analysis | Shared settings/results, provenance and stale-result predicate are merged. #17/#21 cover spectrogram implementation/reference work in progress. | Pitch, Burg formants and intensity algorithms are missing; no full analysis cancellation/cache service or shared GUI/CLI numerical workflow. Proposed numerical budgets remain proposed, not demonstrated gates. |
| M4 — release | Atomic saves, disk-change checks, documented limits, screenshots and prototype timing/buffering constraints. | Recovery, accessibility/IME evidence, measured performance, clean-host packaged launch, manual device results and a complete release report are absent or unverified. Every R1 row must close first. Wheel construction reported for #10 is not signed native packages or clean-host launch evidence. |

## Annotation acceptance map (A01–A12, §17)

| Case | Available evidence | Remaining gap |
| --- | --- | --- |
| A01 — nonzero-origin annotation creation | [Audio/time tests][audio-tests] cover nonzero axes; [CLI tests][cli-tests] cover grid creation; [model][textgrid-model] accepts explicit domains. | One end-to-end nonzero-origin audio → independent grid/tier-order acceptance fixture is not established by those separate tests. |
| A02 — IPA and tier switch | `test_native_label_editor_commits_and_keeps_selection` in [GUI tests][gui-tests]; Unicode round trips in [codec tests][textgrid-tests]. | Full tier-switch/composition scenario and native IME checks across platforms remain unverified. |
| A03 — caret insertion and undo | `test_unicode_split_undo_redo_and_monotonic_revision` in [command tests][commands-tests]. | Self-consistency is covered; reference label-split equivalence still needs a captured oracle fixture. |
| A04 — time/text-selected split | [SplitInterval][commands] supports a collapsed caret. | The complete selected-text/time-range decision table is unimplemented/unverified. |
| A05 — boundary and group drag | `test_boundary_preview_cancel_commit_and_single_undo` and real mouse-drag checks in [tier tests][tiers-tests]. | Single-mark support only; grouped multi-tier transaction is missing. |
| A06 — duplicate/crossing rejection | Atomicity in [command tests][commands-tests] and crossing/stale drag rejection in [tier tests][tiers-tests]. | Implemented paths have regression coverage; retain equivalent atomicity tests when grouped edits are added. This is subset coverage, not evidence for unsupported operations. |
| A07 — equal/different-label merge | Master §18 D03 documents the unresolved runtime rule. | No remove/merge command in [registry][workspace]; pinned-runtime merge fixture and implementation are missing. |
| A08 — selected playback/stop | [Transport tests][transport-tests] exercise source-clock stop and fake-sink timing; [GUI tests][playback-tests] cover cursor/selection. | Audible-range checks, agreed release threshold and physical device/loopback validation remain unverified. |
| A09 — reopen in Praat | [Codec tests][textgrid-tests] check semantic round trips, text encodings and precision. | Reopening exported fixtures in the chosen Praat executable is not established by internal round trips. #21 covers spectrograms, not TextGrid interchange. |
| A10 — find active tier | No search command in [registry][workspace] or [GUI][gui]. | Search/highlight/wrap implementation and reference behavior tests are missing. |
| A11 — annotation-only save/recover | [GUI tests][gui-tests] exercise annotation-only text editing and dirty-close behavior; [command tests][commands-tests] cover safe saves. | Autosave/recovery and the full save/recover scenario are missing. |
| A12 — close during work/device change | [Playback GUI tests][playback-tests] cover lifecycle/device errors/stale position; [GUI tests][gui-tests] reject stale waveform results. | Analysis-worker lifecycle is not implemented; manual device-change and committed-edit preservation evidence is incomplete. |

## Independent next slices

These are proposals for separate claims, not assignments or authorization to
edit another contributor's work. Coordinate shared files before starting.

| Proposed slice | Narrow boundary | Evidence needed to close it |
| --- | --- | --- |
| Reference annotation semantics | New oracle fixtures/report for D03 and A03/A04/A09; coordinate within the existing oracle lane. Leave editor/commands unchanged during capture. | Hashed reference, fixture inputs/outputs/settings and observed equal/different-label merge, split decision table and TextGrid reopening outcomes. |
| Intensity core | New pure `analysis/intensity.py` plus focused tests, using existing result types; coordinate before changing contracts. | DC/silence/stereo/amplitude-doubling cases and separate averaging methods; fixed reference/tolerances, masks/axes/units before numeric comparisons. No GUI claim. |
| Filtered-AC pitch core | New pure pitch module/tests; separately agree any shared resampling primitive. | Candidate counts, voicing/path decisions and F0 errors over tones, octave transitions, noise and gaps, with declared parameters/reference provenance. |
| Burg core and resampler | New pure formant/resampling modules/tests; agree primitive ownership with pitch work. | Independent resampler evidence, half-integer formant settings, bandwidth/count/order/missing-value comparisons and documented root matching. |
| Annotation search | Small command/service and later GUI adapter; coordinate registry/GUI changes with the editor contributor. | Active-tier target, Unicode substring highlight, wrap semantics and focus tests, including A10 reference capture. No concurrent broad editor rewrite. |
| Recovery | Persistence service/tests with a separately coordinated workspace hook; preserve current save/conflict behavior. | Crash/restart and corrupt/stale recovery handling, dirty state and committed edits preserved, annotation-only A11 workflow. |

Do not duplicate #17's algorithm or #21's harness. Analysis UI/CLI integration and
measurement export can follow stable core results; acceptance requires identical
outputs/settings through each surface. Performance, accessibility and packaging
need their own measured evidence before M4 closes.

## Documentation drift to reconcile separately

[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) still describes #10 as
unmerged and analysis contracts/playback as follow-ups, although #10/#14/#16 are
merged in this snapshot. [COMPATIBILITY.md](COMPATIBILITY.md) retains the original
56-test baseline and broad incomplete-analysis wording; its playback addendum and
[PLAYBACK_AND_TIERS.md](PLAYBACK_AND_TIERS.md) provide later evidence. Preserve
those historical test reports rather than presenting their counts as a fresh run.
This audit adds a pinned current map without rewriting those contributors' files.

## Audit validation

Validation is limited to the documentation change: all 13 §2 rows, all five
M0–M4 gates and all 12 annotation cases are mapped; referenced local files and
named commits/PR states were inspected. Relative file targets, reference-link
definitions, table structure, whitespace and the single-file diff were checked.
No new scientific parity, hardware timing or performance result is claimed.

[ci]: https://github.com/mhulden/langtools/blob/7a7bd0b868c08ddaeaa03850e321c23f9a690514/.github/workflows/praat.yml
[workspace]: ../src/langtools_praat/application/workspace.py
[gui]: ../src/langtools_praat/gui/app.py
[audio]: ../src/langtools_praat/io/audio.py
[time]: ../src/langtools_praat/model/time.py
[waveform]: ../src/langtools_praat/media/waveform.py
[transport]: ../src/langtools_praat/media/transport.py
[contracts]: ../src/langtools_praat/analysis/contracts.py
[textgrid-model]: ../src/langtools_praat/model/textgrid.py
[textgrid-io]: ../src/langtools_praat/io/textgrid.py
[commands]: ../src/langtools_praat/annotation/commands.py
[session]: ../src/langtools_praat/annotation/session.py
[tiers]: ../src/langtools_praat/gui/tiers.py
[cli]: ../src/langtools_praat/cli.py
[demo]: ../examples/make_demo.py
[commands-tests]: ../tests/test_commands.py
[audio-tests]: ../tests/test_time_audio.py
[transport-tests]: ../tests/test_transport.py
[contracts-tests]: ../tests/test_analysis_contracts.py
[textgrid-tests]: ../tests/test_textgrid.py
[tiers-tests]: ../tests/test_tiers.py
[cli-tests]: ../tests/test_cli.py
[gui-tests]: ../tests/test_gui.py
[playback-tests]: ../tests/test_playback_gui.py
[portaudio-tests]: ../tests/test_portaudio.py
[compat]: COMPATIBILITY.md
[interfaces]: INTERFACES.md
[spectrogram]: https://github.com/mhulden/langtools/blob/d8adb41c8d0a851f8d942fb324f80348af0035e0/praat/src/langtools_praat/analysis/spectrogram.py
[spectrogram-tests]: https://github.com/mhulden/langtools/blob/d8adb41c8d0a851f8d942fb324f80348af0035e0/praat/tests/test_spectrogram.py
[oracle]: https://github.com/mhulden/langtools/tree/c148e7b41f70f5c8dc5736afa08a3c707e1320cf/praat/oracle
[oracle-report]: https://github.com/mhulden/langtools/blob/c148e7b41f70f5c8dc5736afa08a3c707e1320cf/praat/oracle/docs/OBSERVED_RESULTS.md
