# elan-ng: Design and Specification for a Reimplementation of ELAN

Status: **Draft for review (Step 1)**. Nothing is implemented yet.
Target reference: **ELAN 7.1** (current release, The Language Archive, MPI for Psycholinguistics).
Manual reference: the online ELAN manual at <https://www.mpi.nl/corpus/html/elan/>. The HTML version documents ELAN 6.3 (last updated January 2022), so newer behavior has to be checked against the running program (see §8).
File format reference: `EAFv3.0.xsd` (December 2016) and the "EAF Annotation Format 3.0 and ELAN" document.

Manual section references are written like **[M 2.9]**, meaning section 2.9 of the manual. **[XSD]** means the EAF 3.0 schema. **[VERIFY]** marks a behavior I could not confirm from the docs. Each one is listed in §8 and must be checked against ELAN 7.1 before the matching code is written.

---

## Table of contents

1. [Overview](#1-overview)
2. [Behavior inventory](#2-behavior-inventory)
3. [File formats](#3-file-formats)
4. [Architecture and technology choice](#4-architecture-and-technology-choice)
5. [UI specification](#5-ui-specification)
6. [Testing and verification](#6-testing-and-verification)
7. [Roadmap](#7-roadmap)
8. [Open questions and risks](#8-open-questions-and-risks)

---

## 1. Overview

### 1.1 What ELAN is

ELAN (EUDICO Linguistic Annotator) is a desktop tool for creating time-aligned annotations on audio and video recordings. An annotation is a piece of text tied to a time interval, or to another annotation. Annotations are organized in **tiers**, and tiers form hierarchies: a transcription tier can have a dependent translation tier, a word tier, a morpheme tier, and so on. ELAN stores its data in the XML-based **EAF** format (`.eaf`), which has become a standard exchange format in language documentation archives (TLA, ELAR, AILLA, PARADISEC, and others).

Who uses it:

- **Language documentation and descriptive linguistics:** transcribing and translating field recordings, often with interlinear glossing.
- **Sign language research:** annotating video of signing on many parallel tiers (left and right hand, mouthing, non-manuals). Corpora such as the Corpus NGT and DGS-Korpus are EAF-based.
- **Gesture and multimodal research:** coding gesture phases and their timing relative to speech.
- **Conversation analysis and interaction research:** turn-taking and overlap, with one tier per speaker.
- **Psycholinguistics and child language:** coding behavior in experiments, and CHAT interoperability for CHILDES/TalkBank.

ELAN is written in Java with Swing. It supports several native media frameworks per platform (AVFoundation, Media Foundation/DirectShow, JavaFX, VLC, and Java Sound for WAV) [M 1.3]. Licensed GPL-3.0.

### 1.2 What this reimplementation aims for

**elan-ng** is a modern, cross-platform annotation tool that:

1. **Behaves like ELAN.** Same concepts, terms, modes, menus, default shortcuts and editing rules, so an ELAN user can switch without retraining.
2. **Is fully EAF-compatible.** Files round-trip with ELAN 7.1 without loss or warnings, including content elan-ng does not understand yet.
3. **Runs on one codebase** on Windows 10/11 (x64), macOS 12+ (Intel and Apple Silicon) and mainstream Linux (x86-64, glibc 2.31+), with one consistent media backend instead of one per OS.
4. **Has a UI-free, fully tested core.** The data model and constraint engine are a plain library, usable from scripts and tests without a GUI.

Working name: **elan-ng** (Python package `elan_ng`). It is a name for development only. Before any public release we should pick a name that cannot be mistaken for an MPI product (see §8.3).

### 1.3 Goals for v1 (the MVP and the next priority, i.e. P0 + P1)

- Open, edit and save `.eaf` 2.7–3.0 losslessly, always writing EAF 3.0.
- Open one or more audio/video files linked from the EAF. Synchronized playback with rate, volume, frame step, selection playback and loop.
- Waveform, timeline viewer, grid viewer, video window, text viewer, subtitle viewer.
- Annotation mode with ELAN's default shortcuts; Segmentation and Transcription modes (P1).
- Create, edit, delete, split, merge, move and resize annotations with correct propagation under all four stereotypes and the three time-propagation modes.
- Tier and tier-type management, controlled vocabularies (inline and external, multilingual), languages, participants.
- Unlimited undo/redo within a session.
- Single-document search with plain text and regular expressions.
- Import/export of Praat TextGrid, tab-delimited text, SRT/WebVTT and interlinear text.
- `.pfsx` preferences read and written per document.

### 1.4 Non-goals for v1 (deferred or out of scope)

- Interlinearization mode with lexicon integration (P2). Documented in §2.5.5.
- Multi-file search, structured (multi-tier, multi-file) search, find-and-replace across files (P2).
- Recognizers / automatic segmentation (P2), web services such as WebMAUS and Weblicht (Won't for v1).
- Spectrogram (P2), time-series viewer (Won't for v1), annotation density viewer (P1).
- CHAT, Toolbox, FLEx, Transcriber, Shoebox imports (P2). ELAN's IMDI/CMDI metadata panels (Won't for v1).
- Printing (Won't). Export to HTML and other print-like outputs is P2.
- Collaborative/online editing, cloud features (out of scope).
- A plugin API for third parties (P2; the import/export registry is designed to allow it).
- Reproducing Java/Swing look and feel pixel by pixel. We match layout and behavior, not the theme (§5.4).

---

## 2. Behavior inventory

Priorities: **P0** = MVP (milestones M0–M5), **P1** = next (M6–M8), **P2** = later, **Won't** = out of scope for the foreseeable future.

### 2.1 Data model

#### 2.1.1 Document and header — P0

| Concept | ELAN behavior | Notes and edge cases |
|---|---|---|
| Document | One `.eaf` file = one transcription. Root element `ANNOTATION_DOCUMENT` with `AUTHOR`, `DATE` (ISO dateTime), `VERSION`, `FORMAT` [XSD]. | ELAN writes `VERSION="3.0" FORMAT="3.0"` today. On save, `DATE` is updated to the current local time with offset. `AUTHOR` is kept (editable in File > Properties [VERIFY]). |
| Header | `HEADER` with `TIME_UNITS` (default `milliseconds`; enum also has `NTSC-frames`, `PAL-frames`) and deprecated `MEDIA_FILE`. | ELAN only uses milliseconds. If a file declares frames, read and keep it, and show a warning. Converting frames is P2. |
| Properties | `HEADER/PROPERTY NAME="…"` free key/value pairs. ELAN writes `URN` (`urn:nl-mpi-tools-elan-eaf:<uuid>`) and `lastUsedAnnotationId`. | Keep all properties in order. Update `lastUsedAnnotationId` on save. Generate a URN only if there is none. |
| Licenses | Zero or more `LICENSE` elements (text + `LICENSE_URL`), since 2.8. | Edit in File > Properties? [VERIFY]. P1 for editing, P0 for keeping. |
| Media descriptors | `MEDIA_DESCRIPTOR` with `MEDIA_URL` (absolute `file:///` URL), `RELATIVE_MEDIA_URL` (relative to the `.eaf`), `MIME_TYPE`, `TIME_ORIGIN` (offset in ms), `EXTRACTED_FROM` (audio extracted from a video). | Order matters: the first video is the "master" media in ELAN [VERIFY]. Media search order when the file is missing: absolute URL, then relative URL, then same directory as the `.eaf` with the same file name, then ask the user ("Locate media" dialog). |
| Linked files | `LINKED_FILE_DESCRIPTOR` (time-series, `.cha`/other) with `LINK_URL`, `RELATIVE_LINK_URL`, `MIME_TYPE`, `TIME_ORIGIN`, `ASSOCIATED_WITH`. | Keep them all. The time-series viewer is Won't for v1. |

#### 2.1.2 Time slots — P0

- A **time slot** is a point on the time axis. `TIME_SLOT_ID` plus an optional `TIME_VALUE` in ms (unsigned int) [XSD].
- **Aligned** slot: has a `TIME_VALUE`. **Unaligned** slot: no value. Its time is undetermined but its *order* relative to other slots is defined by the order of `TIME_SLOT` elements in `TIME_ORDER`.
- Unaligned slots only occur inside Time Subdivision chains (and very rarely in imported files). Root-tier and Included In annotations always have aligned begin and end slots.
- **Display time of an unaligned slot:** the viewers place unaligned boundaries by interpolating evenly between the nearest aligned boundaries in the same subdivision chain. Example: parent 1000–4000 with three children whose two inner slots are unaligned are shown at 2000 and 3000. [VERIFY that ELAN interpolates evenly per chain, and not by character count.] Interpolating along the global `TIME_ORDER` instead would be wrong: in ELAN-saved files, unaligned slots sit right after the chain's first slot, often between two aligned slots with the *same* value (seen in the M1 corpus).
- **Sharing:** a slot can be referenced by more than one annotation. This is how ELAN expresses "same point in time" structurally:
  - The first child of a Time Subdivision parent uses the parent's begin slot. The last child uses the parent's end slot. Adjacent siblings share one slot (end of one = begin of the next).
  - Moving a shared slot moves every annotation that uses it. This is what makes subdivision children follow their parent automatically.
- **Invariants** (enforced by the core, checked by `validate()`):
  - I1. For every alignable annotation, `begin < end` in the slot order. If both are aligned, `begin.value < end.value`. ELAN does not allow zero-length annotations [VERIFY: ELAN 7 may allow them on import].
  - I2. The aligned values in the slot order never decrease.
  - I3. Every slot is used by at least one annotation. Orphan slots are removed on save (ELAN does this too).

#### 2.1.3 Tiers — P0

| Attribute | Meaning |
|---|---|
| `TIER_ID` | The tier name. Unique among tiers. Any characters allowed (the schema uses `xsd:key`, not `xsd:ID`) [XSD]. |
| `LINGUISTIC_TYPE_REF` | Required. The tier type, which decides the stereotype and therefore the constraints. |
| `PARENT_REF` | The parent tier name. Missing → independent (root) tier. |
| `PARTICIPANT` | Free text: the speaker or signer. Used by Transcription mode, tier grouping and filters. |
| `ANNOTATOR` | Free text: who annotated the tier. |
| `DEFAULT_LOCALE` | Refers to a `LOCALE` (input method hint). Kept, and used to pick a keyboard layout hint [P2]. |
| `LANG_REF` | Refers to a `LANGUAGE` (content language), since 2.8. |
| `EXT_REF` | External reference (data category), overrides the one on the tier type, since 2.8. |

Rules:

- A tier's stereotype must be compatible with its parent: a root tier must use a type with no constraint ("None"). A dependent tier must use a type with one of the four stereotypes [M 2.1].
- Symbolic tiers (Symbolic Subdivision, Symbolic Association) can be parents of further tiers, but their children can only be symbolic too, because there is no time to subdivide. ELAN enforces this in the "Add tier" dialog by filtering the type list [VERIFY exact filter].
- Tier order in the file is the creation order. ELAN's *display* order is stored in the `.pfsx`, not in the `.eaf` (§3.3).
- Deleting a tier deletes all of its descendant tiers [M 2.1].

#### 2.1.4 Tier types (linguistic types) and stereotypes — P0

`LINGUISTIC_TYPE` attributes: `LINGUISTIC_TYPE_ID` (name), `TIME_ALIGNABLE` (boolean), `CONSTRAINTS` (refers to a `CONSTRAINT/@STEREOTYPE`), `GRAPHIC_REFERENCES` (boolean, legacy), `CONTROLLED_VOCABULARY_REF`, `EXT_REF`, `LEXICON_REF` [XSD].

The `CONSTRAINT` elements are boilerplate. ELAN writes all four, each time, with fixed descriptions:

```xml
<CONSTRAINT DESCRIPTION="Time subdivision of parent annotation's time interval, no time gaps allowed within this interval" STEREOTYPE="Time_Subdivision"/>
<CONSTRAINT DESCRIPTION="Symbolic subdivision of a parent annotation. Annotations refering to the same parent are ordered" STEREOTYPE="Symbolic_Subdivision"/>
<CONSTRAINT DESCRIPTION="1-1 association with a parent annotation" STEREOTYPE="Symbolic_Association"/>
<CONSTRAINT DESCRIPTION="Time alignable annotations within the parent annotation's time interval, gaps are allowed" STEREOTYPE="Included_In"/>
```

(The misspelling "refering" is ELAN's own and must be kept byte-for-byte when writing, to make diffs against ELAN output clean.)

| Stereotype | Annotation kind | Parent needed | Time-alignable | Children per parent | Gaps | Overlap between siblings |
|---|---|---|---|---|---|---|
| None (root) | Alignable | No | Yes | – | Yes | No (touching allowed) |
| Time Subdivision | Alignable | Yes | Yes | 1..n, ordered | **No**: children cover the parent exactly | No |
| Included In | Alignable | Yes | Yes | 0..n | Yes | No |
| Symbolic Subdivision | Reference | Yes | No | 1..n, ordered by `PREVIOUS_ANNOTATION` | n/a | n/a |
| Symbolic Association | Reference | Yes | No | **exactly 0 or 1** | n/a | n/a |

Sources: [M 2.1], [M 2.3], [XSD].

Edge cases:
- `TIME_ALIGNABLE` is redundant with the stereotype. If they disagree in a loaded file, trust the stereotype and keep the original attribute value on write unless the type is edited.
- A type can be changed only if no tier uses it, or if the change does not change alignability [VERIFY ELAN's exact rule in the "Change tier type" dialog].

#### 2.1.5 Annotations — P0

- **Alignable annotation** (`ALIGNABLE_ANNOTATION`): `ANNOTATION_ID`, `TIME_SLOT_REF1` (begin), `TIME_SLOT_REF2` (end), optional `SVG_REF` (legacy), `EXT_REF`, `LANG_REF`, `CVE_REF`; child `ANNOTATION_VALUE` (text, may be empty, may contain newlines).
- **Reference annotation** (`REF_ANNOTATION`): `ANNOTATION_ID`, `ANNOTATION_REF` (parent annotation), optional `PREVIOUS_ANNOTATION` (the sibling before it in a Symbolic Subdivision chain; missing on the first one), `EXT_REF`, `LANG_REF`, `CVE_REF`; child `ANNOTATION_VALUE`.
- **Parent of an alignable annotation on a dependent tier** is not stored in the file. It is derived: the annotation on the parent tier whose interval contains it (for Time Subdivision: the one whose slot chain contains it). The loader computes and caches this.
- **Times of a reference annotation** are derived: Symbolic Association children take the parent's interval. Symbolic Subdivision children divide the parent's interval evenly in chain order (display only).
- `CVE_REF` links the value to a CV entry ID. When the value is edited to text that matches no entry, ELAN clears `CVE_REF` [VERIFY].

#### 2.1.6 Controlled vocabularies — P0 (inline), P1 (external `.ecv`)

- `CONTROLLED_VOCABULARY` with `CV_ID`, optional `EXT_REF` (to an `EXTERNAL_REF TYPE="ecv"`), zero or more `DESCRIPTION LANG_REF=…`, and zero or more `CV_ENTRY_ML` (`CVE_ID`, optional `EXT_REF`) each with one or more `CVE_VALUE` (`LANG_REF` required, `DESCRIPTION` optional) [XSD].
- **Multilingual:** each entry has one value per language. The UI shows values in the "CV language" preference [M 2.6] and falls back to the first value.
- **Pre-2.8 files** use `CONTROLLED_VOCABULARY DESCRIPTION="…"` with `CV_ENTRY` children (text = value, `DESCRIPTION` attribute, optional `EXT_REF`). On load, convert to ML form with a single language `und` (or ELAN's convention, see [VERIFY] in §8). On save, write 3.0 form, as ELAN does.
- **External CV:** when `EXT_REF` points to an `.ecv` URL, the entries live in that file and are cached in the `.eaf`. ELAN stores a cached copy of the entries in the EAF as well [VERIFY]. Reload policy follows the preference "how external CV updates are handled" [M 1.3].
- **Editing with a CV:** the inline editor becomes a list with type-ahead ("starts with" or "contains", case-sensitive or not) [M 1.3]. Entries can have **shortcut keys** (stored in the `.pfsx` [VERIFY]) and **colors** (stored in the `.pfsx`) used in Segmentation mode and the timeline.
- **Edge case:** a value not in the CV can exist in a file (e.g. CV changed later). Show it, mark it with a warning style, never delete it.

#### 2.1.7 Languages, locales, lexicons, external references, ref links

| Element | Priority | Behavior |
|---|---|---|
| `LANGUAGE` (`LANG_ID`, `LANG_DEF` e.g. `http://cdb.iso.org/lg/CDB-00130975-001`, `LANG_LABEL`) | P0 keep, P1 edit | Used by tiers, annotations and CV values. ELAN offers an ISO 639-3 list. |
| `LOCALE` (`LANGUAGE_CODE`, `COUNTRY_CODE`, `VARIANT`) | P0 keep | Old input-method hints. |
| `LEXICON_REF` | P0 keep, P2 use | Lexicon service binding for Interlinearization mode. |
| `EXTERNAL_REF` (`EXT_REF_ID`, `TYPE` ∈ `iso12620`, `ecv`, `cve_id`, `lexen_id`, `resource_url`, `VALUE`) | P0 keep, P1 for `ecv` | Data category links (`iso12620`) are kept but not edited in v1. |
| `REF_LINK_SET` with `CROSS_REF_LINK` / `GROUP_REF_LINK` (3.0) | P0 keep, P2 edit | Referential links between annotations. Deleting an annotation must remove or fix links that refer to it, so the file stays valid (P0 even though links are not editable: see rule D6 in §2.2.4). |

#### 2.1.8 Participants and annotators — P1

There is no separate participant entity in EAF. Participants are the distinct values of `TIER/@PARTICIPANT`. ELAN uses them to group tiers, in Transcription mode, and in "Tier > Change tier attributes" for whole groups. We derive the list the same way.

### 2.2 Constraint rules (propagation engine) — P0

This is the core of ELAN's logic. Everything here is implemented in the UI-free `elan_ng.core.constraints` module, and each numbered rule has at least one unit test named after it (e.g. `test_R3_create_root_overlap_trims_neighbor`).

#### 2.2.1 Terms

- *Tier tree*: tiers form a forest. For an annotation *a*, `children(a)` = annotations on the direct child tiers whose parent is *a*. `descendants(a)` is the transitive closure.
- *Interval*: `[begin, end)` in ms, using derived display times for unaligned slots.
- *Propagation mode*: ELAN's **Options > Time propagation mode**: **Normal** (default), **Bulldozer**, **Shift** [VERIFY exact menu name and that this is still in 7.1]. It only affects changes on alignable tiers that would collide with other annotations.
- *Edit*: a single user action. Each edit is exactly one undoable command (§2.6.3), however many annotations it changes.

#### 2.2.2 Creating annotations

| ID | Situation | Rule |
|---|---|---|
| R1 | Create on a root tier, selection `[b,e)` with no overlap | New alignable annotation with two new aligned slots. Value = typed text (may be empty). |
| R2 | Create on a root tier, zero-length selection (crosshair only, no selection) | Not allowed. "New annotation here" is disabled [M 2.9]. |
| R3 | Create on a root tier, selection overlaps existing annotations, **Normal** mode | Existing annotations that are completely inside `[b,e)` are deleted (with their descendants, rule D1). Existing annotations that partly overlap are trimmed so they end at `b` or start at `e`. If an existing annotation strictly contains `[b,e)`, it is trimmed to end at `b`, and the part after `e` is **not** recreated [VERIFY: ELAN might reject instead]. Their dependents are adjusted with rules M3–M6. |
| R4 | Same as R3, **Bulldozer** mode | Existing annotations to the right of `b` that overlap are pushed right by the overlap amount; this cascades to the next ones. Those to the left that overlap are pushed left, with the same cascade, but cannot go below 0; if they would, the creation is rejected [VERIFY]. Dependents move with their parents (rule M2). |
| R5 | Same as R3, **Shift** mode | All annotations on **all tiers** that start at or after `b` are shifted right by `e − b`. [VERIFY: ELAN's Shift mode may shift only on the same tier tree, or by the overlap amount.] |
| R6 | Create on an Included In tier | Selection must lie inside exactly one parent annotation. If it extends past the parent, it is clipped to the parent. If it touches no parent, the action is disabled. Overlap with siblings under the same parent follows R3/R4/R5 but bounded by the parent's interval. |
| R7 | Create on a Time Subdivision tier, parent has no children | Creates one child covering the whole parent, sharing the parent's begin and end slots. Triggered by double-click inside the parent span on the child tier, or "New annotation here". |
| R8 | Create on a Time Subdivision tier with a time selection inside a child *c* | Splits *c* at the selection boundaries into up to three children; the middle one gets the typed value; the outer parts keep *c*'s value [VERIFY: ELAN might keep the value on the left part only]. New boundaries are **aligned** slots. |
| R9 | "New annotation before/after" on a Time Subdivision child *c* | Splits *c* in two equal halves. The new boundary is an **unaligned** slot. The new annotation is placed before/after *c* and is empty; *c* keeps its value [M 6.2.3]. |
| R10 | Create on a Symbolic Subdivision tier, parent has no children | One reference annotation, `PREVIOUS_ANNOTATION` missing. |
| R11 | "New annotation before/after" on a Symbolic Subdivision child *c* | Inserts a new reference annotation in the chain and rewrites `PREVIOUS_ANNOTATION` of the next sibling. |
| R12 | Create on a Symbolic Association tier | Allowed only when the parent has no child on this tier. Otherwise the action edits the existing child. |
| R13 | **Preference "Create annotations on dependent tiers"** [M 1.3] on | After creating a parent, recursively creates empty children on every dependent tier: Symbolic Association → one child; Time Subdivision / Symbolic Subdivision → one child covering the parent; Included In → one child with the parent's interval. [VERIFY Included In behavior.] All in the same undo step. |
| R14 | Frame snapping preference on [M 2.9] | `b` and `e` are rounded to the nearest frame boundary of the first video before rules R1–R6 apply. |
| R15 | "New annotation from begin–end time" dialog (Ctrl+Alt+Shift+N) [M 2.9] | Same as R1/R3–R6 applied to each selected tier in turn, all in one undo step. Value applied to each. |

#### 2.2.3 Changing time (resize and move)

Only alignable annotations with aligned slots can be retimed directly. Reference annotations are never retimed directly.

| ID | Situation | Rule |
|---|---|---|
| M1 | Resize/move a root or Included In annotation, no collision | Update its slot values. If a slot is shared with another annotation (e.g. parent begin = first subdivision child begin), every user of the slot moves. |
| M2 | **Move** (both boundaries by Δ) of a root annotation | Every descendant with aligned slots is shifted by Δ too. Unaligned slots need nothing. |
| M3 | **Resize** a root or Included In parent; Time Subdivision children | The outer children follow automatically through the shared slots. Inner aligned slots that end up outside the new interval are clamped to it; children whose length becomes 0 are deleted and their neighbor absorbs the space (rule D3) [VERIFY]. |
| M4 | Resize a parent; Included In children | Children completely outside the new interval are deleted (with descendants). Children partly outside are trimmed to the parent's new boundary. |
| M5 | Resize/move a parent; symbolic children | No change needed. Their displayed times are derived. |
| M6 | Collision with siblings on the same tier (root or Included In) | **Normal:** trim/delete the neighbors as in R3. **Bulldozer:** push the neighbors as in R4. **Shift:** shift everything after the moved boundary on all tiers by Δ, as in R5. [VERIFY: in Normal mode ELAN might instead stop the drag at the neighbor's boundary.] |
| M7 | Resize an inner boundary of a Time Subdivision chain | Only allowed between the neighboring boundaries (exclusive). Changing an unaligned slot makes it aligned. |
| M8 | Resize an outer boundary of a Time Subdivision child (= the parent's boundary) | Not allowed directly. The time interval of a child cannot be changed independently [M 2.1]. The user must resize the parent. |
| M9 | Resize so that `begin ≥ end` | Rejected. The UI stops dragging at 1 ms before the other boundary [VERIFY minimum length]. |
| M10 | Move below 0 ms, or past media end | Below 0: clamped to 0. Past media end: allowed, since ELAN does not tie annotations to the media length [VERIFY]. |
| M11 | "Shift all annotations" / "Shift annotations of active tier" [VERIFY menu] | Adds Δ to every aligned slot on the given scope. If the result would go below 0, the dialog refuses. |

#### 2.2.4 Deleting

| ID | Situation | Rule |
|---|---|---|
| D1 | Delete any annotation | All descendants are deleted too [M 2.1]. |
| D2 | Delete a root or Included In annotation | Its two slots are removed if no other annotation uses them. |
| D3 | Delete a Time Subdivision child *c* | No gaps allowed, so the previous sibling's end is extended to *c*'s end (it takes over *c*'s end slot). If *c* is the first child, the next sibling's begin is extended instead. If *c* is the only child, the parent ends up with no children. [VERIFY which neighbor absorbs the space.] |
| D4 | Delete a Symbolic Subdivision child | Remove it from the chain. Set the next sibling's `PREVIOUS_ANNOTATION` to *c*'s previous (or remove the attribute if *c* was first). |
| D5 | Delete a tier | Deletes all annotations on it and all its descendant tiers, after a confirmation dialog listing them. |
| D6 | Delete an annotation referenced by a `CROSS_REF_LINK` / `GROUP_REF_LINK` | Cross links that refer to it are removed. Group links have it removed from `REFS`; a group link left empty is removed. [VERIFY ELAN 7.1 behavior; this is our rule to keep files schema-valid.] |
| D7 | "Clear annotation value" (Ctrl+Delete) | Sets the value to empty and clears `CVE_REF`. Structure unchanged. |

#### 2.2.5 Split, merge, and other structural edits

| ID | Operation | Rule |
|---|---|---|
| S1 | Split annotation at the crosshair (root/Included In) [VERIFY name in Annotation menu] | Two annotations `[b,t)` and `[t,e)`. The left one keeps the ID and value; the right one is new and empty. Included In children are given to the half that contains them (a child crossing `t` is split too [VERIFY]). Time Subdivision children: the chain is split at `t` (a new aligned slot inserted). Symbolic children stay with the left half. |
| S2 | Merge with next / previous (root/Included In) | The new interval is the union. Value = the two values joined by a single space [VERIFY]. Children of both are moved under the merged annotation. Symbolic Association children: both values joined by a space into the surviving child [VERIFY]. |
| S3 | Copy annotation (Ctrl+C) / paste (Ctrl+V) / paste here (Ctrl+Shift+V) | Copy puts the annotation (value, time, tier name) on the clipboard; "paste" puts it on the active tier at the original time; "paste here" pastes it at the crosshair. Pasting follows R1–R6 for collisions. "Group" variants copy the annotation with all descendants [M 6.2.4]. |
| S4 | Duplicate annotation (Ctrl+D) | Copies the selected annotation to the active tier at the same time [M 6.2.4]. Allowed only if the active tier is alignable and not the source tier. |
| S5 | Tokenize tier [M 2.12] | For each annotation on the source tier, splits its value on a delimiter and creates children on a Symbolic Subdivision or Time Subdivision tier. P1. |
| S6 | Annotations from overlaps / gaps / subtraction [M 2.14, 2.15] | Compute intervals from other tiers and create root annotations. P2. |
| S7 | Copy tier, merge tiers, reparent tier ("Change parent") [M 2.13] | Creates or moves annotations under the target's constraints. Reparenting must check that each annotation has a valid parent under the new parent tier; annotations without one are reported and the operation cancelled or the orphans dropped, as the user chooses [VERIFY ELAN's dialog]. P1. |

#### 2.2.6 Engine design rules

- The engine works on an immutable-ish document snapshot and produces a **change set** (a list of primitive operations: add/remove slot, set slot value, add/remove annotation, set value, set attribute). Applying the change set gives the new state, and its inverse gives undo. This keeps every rule above testable without a UI.
- Before committing a change set, the engine runs the invariant checker (I1–I3 plus the per-stereotype rules in §2.1.4). A violation is a bug: in debug builds it raises; in release builds the edit is rejected and logged.
- **Reused-from-ELAN note:** none of ELAN's Java code is copied. If, when implementing R3–R5/M6, reading ELAN's `TierImpl` / `TimeSlot` logic turns out to be the only reliable way to settle a [VERIFY], we will record it here as a GPL-3.0-derived part and license the repository accordingly (see §8.3).

### 2.3 Media — P0 unless noted

| Feature | ELAN behavior | Priority | Edge cases |
|---|---|---|---|
| Linked media | Several media files per document. Up to four videos shown at once [VERIFY limit in 7.1]; audio files are used for playback and waveform. Edit > Linked files to add/remove/reorder. | P0 one audio + one video; P1 several videos | Missing media → "Locate media" dialog; the document still opens without media. |
| Master media | One media file drives the clock. ELAN uses the first video, or else the first audio [VERIFY]. | P0 | Different durations: document length = max over all media (after offsets). |
| Offsets / synchronization | `TIME_ORIGIN` on a descriptor: the media position that corresponds to time 0 of the document. Set in Synchronization mode. | P1 | Negative effective offsets are not allowed; Synchronization mode warns. |
| Playback | Play/pause (Ctrl+Space), go to start (Ctrl+B), go to end (Ctrl+E). | P0 | |
| Rate | 0–200% slider in the Controls tab; Ctrl+Alt+R switches to a predefined rate [M 6.2.2]. Pitch is kept (time-stretched audio) [VERIFY]. | P0 slider, P1 presets | |
| Volume | Slider; Ctrl+Shift+R switches to a predefined volume [M 6.2.2]. Per-media volume for several files [VERIFY]. | P0 | |
| Stepping | One frame (Ctrl+Left/Right), one second (Shift+Left/Right), one pixel [M 6.2.2]. Frame duration from the master video; 40 ms if there is no video [VERIFY]. | P0 | Variable frame rate video: use actual frame timestamps, not 1/fps. |
| Selection playback | Play selection (Shift+Space); play around selection (Ctrl+Shift+Space) with a margin set in preferences [M 6.2.5]. | P0 / P1 | |
| Loop mode | Ctrl+L toggles; selection playback then repeats until stopped [M 6.2.5]. | P0 | Pause between loops is a preference [VERIFY]. |
| Go to time | Ctrl+G opens a time-entry dialog [M 6.2.2]. | P0 | Accepts `hh:mm:ss.mss` and plain ms. |
| Formats | Whatever the platform framework supports. WAV (PCM) is the safe choice; ELAN shows the waveform only for WAV. | P0 | We decode with FFmpeg, so MP4/H.264, MOV, MKV, WebM, MPEG-2, MP3, AAC, FLAC, OGG/Opus all work on every OS. We also show waveforms for any audio (a deliberate improvement). |
| Media clipping | Export the selection as a separate media file (via a configured script in ELAN) [M 1.3]. | P2 | |
| Detached video | Video windows can be detached and resized. | P1 | |

### 2.4 Viewers

| Viewer | ELAN behavior | Priority |
|---|---|---|
| **Timeline viewer** (multi-tier) | Horizontal time axis (ruler) with one row per visible tier. Annotations drawn as boxes with their value. Click selects an annotation; drag on empty space selects a time interval; double-click opens the inline editor. Tier labels on the left: double-click sets the active tier; drag to reorder [M 6.1]. Right-click menus on labels and annotations. Symbolic annotations drawn in a separate preference color [M 1.3]. Zoom levels, plus "Fit to window". | P0 |
| **Waveform** (Signal viewer) | Waveform of the audio for the visible time range, synchronized with the timeline zoom. Stereo drawn as separate channels or merged (option). Click moves the crosshair; drag selects. | P0 |
| **Spectrogram** | Added in ELAN 5.x as a viewer option. Settings: window length, frequency range, color scheme. | P2 |
| **Interlinear viewer** | Annotations shown as stacked blocks per root annotation, following the tier hierarchy (like interlinear glossed text). | P1 |
| **Grid viewer** | Table of the annotations on one tier: Nr, Annotation, Begin Time, End Time, Duration. A tier dropdown; option to add columns for the child tiers. Click goes to the annotation; double-click edits. | P0 |
| **Text viewer** | All annotation values of one tier as running text, with a selectable separator; clicking a word selects that annotation. | P1 |
| **Subtitle viewer** | Up to four rows that show the value of the annotation on a chosen tier at the crosshair. | P1 |
| **Annotation density viewer** | An overview bar of the whole media showing where annotations are; click jumps there. Ctrl+Shift+Left/Right move one pixel in it [M 6.2.2]. | P1 |
| **Video viewer(s)** | Video frame at the crosshair, with a context menu for zoom, aspect ratio and detaching. | P0 (one), P1 (several) |
| **Time-series viewer** | Plots tracks from linked time-series files (e.g. motion capture). | Won't for v1 |
| **Lexicon, Comments, Recognizer, Metadata, Controls tabs** | Tabs in the upper right pane. | Controls P0, Comments P2, Lexicon P2, Recognizer P2, Metadata Won't |

Common behavior:

- **Crosshair vs. selection:** the crosshair (vertical red line) is the media time. The selection is a separate time interval, shown as a highlighted band (light blue). They are independent: moving the crosshair does not clear the selection. **Selection mode** (Ctrl+K): when on, clicking extends the selection from the crosshair [M 6.2.5] [VERIFY precise semantics]. Esc clears the selection [M 6.2.3].
- **Active tier and active annotation:** one tier is active (bold label, highlight color). One annotation can be active (selected), shown with a darker fill. Ctrl+Up/Down change the active tier; Alt+Left/Right/Up/Down move the active annotation [M 6.2.3].
- **Zoom:** discrete zoom levels expressed as a percentage, e.g. 10%, 25%, 50%, 75%, 100%, 150%, 200%, 300%, 400%, 500%, 750%, 1000% [VERIFY exact list], where 100% = 10 ms per pixel [VERIFY]. Ctrl+mouse wheel zooms [VERIFY]. Waveform and timeline always share the zoom.
- **Scrolling and auto-follow:** during playback, when the crosshair leaves the visible range, the view jumps by one page ("page scroll") [VERIFY]. Ctrl+PgUp/PgDn move one page [M 6.2.2]. Shift+A centers the selection [M 6.2.5]. A preference sets horizontal scroll speed [M 1.3].

### 2.5 Modes

Selected from the **Options** menu. Only one mode at a time per document window [M 3].

#### 2.5.1 Annotation mode — P0

- **Purpose:** the general-purpose mode. Create and edit annotations on any tier, manage tiers and types.
- **Layout:** see §5.1.1. Video and the tab pane (Grid, Text, Subtitles, Lexicon, Comments, Recognizers, Metadata, Controls) on top; media controls in the middle; waveform, then timeline viewer below.
- **Keyboard workflow:** select a time interval with the mouse (or Shift+Enter at begin and end, [M 2.9]), then Alt+N / Ctrl+Alt+N to open the inline editor on the active tier, type, Ctrl+Enter to commit, Esc to cancel. Navigate with Alt+arrows, Ctrl+Up/Down. Play with Ctrl+Space and Shift+Space.

#### 2.5.2 Synchronization mode — P1

- **Purpose:** align several media files by setting offsets (`TIME_ORIGIN`).
- **Layout:** all video windows are shown; the media controls get a "Player" selector with entries for "All players" and each separate file. Each player has its own crosshair position.
- **Workflow:** select one player, step it to a recognizable event (e.g. clap), select the next, step it to the same event, click "Apply current offsets". Offsets are shown per file in ms [M 3.2]. Annotations cannot be edited in this mode.
- **Edge cases:** an offset that would make a media start before 0 is rejected; the master file defines time 0.

#### 2.5.3 Transcription mode — P1

- **Purpose:** fast keyboard-only transcription of an already segmented recording [M 3.3].
- **Layout:** a table. Rows = annotations in time order; columns = **tier types** chosen in the settings dialog. Column 1 can be any type; further columns must be Symbolic Association children of column 1's type, so they line up row by row [M 3.3]. Each column shows annotations from all tiers of that type (all participants), so rows from different speakers interleave in time order. Video and waveform/timeline are shown above or beside the table [VERIFY default layout].
- **Settings:** font size, number of columns and their types, tier selection (show/hide tiers), tier colors, "auto-play when moving to a cell", "loop" [VERIFY names], "don't create empty annotations" [VERIFY].
- **Keyboard workflow** (defaults to be confirmed from Edit > Preferences > Shortcuts > Transcription mode in ELAN 7.1 [VERIFY all]): move between cells with Up/Down (or Enter to commit and go down); Tab / Shift+Tab move between columns; play/pause the current cell's segment; play from the cell's start; merge with next / delete annotation; toggle loop. Moving to a cell plays its segment if auto-play is on.
- **Edge cases:** a Symbolic Association cell that has no annotation yet is shown empty; typing in it creates the annotation (R12).

#### 2.5.4 Segmentation mode — P1

- **Purpose:** create time segments on one tier with keystrokes while listening [M 3.4].
- **Layout:** like Annotation mode, with a settings panel in the tab pane. Only root tiers and Included In tiers can be shown. The editable tier is shown on top, right below the ruler, and highlighted; a red marker shows its position in the tier list [M 3.4].
- **Methods:**
  - *Two keystrokes per annotation:* Enter marks the begin, Enter again marks the end.
  - *One keystroke per annotation:* each Enter ends the current segment and starts the next one (adjacent segments).
  - *One keystroke, fixed duration:* each Enter creates a segment of a configured length; the key marks the begin or the end (option).
  - *Delayed mode:* a configured number of ms is subtracted from every keystroke to compensate for reaction time.
- **Keys:** Enter creates/ends segments; a CV entry's shortcut key replaces Enter and also sets the value; Up/Down change the editable tier without pausing [M 3.4]. Each segment is its own undo step. No text entry in this mode.
- **Edge cases:** segments overlapping existing annotations follow R3–R5 [VERIFY ELAN does this, and not just refuse].

#### 2.5.5 Interlinearization mode — P2

- **Purpose:** interlinear glossing with lexicon lookup: tokenize utterances into words, words into morphemes, and fill glosses from a lexicon (ELAN's built-in lexicon component or an external one through `LEXICON_REF`) [M 3.5].
- **Layout:** a vertical list of root annotations, each rendered as interlinear blocks (like the Interlinear viewer) with editable cells; a lexicon panel on the side.
- **Workflow:** select a tier pattern (e.g. utterance → word → morph → gloss), run the analyzers ("Parse", "Gloss"), confirm suggestions with keyboard.
- **For v1:** documented only. The data model already supports everything it needs (Symbolic Subdivision and Association, `LEXICON_REF`).

### 2.6 Editing (UI level) — P0 unless noted

#### 2.6.1 Annotations

| Action | ELAN | Shortcut |
|---|---|---|
| New annotation here | Opens the inline editor for the selection on the active tier | Alt+N [M 2.9] / Ctrl+Alt+N [M 6.2.3] (manual is inconsistent; see §8) |
| New annotation before / after | Rules R9, R11 | Ctrl+Shift+N for both in the manual table [M 6.2.3]; the "before" key needs to be confirmed [VERIFY] |
| Modify annotation | Inline editor on the active annotation | Ctrl+Alt+M; Ctrl+Shift+E; Shift+E [M 6.2.3, 2.9] |
| Switch inline editor ↔ "Edit annotation" dialog | | Shift+Enter in the editor [M 6.2.3] |
| Commit / cancel | Commit on Ctrl+Enter (or Enter, by preference); cancel on Esc. Leaving the editor (focus lost) discards by default (preference) [M 1.3]. | Ctrl+Enter / Esc |
| Clear value | Rule D7 | Ctrl+Delete |
| Delete annotation | Rules D1–D4, D6 | Ctrl+Alt+D |
| Retime by dragging | Drag a boundary or the body of the active annotation in the timeline viewer, with a modifier [VERIFY which modifier: ELAN uses Alt+drag on Windows/Linux and a different key on macOS]. Rules M1–M10. | mouse |
| Modify annotation time dialog | Type begin/end exactly [VERIFY menu name] | P1 |
| Split, merge, copy, paste, duplicate | Rules S1–S4 | Ctrl+C, Ctrl+Alt+C, Ctrl+D, Ctrl+V, Ctrl+Alt+V, Ctrl+Shift+V, Ctrl+Alt+Shift+V [M 6.2.4] |
| Multi-select across tiers | Alt+click [M 6.2.3] | P1 (used for multi-delete and copy group) |
| Spell checking | [M 2.10] | P2 |

The **inline editor** is a text box drawn over the annotation in the timeline viewer. It supports multi-line text (Enter inserts a newline unless the preference swaps it), a right-click menu to switch the input method/character set, and for CV tiers a filtered list instead of free text [M 2.9].

#### 2.6.2 Tiers and tier types

| Action | Shortcut | Priority |
|---|---|---|
| Add tier (name, parent, type, participant, annotator, language, color, font) | Ctrl+T | P0 |
| Change tier attributes (same fields; renaming updates `PARENT_REF` of children) | | P0 |
| Delete tier (rule D5) | Ctrl+Alt+T | P0 |
| Add tier type | Ctrl+Shift+T | P0 |
| Change / delete tier type | | P0 |
| Edit controlled vocabularies | Ctrl+Shift+C | P0 inline, P1 external |
| Reparent tier, copy tier, merge tiers, tokenize | | P1 |
| Import tiers / tier types / CVs from another EAF or template (`.etf`) | | P1 |
| Hide/show tiers, sort tiers (by hierarchy, by type, by participant, by annotator, by language) | | P0 hide/show, P1 sort |

A **template** (`.etf`) is an EAF file without annotations or media (File > Save as template, Ctrl+Shift+Alt+S [M 6.2.1]); "New" can start from one. P1.

#### 2.6.3 Undo and redo — P0

- Ctrl+Z / Ctrl+Y [M 6.2.7]. On macOS also Cmd+Shift+Z as an alias (§5.4).
- Every user-level edit (including complex ones: tokenize, R13, paste group) is one undo step [M 2.11].
- Undo history is per document, unlimited in size by default (memory-capped by a preference), and cleared when the document is closed. Saving does not clear it.
- Media actions (play, seek, zoom, selection) are not undoable. Tier visibility and order are not undoable [VERIFY].
- Segmentation mode: one step per created segment [M 3.4].

### 2.7 Search

| Feature | ELAN | Priority |
|---|---|---|
| Find (Ctrl+F) in the current document [M 4.1] | A search dialog: query text, tier(s), "regular expression", "case sensitive", substring vs. exact match; result list with tier, value, begin, end; clicking a result jumps to it. | P0 substring and case flags; P1 regex |
| Regex syntax | Java regular expressions [M A]. | We use Python `re`, which differs in a few areas (possessive quantifiers and atomic groups exist in Python 3.11+; Unicode classes differ). Document the differences in the dialog's help; flag queries that use Java-only syntax. |
| Replace in current document | | P1 |
| Search in multiple EAF files (Ctrl+Shift+F) [M 4.2] | Search a set of files or a folder. | P2 |
| Find & replace in multiple files [M 4.3] | | P2 |
| Structured multi-tier search [M 4.4] | Constraints across tiers: "X on tier A overlaps Y on tier B", within distance, dependency relations. | P2 |
| Search for overlaps (annotation overlap detection) [M 2.14] | | P2 |

### 2.8 Import and export

| Format | Direction | Priority | Notes |
|---|---|---|---|
| EAF 2.7, 2.8, 3.0 | read | P0 | Older EAF (2.0–2.6) read best-effort, P1. |
| EAF 3.0 | write | P0 | Always write 3.0 (ELAN default). |
| EAF 2.7 | write | P2 | ELAN offers "save in EAF 2.7 format" as a preference [M 1.3]. |
| `.etf` template | read/write | P1 | Same schema, no annotations. |
| `.pfsx` preferences | read/write | P0 read and keep, P1 write all settings | See §3.3. |
| `.ecv` external CV | read | P1 | Writing (CV editor for external CVs) P2. |
| Praat TextGrid (long and short text formats, UTF-8/UTF-16) | import/export | P1 | Interval tiers → root tiers; point tiers → root tiers with short annotations of configurable length [VERIFY ELAN default]. Export: choose tiers; dependent tiers exported as interval tiers with computed times. |
| Tab-delimited text | import (CSV/TSV with column mapping) / export | P1 | Export options mirror ELAN's dialog: which tiers, columns (begin, end, duration, in hh:mm:ss.ms / ss.msec / ms / frames), include tier name, participant, annotator, file name [VERIFY full list]. |
| Plain text / traditional transcript | export | P1 | |
| Interlinear text | export | P1 | |
| SRT, WebVTT | import/export | P1 | ELAN exports "subtitles text"; WebVTT import is our addition. |
| CHAT (`.cha`, CHILDES) | import/export | P2 | Needs the CLAN tier-naming conventions. |
| Toolbox / Shoebox | import/export | P2 | Marker mapping, typ file. |
| FLEx (`.flextext`) | import/export | P2 | |
| Transcriber (`.trs`) | import | P2 | |
| ELAN's "Export multiple files as…" | batch | P2 | |
| HTML, SMIL, image of timeline | export | Won't (v1) | |

All import/export goes through a registry of `Importer` / `Exporter` plugins (§4.3) so formats can be added later without touching the core.

### 2.9 Keyboard shortcuts

Default shortcuts from [M 6.2] (ELAN 6.3 manual). On macOS, ELAN maps **Ctrl → Cmd** for most menu shortcuts [VERIFY per item]. We keep all of them, with the same macOS mapping; the column "Keep" says otherwise only when there is a conflict.

| Category | Action | Default (Win/Linux) | Keep |
|---|---|---|---|
| File | Save | Ctrl+S | yes |
| File | Save as | Ctrl+Shift+S | yes |
| File | Save as template | Ctrl+Shift+Alt+S | yes |
| File | Close window | Ctrl+W | yes |
| File | Exit | Ctrl+Q | yes |
| File | Open | Ctrl+O | yes |
| File | New | Ctrl+N | yes |
| File | Print / Page setup / Print preview | Ctrl+P / Ctrl+Shift+P / Ctrl+Alt+P | no (printing is Won't); keys reserved |
| Window | Previous / next document window | Shift+Up / Shift+Down | yes, but only when focus is not in a text field (§8) |
| Media | Play / pause | Ctrl+Space | yes |
| Media | Go to begin / end | Ctrl+B / Ctrl+E | yes |
| Media | Previous / next scroll view (page) | Ctrl+PgUp / Ctrl+PgDn | yes |
| Media | Back / forward 1 second | Shift+Left / Shift+Right | yes |
| Media | Back / forward 1 frame | Ctrl+Left / Ctrl+Right | yes |
| Media | Back / forward 1 pixel (density viewer) | Ctrl+Shift+Left / Ctrl+Shift+Right | yes |
| Media | Predefined playback rate | Ctrl+Alt+R | yes |
| Media | Predefined volume | Ctrl+Shift+R | yes |
| Media | Go to time | Ctrl+G | yes |
| Annotation | New annotation here | Ctrl+Alt+N (and Alt+N per [M 2.9]) | yes, both |
| Annotation | Modify annotation | Ctrl+Alt+M | yes |
| Annotation | Inline-edit active annotation | Ctrl+Shift+E, Shift+E | yes |
| Annotation | Data category selection | Alt+Shift+M | reserved (P2) |
| Annotation | Clear value | Ctrl+Delete | yes |
| Annotation | Delete annotation | Ctrl+Alt+D | yes |
| Annotation | New annotation before / after | Ctrl+Shift+N (both listed) | yes; "before" to be confirmed |
| Annotation | New annotation from begin–end time | Ctrl+Alt+Shift+N | yes |
| Annotation | Begin/end at crosshair then open editor | Shift+Enter (twice) | yes |
| Annotation | Previous / next annotation | Alt+Left / Alt+Right | yes |
| Annotation | Annotation above / below | Alt+Up / Alt+Down | yes |
| Annotation | Multi-select | Alt+click | yes |
| Inline editor | Commit / cancel | Ctrl+Enter / Esc | yes |
| Inline editor | Switch to edit dialog | Shift+Enter | yes |
| Tier | New tier / delete tier | Ctrl+T / Ctrl+Alt+T | yes |
| Tier | New tier type | Ctrl+Shift+T | yes |
| Tier | Edit CV | Ctrl+Shift+C | yes |
| Tier | Previous / next active tier | Ctrl+Up / Ctrl+Down | yes |
| Tier | Edit linked files | Ctrl+Alt+L | yes |
| Viewer | Show empty slots in the multi-tier viewer | Ctrl+Alt+Shift+? (incomplete in manual) | [VERIFY] |
| Copy/paste | Copy annotation / group | Ctrl+C / Ctrl+Alt+C | yes |
| Copy/paste | Duplicate | Ctrl+D | yes |
| Copy/paste | Paste / paste group | Ctrl+V / Ctrl+Alt+V | yes |
| Copy/paste | Paste here / paste group here | Ctrl+Shift+V / Ctrl+Alt+Shift+V | yes |
| Copy/paste | Copy current time | Ctrl+Alt+G | yes |
| Selection | Play selection | Shift+Space | yes |
| Selection | Play around selection | Ctrl+Shift+Space | yes |
| Selection | Clear selection | Alt+Shift+C; Esc | yes |
| Selection | Clear selection and leave selection mode | Ctrl+Shift+Z | yes |
| Selection | Crosshair to selection begin / end | Ctrl+Shift+K / Ctrl+/ | yes |
| Selection | Crosshair to selection center | Ctrl+Alt+/ | yes |
| Selection | Toggle selection mode | Ctrl+K | yes |
| Selection | Toggle loop mode | Ctrl+L | yes |
| Selection | Center selection in viewer | Shift+A | yes, only outside text fields |
| Search | Find / search multiple files | Ctrl+F / Ctrl+Shift+F | yes / reserved (P2) |
| General | Undo / redo | Ctrl+Z / Ctrl+Y | yes (+ Cmd+Shift+Z on macOS) |
| Segmentation mode | Mark begin/end | Enter | yes |
| Segmentation mode | Previous / next editable tier | Up / Down | yes |
| Transcription mode | (see §2.5.3) | [VERIFY] | yes |

Shortcuts are configurable (Edit > Preferences > Shortcuts in ELAN, stored in the user preferences [VERIFY file]). P1: we provide the same editor and store overrides in our user settings (§2.10).

Note: Ctrl+Shift+Z is "clear selection" in ELAN, not redo. On macOS we add Cmd+Shift+Z as redo only if it does not collide with ELAN's mapping there [VERIFY]; otherwise ELAN's mapping wins.

### 2.10 Preferences and UI state

ELAN keeps two levels of preferences [M 1.3]:

1. **Global (user) preferences:** Edit > Preferences > Edit Preferences. Categories: Editing, CV, Media, Metadata, Platform/OS, Preferences, User Interface, Viewers [M 1.3]. Stored in ELAN's user directory (`~/.elan_data/` on Linux/Windows, `~/Library/Preferences/ELAN/` on macOS [VERIFY]).
2. **Per-document preferences:** a `.pfsx` file next to the `.eaf` (same base name), or in a configured "preferences location" [M 1.3]. Holds: tier order, visible tiers, tier colors and fonts, active tier, zoom, selection, crosshair position, media positions, viewer layout, sort order, mode-specific settings [VERIFY full key list against real `.pfsx` files].

What we persist:

| State | Where | Priority |
|---|---|---|
| Global settings (editing, CV, media, UI, viewers, shortcuts) | OS-standard config dir via `QStandardPaths` (`%APPDATA%\elan-ng`, `~/Library/Application Support/elan-ng`, `$XDG_CONFIG_HOME/elan-ng`) as TOML | P0 basic, P1 full |
| Per-document state | `.pfsx` next to the `.eaf`, in ELAN's format, so ELAN and elan-ng share tier order, colors, etc. Unknown keys kept. | P0 read/keep, P1 write |
| Recent files, window geometry | global settings | P0 |
| Backups | ELAN keeps N backups (`.eaf.001` … [VERIFY naming]) and supports `.lock` files [M 1.3] | P1 backups, P1 lock files |
| Automatic save | ELAN option [VERIFY] | P1 |
| Editing preferences we must honor from P0: commit on focus loss, Enter vs Ctrl+Enter to commit, frame snapping, create dependent annotations, CV matching mode | global | P0 |

### 2.11 Automatic processing (recognizers) — P2

ELAN has a "Recognizer" tab with built-in and plugin recognizers (Audio/Video Recognizer API, current version 4.1). Built-in examples: silence recognizer (segments audio into sound/silence using an amplitude threshold, minimum silence and minimum sound duration), and "Create annotations from silence". Web-service recognizers include WebMAUS (forced alignment) and others [M 2.17].

For elan-ng:

- P2: a built-in **silence detector** on our own peak/energy data (threshold in dB relative to max, min silence ms, min sound ms; output to a new or existing root tier), with preview on the waveform before committing (one undo step).
- P2: a small recognizer interface (`run(media, params) -> segments`) so local tools (e.g. VAD, Whisper-based segmenters) can be added later. Network services are Won't for v1.
- Not planned: compatibility with ELAN's Java recognizer plugins.

---

## 3. File formats

### 3.1 EAF (ELAN Annotation Format)

Encoding: **UTF-8** with an XML declaration. ELAN writes `<?xml version="1.0" encoding="UTF-8"?>`. Reading must accept any encoding declared in the XML header (lxml does this).

Namespaces: the root carries `xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"` and `xsi:noNamespaceSchemaLocation="http://www.mpi.nl/tools/elan/EAFv3.0.xsd"`. Keep the value from the source; write the 3.0 URL for new files.

#### 3.1.1 Element order

`ANNOTATION_DOCUMENT` children, in this order (sequence in [XSD]):

1. `LICENSE` *
2. `HEADER` (1)
3. `TIME_ORDER` (1)
4. `TIER` *
5. `LINGUISTIC_TYPE` *
6. `LOCALE` *
7. `LANGUAGE` *
8. `CONSTRAINT` *
9. `CONTROLLED_VOCABULARY` *
10. `LEXICON_REF` *
11. `REF_LINK_SET` *
12. `EXTERNAL_REF` *

`HEADER` children: `MEDIA_DESCRIPTOR` *, `LINKED_FILE_DESCRIPTOR` *, `PROPERTY` * (in that order).

#### 3.1.2 Elements and attributes

Required attributes in **bold**.

| Element | Attributes | Content |
|---|---|---|
| `ANNOTATION_DOCUMENT` | **`DATE`** (xsd:dateTime), **`AUTHOR`**, **`VERSION`**, `FORMAT` (default "3.0") | children above |
| `LICENSE` | `LICENSE_URL` | text |
| `HEADER` | `MEDIA_FILE` (deprecated, keep as is), `TIME_UNITS` (`milliseconds` default, `NTSC-frames`, `PAL-frames`) | children |
| `MEDIA_DESCRIPTOR` | **`MEDIA_URL`**, `RELATIVE_MEDIA_URL`, **`MIME_TYPE`**, `TIME_ORIGIN` (long, ms), `EXTRACTED_FROM` | empty |
| `LINKED_FILE_DESCRIPTOR` | **`LINK_URL`**, `RELATIVE_LINK_URL`, **`MIME_TYPE`**, `TIME_ORIGIN`, `ASSOCIATED_WITH` | empty |
| `PROPERTY` | `NAME` | text |
| `TIME_ORDER` | – | `TIME_SLOT` * |
| `TIME_SLOT` | **`TIME_SLOT_ID`** (xsd:ID), `TIME_VALUE` (unsignedInt, ms) | empty |
| `TIER` | **`TIER_ID`**, `PARTICIPANT`, `ANNOTATOR`, **`LINGUISTIC_TYPE_REF`**, `DEFAULT_LOCALE`, `PARENT_REF`, `EXT_REF`, `LANG_REF` | `ANNOTATION` * |
| `ANNOTATION` | – | exactly one of `ALIGNABLE_ANNOTATION`, `REF_ANNOTATION` |
| `ALIGNABLE_ANNOTATION` | **`ANNOTATION_ID`**, `EXT_REF` (IDREFS), `LANG_REF`, `CVE_REF`, **`TIME_SLOT_REF1`**, **`TIME_SLOT_REF2`**, `SVG_REF` | `ANNOTATION_VALUE` (1) |
| `REF_ANNOTATION` | **`ANNOTATION_ID`**, `EXT_REF`, `LANG_REF`, `CVE_REF`, **`ANNOTATION_REF`**, `PREVIOUS_ANNOTATION` | `ANNOTATION_VALUE` (1) |
| `ANNOTATION_VALUE` | – | text (may be empty: `<ANNOTATION_VALUE></ANNOTATION_VALUE>`) |
| `LINGUISTIC_TYPE` | **`LINGUISTIC_TYPE_ID`**, `TIME_ALIGNABLE`, `CONSTRAINTS`, `GRAPHIC_REFERENCES`, `CONTROLLED_VOCABULARY_REF`, `EXT_REF`, `LEXICON_REF` | empty |
| `LOCALE` | **`LANGUAGE_CODE`**, `COUNTRY_CODE`, `VARIANT` | empty |
| `LANGUAGE` | **`LANG_ID`**, `LANG_DEF`, `LANG_LABEL` | empty |
| `CONSTRAINT` | **`STEREOTYPE`** (`Time_Subdivision`, `Symbolic_Subdivision`, `Symbolic_Association`, `Included_In`), `DESCRIPTION` | empty |
| `CONTROLLED_VOCABULARY` | **`CV_ID`**, `EXT_REF` | `DESCRIPTION` *, `CV_ENTRY_ML` * |
| `DESCRIPTION` (in CV) | **`LANG_REF`** | text |
| `CV_ENTRY_ML` | **`CVE_ID`**, `EXT_REF` | `CVE_VALUE` + |
| `CVE_VALUE` | **`LANG_REF`**, `DESCRIPTION` | text |
| `LEXICON_REF` | **`LEX_REF_ID`**, **`NAME`**, **`TYPE`**, **`URL`**, **`LEXICON_ID`**, **`LEXICON_NAME`**, `DATCAT_ID`, `DATCAT_NAME` | empty |
| `REF_LINK_SET` | **`LINK_SET_ID`**, `LINK_SET_NAME`, `EXT_REF`, `LANG_REF`, `CV_REF` | (`CROSS_REF_LINK` \| `GROUP_REF_LINK`) * |
| `CROSS_REF_LINK` | **`REF_LINK_ID`**, `REF_LINK_NAME`, `EXT_REF`, `LANG_REF`, `CVE_REF`, `REF_TYPE`, **`REF1`**, **`REF2`**, `DIRECTIONALITY` (`undirected`, `unidirectional`, `bidirectional`) | text |
| `GROUP_REF_LINK` | **`REF_LINK_ID`**, `REF_LINK_NAME`, `EXT_REF`, `LANG_REF`, `CVE_REF`, `REF_TYPE`, **`REFS`** (IDREFS) | text |
| `EXTERNAL_REF` | **`EXT_REF_ID`**, **`TYPE`** (`iso12620`, `ecv`, `cve_id`, `lexen_id`, `resource_url`), **`VALUE`** | empty |

Key constraints [XSD]: tier names unique among tiers; type names unique among types; CV IDs unique among CVs; `CVE_ID` unique within its CV; `TIME_SLOT_ID`, `ANNOTATION_ID`, `LANG_ID`, `EXT_REF_ID`, `REF_LINK_ID`, `LINK_SET_ID` are `xsd:ID`, i.e. **globally unique across the whole document** and must be valid XML NCNames. `PARENT_REF`, `LINGUISTIC_TYPE_REF`, `CONTROLLED_VOCABULARY_REF`, `LEXICON_REF` must resolve. `PREVIOUS_ANNOTATION` must point to a `REF_ANNOTATION`.

Version differences:

- **2.7** (2010): external CVs (`CV_RESOURCE` root for `.ecv`), `LEXICON_REF`, `EXTERNAL_REF` types `ecv`, `cve_id`, `lexen_id`. CVs are monolingual: `CONTROLLED_VOCABULARY/@DESCRIPTION`, `CV_ENTRY` (text value, `@DESCRIPTION`, `@EXT_REF`; `@CVE_ID` on external entries).
- **2.8** (2014): `LANGUAGE`, `LICENSE`; multilingual CVs (`CV_ENTRY_ML`, `CVE_VALUE`, CV `DESCRIPTION` elements), `LANG_REF` and `CVE_REF` on annotations, `LANG_REF` and `EXT_REF` on tiers. Not backward compatible for CVs.
- **3.0** (2016): `REF_LINK_SET` with `CROSS_REF_LINK` and `GROUP_REF_LINK`.

#### 3.1.3 ID generation and ordering rules (writer)

These rules aim at output that ELAN would produce, so a load–save cycle in elan-ng and one in ELAN give nearly identical files.

- **Annotation IDs:** keep existing IDs. New IDs are `a<n>` with `n = lastUsedAnnotationId + 1`, incremented per new annotation; `lastUsedAnnotationId` (header property) is updated on save. If the property is missing, compute it as the highest numeric suffix among `a<n>` IDs. Never reuse an ID within a session (undo of a deletion restores the original ID). If a loaded ID collides with another `xsd:ID` (e.g. a `LANG_ID` named `a5`), new IDs skip it.
- **Time slot IDs:** regenerated on every save as `ts1 … tsN` in time-order. ELAN-saved files always number their slots consecutively in TIME_ORDER (checked on the M1 corpus), and our writer reproduces an ELAN 3.0 file byte for byte this way.
- **Time order (`TIME_ORDER`):** slots are written in a total order consistent with:
  1. aligned values ascending;
  2. for unaligned slots, their position in the subdivision chain between the neighboring aligned slots;
  3. ties between aligned slots with equal values: keep the order from the input file; for new slots, order by (tier position in file, annotation begin).
  
  Algorithm: build a directed graph with edges `begin(a) → end(a)` for every alignable annotation and `slot_i → slot_j` for aligned values `v_i < v_j`; take a stable topological sort. Unaligned slots fall between their chain neighbors. (This is our own design; it does not come from ELAN's code.)
- **Tiers:** written in document order (creation order; new tiers appended). Annotations in a tier written in time order (by begin slot order; for reference annotations: parent order, then chain order).
- **Linguistic types, CVs, languages:** document order, new ones appended.
- **Constraints:** ELAN always writes the four `CONSTRAINT` elements with the exact descriptions in §2.1.4. Do the same.
- **Formatting:** 4-space indentation, one element per line, attributes in **alphabetical order** with `xmlns:xsi` and `xsi:*` after the plain attributes (this is what ELAN writes; confirmed on ELAN-saved files in M1), double quotes, `&amp; &lt; &gt; &quot;` escaped in attributes; newlines in `ANNOTATION_VALUE` written as is. An empty `ANNOTATION_VALUE` is written as `<ANNOTATION_VALUE></ANNOTATION_VALUE>`; other empty elements (e.g. a CV `DESCRIPTION`) self-close. Formatting differences are not "loss", but matching ELAN keeps diffs small for users who track EAF in git.
- **DATE:** current time in ISO 8601 with offset, e.g. `2026-11-02T13:45:12-05:00`.

#### 3.1.4 Minimal annotated example

```xml
<?xml version="1.0" encoding="UTF-8"?>
<ANNOTATION_DOCUMENT AUTHOR="" DATE="2026-11-02T13:45:12-05:00" FORMAT="3.0" VERSION="3.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:noNamespaceSchemaLocation="http://www.mpi.nl/tools/elan/EAFv3.0.xsd">
    <HEADER MEDIA_FILE="" TIME_UNITS="milliseconds">
        <!-- the media file; RELATIVE_MEDIA_URL is resolved against the .eaf's folder -->
        <MEDIA_DESCRIPTOR MEDIA_URL="file:///C:/data/story.wav" MIME_TYPE="audio/x-wav"
            RELATIVE_MEDIA_URL="./story.wav"/>
        <PROPERTY NAME="URN">urn:nl-mpi-tools-elan-eaf:3f1a6c2e-8b0d-4c35-9d0e-6a7b1c2d3e4f</PROPERTY>
        <PROPERTY NAME="lastUsedAnnotationId">5</PROPERTY>
    </HEADER>
    <TIME_ORDER>
        <TIME_SLOT TIME_SLOT_ID="ts1" TIME_VALUE="1000"/>
        <TIME_SLOT TIME_SLOT_ID="ts2"/>              <!-- unaligned: inner subdivision boundary -->
        <TIME_SLOT TIME_SLOT_ID="ts3" TIME_VALUE="2500"/>
    </TIME_ORDER>
    <!-- root tier: one utterance, 1000-2500 ms -->
    <TIER LINGUISTIC_TYPE_REF="utterance" PARTICIPANT="Speaker A" TIER_ID="tx@A">
        <ANNOTATION>
            <ALIGNABLE_ANNOTATION ANNOTATION_ID="a1" TIME_SLOT_REF1="ts1" TIME_SLOT_REF2="ts3">
                <ANNOTATION_VALUE>hello world</ANNOTATION_VALUE>
            </ALIGNABLE_ANNOTATION>
        </ANNOTATION>
    </TIER>
    <!-- Time Subdivision child tier: two words sharing ts1/ts3 with the parent, split at unaligned ts2 -->
    <TIER LINGUISTIC_TYPE_REF="words" PARENT_REF="tx@A" PARTICIPANT="Speaker A" TIER_ID="wd@A">
        <ANNOTATION>
            <ALIGNABLE_ANNOTATION ANNOTATION_ID="a2" TIME_SLOT_REF1="ts1" TIME_SLOT_REF2="ts2">
                <ANNOTATION_VALUE>hello</ANNOTATION_VALUE>
            </ALIGNABLE_ANNOTATION>
        </ANNOTATION>
        <ANNOTATION>
            <ALIGNABLE_ANNOTATION ANNOTATION_ID="a3" TIME_SLOT_REF1="ts2" TIME_SLOT_REF2="ts3">
                <ANNOTATION_VALUE>world</ANNOTATION_VALUE>
            </ALIGNABLE_ANNOTATION>
        </ANNOTATION>
    </TIER>
    <!-- Symbolic Association child of the words tier: one gloss per word -->
    <TIER LINGUISTIC_TYPE_REF="gloss" PARENT_REF="wd@A" PARTICIPANT="Speaker A" TIER_ID="gl@A">
        <ANNOTATION>
            <REF_ANNOTATION ANNOTATION_ID="a4" ANNOTATION_REF="a2">
                <ANNOTATION_VALUE>greeting</ANNOTATION_VALUE>
            </REF_ANNOTATION>
        </ANNOTATION>
        <ANNOTATION>
            <REF_ANNOTATION ANNOTATION_ID="a5" ANNOTATION_REF="a3" CVE_REF="cveid1">
                <ANNOTATION_VALUE>N</ANNOTATION_VALUE>
            </REF_ANNOTATION>
        </ANNOTATION>
    </TIER>
    <LINGUISTIC_TYPE GRAPHIC_REFERENCES="false" LINGUISTIC_TYPE_ID="utterance" TIME_ALIGNABLE="true"/>
    <LINGUISTIC_TYPE CONSTRAINTS="Time_Subdivision" GRAPHIC_REFERENCES="false"
        LINGUISTIC_TYPE_ID="words" TIME_ALIGNABLE="true"/>
    <LINGUISTIC_TYPE CONSTRAINTS="Symbolic_Association" CONTROLLED_VOCABULARY_REF="pos"
        GRAPHIC_REFERENCES="false" LINGUISTIC_TYPE_ID="gloss" TIME_ALIGNABLE="false"/>
    <LANGUAGE LANG_DEF="http://cdb.iso.org/lg/CDB-00138502-001" LANG_ID="eng" LANG_LABEL="English (eng)"/>
    <CONSTRAINT DESCRIPTION="Time subdivision of parent annotation's time interval, no time gaps allowed within this interval" STEREOTYPE="Time_Subdivision"/>
    <CONSTRAINT DESCRIPTION="Symbolic subdivision of a parent annotation. Annotations refering to the same parent are ordered" STEREOTYPE="Symbolic_Subdivision"/>
    <CONSTRAINT DESCRIPTION="1-1 association with a parent annotation" STEREOTYPE="Symbolic_Association"/>
    <CONSTRAINT DESCRIPTION="Time alignable annotations within the parent annotation's time interval, gaps are allowed" STEREOTYPE="Included_In"/>
    <CONTROLLED_VOCABULARY CV_ID="pos">
        <DESCRIPTION LANG_REF="eng">Parts of speech</DESCRIPTION>
        <CV_ENTRY_ML CVE_ID="cveid1">
            <CVE_VALUE DESCRIPTION="noun" LANG_REF="eng">N</CVE_VALUE>
        </CV_ENTRY_ML>
    </CONTROLLED_VOCABULARY>
</ANNOTATION_DOCUMENT>
```

(The XML comments are only there to explain the example. ELAN drops comments when it re-saves a file; our writer keeps them, see §3.2.)

Displayed times: `a1` 1000–2500, `a2` 1000–1750, `a3` 1750–2500 (`ts2` interpolated), `a4` = `a2`, `a5` = `a3`.

### 3.2 Round-trip strategy

Goal: **load → save without edits produces a file that is semantically identical** to the input (same elements, attributes and text after normalizing whitespace-only text, attribute order, and the fields we are allowed to regenerate: `DATE`, `lastUsedAnnotationId`, time slot IDs, schema location).

Approach:

1. **Typed model + raw residue.** The parser maps every known element and attribute into the typed model. Anything else is kept as raw lxml elements attached to the nearest known parent, with its position (index among siblings of known type) recorded:
   - unknown attributes on known elements → `extra_attrs: dict[str, str]` (order kept);
   - unknown child elements → `extra_children: list[(anchor, Element)]`;
   - XML comments and processing instructions → kept the same way;
   - unknown root-level elements → kept in place relative to their known neighbors.
2. **Writer** emits known content from the model in schema order and re-inserts the residue at the recorded positions. If the anchor element was deleted by an edit, residue moves to the end of the parent.
3. **Versions:** read 2.7/2.8/3.0; write 3.0. Converting 2.7 CVs to 2.8+ form is a semantic change ELAN makes too; the round-trip comparer knows about it.
4. **Things we never touch** unless the user edits them: `LICENSE`, `LOCALE`, `LEXICON_REF`, `EXTERNAL_REF`, `REF_LINK_SET`, `LINKED_FILE_DESCRIPTOR`, `SVG_REF`, `GRAPHIC_REFERENCES`, `MEDIA_FILE`, `EXTRACTED_FROM`.
5. **Invalid input:** files that violate the schema but that ELAN opens (e.g. dangling `CVE_REF`, out-of-order time slots, zero-length annotations, overlapping annotations on a root tier) open in a "repair report" mode: we load them as is, list the problems, and do not fix anything unless the user asks. Saving keeps the problems except where keeping them would make the output schema-invalid.
6. **Validation:** the writer validates its output against `EAFv3.0.xsd` in debug builds and tests (lxml `XMLSchema`).

### 3.3 `.pfsx` (per-document preferences)

ELAN's `.pfsx` is an XML file next to the `.eaf` (`name.pfsx`). Structure as observed in ELAN 5–7 files [VERIFY against real files collected for the corpus, §6.2]:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<preferences version="1.1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:noNamespaceSchemaLocation="http://www.mpi.nl/tools/elan/Prefs_v1.1.xsd">
    <prefList key="TierOrder">
        <String>tx@A</String>
        <String>wd@A</String>
    </prefList>
    <pref key="ActiveTierName"><String>tx@A</String></pref>
    <pref key="TimeScaleBeginTime"><Long>0</Long></pref>
    <pref key="TimeLineViewer.ZoomLevel"><Float>100.0</Float></pref>
    <prefGroup key="TierColors">
        <pref key="tx@A"><Object class="java.awt.Color">255,0,0</Object></pref>
    </prefGroup>
    <!-- ... -->
</preferences>
```

Value elements: `String`, `Boolean`, `Int`, `Long`, `Float`, `Double`, `Object` (with a `class` attribute; colors, fonts, rectangles serialized as text), nested `prefGroup` (map) and `prefList` (list). The schema is `Prefs_v1.1.xsd` [VERIFY URL and version].

Policy:

- Parse into a generic typed tree (key → value/list/group). Keep every key.
- elan-ng reads and writes the keys it uses (tier order, visible tiers, tier colors, active tier, selection, crosshair, zoom, viewer layout, sort mode, Transcription/Segmentation mode settings). Every other key is written back unchanged.
- Our own extra settings go under keys prefixed `elan-ng.` so ELAN ignores them.

### 3.4 `.ecv` (external controlled vocabulary)

An `.ecv` file is an XML file with root `CV_RESOURCE` [XSD]: optional `DATE`, `AUTHOR`, `VERSION` attributes; children `LANGUAGE` *, `CONTROLLED_VOCABULARY` + (same type as inside EAF), `EXTERNAL_REF` *.

- The EAF refers to it with `EXTERNAL_REF TYPE="ecv" VALUE="<url>"` and `CONTROLLED_VOCABULARY EXT_REF="<ext ref id>"`.
- An EAF may also carry a cached copy of the entries [VERIFY]. When the `.ecv` cannot be loaded (offline), use the cached copy and show a status message.
- External CVs are read-only inside a document (edit them with the CV editor in P2).

---

## 4. Architecture and technology choice

### 4.1 Requirements that drive the choice

| Criterion | Why it matters |
|---|---|
| C1. Cross-platform media, incl. frame-accurate video | Sign-language and gesture users step through video frame by frame and annotate at frame precision. Must decode the same formats on all three OSes. |
| C2. Waveform/spectrogram performance on hour-long audio | A 2-hour 48 kHz stereo WAV = 691 M samples. Zooming and scrolling must stay at 60 fps. |
| C3. Packaging/installers on all three OSes | Signed `.msi`/`.exe`, notarized `.dmg` (universal or two builds), AppImage/`.deb`/Flatpak. |
| C4. Accessibility | Screen reader support for tables, dialogs and menus; keyboard-only operation. |
| C5. Keyboard-heavy UI | Dozens of global shortcuts with modifiers, inline editing, input methods for IPA and non-Latin scripts. |
| C6. Long-term maintenance | Small team, academic setting; readable code; stable libraries; contributors from linguistics who often know Python. |
| C7. Testability of the core | The data model must be testable without a UI. |

### 4.2 Candidate stacks

Scores: ++ very good, + good, 0 neutral, − weak, −− poor.

| | A. Python + PySide6 (Qt 6) | B. Tauri 2 (Rust) + TypeScript UI | C. Electron + TypeScript | D. C++ (or Rust) + Qt 6 native |
|---|---|---|---|---|
| **C1 media** | + Qt Multimedia 6 uses an FFmpeg backend on all three OSes since Qt 6.5, so formats are identical everywhere. Frame-accurate stepping and exact seeking are not guaranteed by `QMediaPlayer`; we add a PyAV (FFmpeg) frame server for paused/stepped frames (exact). libmpv (via python-mpv) is an alternative backend with excellent frame stepping. | −− Uses the OS webview: WebView2 (Chromium) on Windows, WKWebView on macOS, WebKitGTK on Linux. Codec support differs per OS (WebKitGTK depends on GStreamer plugins; no H.264 on many distros by default). `<video>` cannot step frames exactly. Native media would mean a Rust FFmpeg pipeline that streams frames to the webview, which is a lot of custom work. | 0 Chromium is the same everywhere and ships H.264/AAC. Frame stepping is approximate (`requestVideoFrameCallback` helps but seeking to an exact frame is not guaranteed). Native FFmpeg via a Node addon is possible but adds a build matrix. | ++ Same as A (Qt Multimedia with FFmpeg, or libmpv), with direct access to FFmpeg's C API. |
| **C2 waveform** | + Peaks computed with numpy (vectorized) and cached; drawing from a min/max pyramid with `QPainter` paths is cheap (≈ 2 × width points per frame). Spectrogram with numpy FFT (P2) cached as tiles. Python is slow per-sample but we never draw per sample. | + Canvas/WebGL, peaks computed in Rust. Fast. wavesurfer.js does not scale to 2-hour files without precomputed peaks; custom canvas is needed anyway. | + Same as B but peaks in JS/WASM or a worker. | ++ Fastest. |
| **C3 packaging** | 0 PyInstaller or Briefcase produce app bundles; macOS notarization and Windows signing are well documented; app size ~150–250 MB with Qt + FFmpeg. Python packaging is the most fragile part of this stack, so we put it in CI from M0. | ++ Small installers (~10–20 MB), built-in bundler for all three. | + electron-builder is mature; ~150 MB. | 0 CMake + CPack/macdeployqt/windeployqt/linuxdeploy: mature but manual. |
| **C4 accessibility** | + Qt maps widgets to UIA (Windows), NSAccessibility (macOS) and AT-SPI (Linux). Custom-painted viewers need explicit `QAccessibleInterface` work. | + Web accessibility (ARIA) via the OS webview; decent on Windows/macOS, weaker on WebKitGTK. | + Chromium accessibility is good. | + Same as A. |
| **C5 keyboard UI** | ++ `QAction`/`QShortcut` with contexts, native menus on macOS, input methods (IME) handled by Qt. | + Possible, but global shortcuts vs. webview focus and IME in custom canvases need care. | + Same as B. | ++ Same as A. |
| **C6 maintenance** | ++ One language for core, UI and scripts. Python is the lingua franca of computational linguistics; contributors can read the core. Qt 6 has LTS releases. | 0 Two languages (Rust + TS) and a webview boundary. | + One language (TS), very large ecosystem, but fast-moving dependencies. | − C++ is the hardest for the expected contributors; Rust + Qt bindings (cxx-qt) are still young. |
| **C7 testable core** | ++ pytest + hypothesis for the core; pytest-qt for widgets. | + Core in Rust (cargo test), UI tests in Playwright. | + Vitest/Jest + Playwright. | + GoogleTest/Qt Test. |

### 4.3 Choice: **Python 3.12 + PySide6 (Qt 6 LTS) + FFmpeg (via Qt Multimedia and PyAV)**

Why:

1. **Media is the deciding factor.** Qt Multimedia's FFmpeg backend gives the same codecs and behavior on all OSes, and PyAV gives us exact, frame-accurate decoding where `QMediaPlayer` is not precise. The webview stacks (B, C) cannot step video frames exactly without a native pipeline that we would have to build ourselves.
2. **ELAN is a dense desktop app** (docked viewers, many dialogs, tables, native menus, dozens of shortcuts). Qt widgets fit that much better than a web UI and handle accessibility and IMEs natively.
3. **Maintainers and users.** The likely contributors are linguists and NLP people who know Python. The core library (`elan_ng.core`) is also directly useful as a scripting API for corpus work (like `pympi`, but with the editing rules).
4. **Performance risk is manageable.** Everything heavy (decoding, peak computation, FFT) runs in FFmpeg or numpy; Python only orchestrates. Drawing uses precomputed pyramids. If profiling ever shows a hot path in Python, it can move to a small compiled extension without changing the architecture.

Fallback: if Qt Multimedia's playback proves unreliable on one OS (see §8.2), the media service has a second backend on **libmpv** (python-mpv). The media service interface (§4.4) hides which one is used.

**Dependencies (pinned in `uv.lock`; versions are chosen at M0 as the newest stable release at that time, and only upgraded deliberately):**

| Package | Use | License |
|---|---|---|
| PySide6-Essentials 6.8.x (Qt 6.8 LTS) | UI, multimedia playback, audio output. Pinned to 6.8 because newer wheels (6.12) need macOS 14.4+, and we promise macOS 12+ (found in M0). | LGPL-3.0 |
| lxml | EAF/pfsx/ecv parsing and writing, schema validation, keeping unknown XML | BSD |
| numpy | Peaks, energy, FFT | BSD |
| PyAV | Exact frame decoding, audio decoding for peaks (bundles FFmpeg) | BSD (PyAV); FFmpeg in wheels: LGPL [VERIFY build flags, §8.3] |
| (optional) python-mpv + libmpv | Fallback media backend | LGPL/GPL [VERIFY] |
| Dev: pytest, pytest-qt, hypothesis, ruff, mypy (strict for `core`), xmldiff (round-trip tests), PyInstaller | tests, lint, types, packaging | MIT/BSD/GPL-with-exception (PyInstaller bootloader exception allows any license) |

Tooling: **uv** for environments and locking; Python 3.12 (3.13 tested in CI).

### 4.4 Module layout

```
elan/
├── REIMPLEMENTATION.md
├── README.md
├── pyproject.toml / uv.lock
├── src/elan_ng/
│   ├── core/                 # UI-free. No Qt imports allowed (enforced by a test).
│   │   ├── model.py          # Document, Header, MediaDescriptor, TimeSlot, Tier, TierType,
│   │   │                     # Stereotype, AlignableAnnotation, RefAnnotation, CV, Language, ...
│   │   ├── timeorder.py      # slot ordering, unaligned interpolation, slot sharing
│   │   ├── constraints.py    # rules R*, M*, D*, S* → ChangeSet
│   │   ├── changes.py        # primitive ops + ChangeSet + inverse
│   │   ├── commands.py       # user-level commands (command pattern) built on constraints
│   │   ├── undo.py           # UndoStack (per document), grouping, limits
│   │   ├── validate.py       # invariants I1–I3, stereotype checks, schema-level checks
│   │   ├── ids.py            # annotation id allocation, lastUsedAnnotationId
│   │   ├── search.py         # substring/regex search over the model
│   │   └── events.py         # document change notifications (plain callbacks)
│   ├── io/
│   │   ├── eaf_reader.py     # 2.7–3.0 → model + residue
│   │   ├── eaf_writer.py     # model + residue → 3.0
│   │   ├── residue.py        # unknown-content keeping
│   │   ├── pfsx.py, ecv.py
│   │   ├── registry.py       # Importer/Exporter plugin registry
│   │   └── formats/          # textgrid.py, tabtext.py, srt_vtt.py, chat.py (P2), ...
│   ├── media/
│   │   ├── clock.py          # MediaClock (single source of truth for time)
│   │   ├── service.py        # MediaService interface: open, play, pause, seek, rate, volume, offsets
│   │   ├── qt_backend.py     # QMediaPlayer + QAudioOutput + QVideoSink
│   │   ├── mpv_backend.py    # optional fallback
│   │   ├── frames.py         # PyAV frame server: exact frame at time t, frame index ↔ time
│   │   └── peaks.py          # peak pyramid computation + on-disk cache
│   ├── ui/
│   │   ├── app.py, mainwindow.py, actions.py (all QActions + default shortcuts table)
│   │   ├── viewers/          # timeline.py, waveform.py, grid.py, text.py, subtitle.py,
│   │   │                     # interlinear.py, density.py, video.py, spectrogram.py
│   │   ├── modes/            # annotation.py, sync.py, transcription.py, segmentation.py, interlinear.py
│   │   ├── dialogs/          # tier, type, CV, find, preferences, linked files, import/export
│   │   └── inline_editor.py
│   └── settings.py           # global settings (TOML) + per-document pfsx state
└── tests/
    ├── core/  io/  media/  ui/
    └── corpus/               # sample .eaf files + LICENSES.md (§6.2)
```

Dependency rule: `ui → media, io, core`; `io → core`; `media → core` (only `clock` types); `core → nothing`. Enforced with an import-linter contract in CI.

**Peak cache:** for each audio stream, a pyramid of (min, max) pairs per channel at 256, 1024, 4096, 16384 … samples per bucket, stored as `.npy` files in the OS cache directory keyed by (absolute path, size, mtime, stream index). Computed in a background thread with progress; the waveform shows the coarse levels first. A 2-hour file is decoded once (≈ 10–30 s in a background thread) and opens instantly afterwards.

### 4.5 One media clock drives everything

```
                 ┌──────────────────────────────────────────┐
user keys ─────► │ MediaClock                               │
(play, seek,     │  state: playing|paused, rate, time_ms    │
 step, rate)     │  source: master backend position         │
                 │  emits: tick(time_ms) at display refresh │
                 └───────┬───────────────┬──────────────────┘
                         │               │
          follows master │               │ tick(t) (≈60 Hz while playing,
          with offsets   ▼               ▼ once per seek while paused)
                 ┌──────────────┐   ┌──────────────────────────────────┐
                 │ MediaService │   │ Viewers: timeline, waveform,     │
                 │  master +    │   │ grid, subtitle, density, video   │
                 │  slave media │   │ (repaint crosshair, auto-scroll) │
                 └──────────────┘   └──────────────────────────────────┘
```

- **Master position is the truth.** While playing, the clock reads the master backend's position on each display frame (a `QTimer` synced to the screen refresh), smoothing jitter with linear extrapolation from the last reported position and the rate, but never drifting more than one video frame from the backend.
- **Slaves** (other media files) are positioned at `t + offset_i`. Every 500 ms the service compares each slave with its target; if the drift exceeds 40 ms [tunable], it re-seeks the slave (or adjusts its rate by ±2% for small drift, which sounds less abrupt). Video-only slaves are muted.
- **Paused / stepping:** seeks go through the frame server (PyAV) for video, so the shown frame is exactly the frame at `t`, and frame stepping moves by the actual next/previous frame timestamp (works with variable frame rate).
- **Viewers never talk to the media backends.** They subscribe to `tick` and to `selectionChanged`. Commands like "play selection" call the clock, which sets a stop time (and loop) and tells the service.
- **Document time vs. media time:** document time 0 = master media time minus master offset. All model times are document times.

---

## 5. UI specification

### 5.1 Main window per mode

Layout follows the manual's screenshots of the ELAN main window [M 1.5]. All splitters are draggable and their positions are saved in the `.pfsx`.

#### 5.1.1 Annotation mode (P0)

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ File  Edit  Annotation  Tier  Type  Search  View  Options  Window  Help          │ menu bar
├───────────────────────────────┬──────────────────────────────────────────────────┤
│                               │ [Grid][Text][Subtitles][Lexicon][Comments]       │
│                               │ [Recognizers][Metadata][Controls]                │ tab pane
│        VIDEO VIEWER(S)        │ ┌──────────────────────────────────────────────┐ │
│                               │ │ Tier: [tx@A          ▾]                      │ │
│                               │ │ Nr │ Annotation      │ Begin  │ End   │ Dur  │ │ (Grid viewer)
│                               │ │  1 │ hello world     │ 00:00… │ …     │ …    │ │
│                               │ └──────────────────────────────────────────────┘ │
├───────────────────────────────┴──────────────────────────────────────────────────┤
│ 00:00:01.250  Selection: 00:00:01.000 – 00:00:02.500  1500        [loop][sel]    │ time / selection
│ |◄ ◄◄ ◄| ◄ ► |► ►► ►|   ▷sel  ⟲around  rate 100%  vol 100%                       │ media controls
├──────────────────────────────────────────────────────────────────────────────────┤
│ ▁▂▅▇▅▂▁▁▂▃▆▇▆▃▂▁▁▁▂▅▇▅▂▁▁▂▃▆▇▆▃▂▁   (density overview, P1)                        │
├──────────────────────────────────────────────────────────────────────────────────┤
│        ▁▂▅█▇▅▂▁ ▁▂▃▆█▇▆▃▂▁          │                                            │ waveform
│        ▔▔▀▀▀▀▔▔ ▔▔▔▀▀▀▀▔▔▔          │ (red crosshair)                            │
├──────────┬───────────────────────────┼───────────────────────────────────────────┤
│          │ 00:00:01.000   00:00:02.000   00:00:03.000          (ruler)          │
│ tx@A   ● │ ┌hello world──────────────┐│                                           │ timeline viewer
│  wd@A    │ ┌hello──────┐┌world───────┐│                                          │ (indented labels
│   gl@A   │ ┊greeting   ┊┊N           ┊│                                          │  show hierarchy;
│ tx@B     │                     ┌yes──┼──────┐                                    │  ● = active tier)
│          │      ░░░░░░░░░░░░░░░░ selection band                                  │
├──────────┴──────────────────────────────────────────────────────────────────────┤
│ zoom: [100% ▾]  ◄═══════════════════════════════════════════════════════►        │ h-scroll
└──────────────────────────────────────────────────────────────────────────────────┘
```

Regions: (1) menu bar; (2) video area (one or more videos, left); (3) tab pane with viewers and Controls (right); (4) time display, selection display and media controls; (5) annotation density viewer (P1); (6) waveform viewer; (7) timeline viewer with tier labels, ruler, annotations, crosshair and selection; (8) horizontal scrollbar and zoom. The waveform and timeline can be switched to the interlinear viewer from a context menu [M 1.5] (P1). Without video, the video area collapses and the tab pane takes the full width.

Symbolic annotations (reference annotations) are drawn with dotted boundaries and the "symbolic annotation color" [M 1.3]. Unaligned boundaries are drawn dashed.

#### 5.1.2 Synchronization mode (P1)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ menu bar                                                                 │
├────────────────────┬────────────────────┬────────────────────────────────┤
│   VIDEO 1          │   VIDEO 2          │   VIDEO 3 / audio waveform     │
├────────────────────┴────────────────────┴────────────────────────────────┤
│ Player: (•) All  ( ) video1.mp4  ( ) video2.mp4  ( ) audio.wav           │
│ Offsets:  video1 0 ms   video2 1280 ms   audio 340 ms                     │
│ |◄ ◄◄ ◄| ◄ ► |► ►► ►|        [Apply current offsets]  [Reset]            │
├──────────────────────────────────────────────────────────────────────────┤
│ waveform of the selected player                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

#### 5.1.3 Transcription mode (P1)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ menu bar                                                                 │
├──────────────────────────────┬───────────────────────────────────────────┤
│ VIDEO                        │ [Settings…] [Configure…]  font [14]       │
│                              │ ☑ auto-play  ☐ loop  ☑ show tier names    │
├──────────────────────────────┴───────────────────────────────────────────┤
│ waveform + mini timeline of the current row                              │
├────┬──────────┬───────────────────────────┬──────────────────────────────┤
│ No │ Tier     │ po (transcription)        │ tl (translation)             │
├────┼──────────┼───────────────────────────┼──────────────────────────────┤
│  1 │ po@A     │ ka tomo na                │ he came here                 │
│  2 │ po@B     │ ▌ (editing)               │                              │
│  3 │ po@A     │ …                         │ …                            │
└────┴──────────┴───────────────────────────┴──────────────────────────────┘
```

Rows from different participants interleave by begin time; each row's background uses its tier color.

#### 5.1.4 Segmentation mode (P1)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ menu bar                                                                 │
├──────────────────────────────┬───────────────────────────────────────────┤
│ VIDEO                        │ Segmentation settings                     │
│                              │ (•) two keystrokes per annotation         │
│                              │ ( ) one keystroke per annotation          │
│                              │ ( ) one keystroke, fixed duration [1000]ms│
│                              │     (•) marks begin  ( ) marks end        │
│                              │ delay [0] ms                              │
├──────────────────────────────┴───────────────────────────────────────────┤
│ media controls                                                           │
├──────────────────────────────────────────────────────────────────────────┤
│ waveform                                                                 │
├──────────┬───────────────────────────────────────────────────────────────┤
│▶ gesture │ ┌──────┐   ┌────┐  ┌──  (open segment, begin marked)          │ editable tier on top
│──────────┼───────────────────────────────────────────────────────────────┤
│ tx@A     │ (read-only)                                                    │
│ ● marker │                                                                │ red marker = position
└──────────┴───────────────────────────────────────────────────────────────┘
```

#### 5.1.5 Interlinearization mode (P2)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ menu bar                                                                 │
├──────────────────────────────────────────────┬───────────────────────────┤
│ #1  00:01.000–00:02.500  tx@A                │ Lexicon: [my-lexicon ▾]   │
│   tx  hello world                            │ entry: world              │
│   wd  hello        │ world                   │  gloss: N; 'earth'        │
│   gl  greeting     │ N                       │                           │
│ #2  …                                        │ [Parse] [Gloss] [Apply]   │
└──────────────────────────────────────────────┴───────────────────────────┘
```

### 5.2 Menus

Phase column: **M3**, **M4**, **M5** = the milestone that delivers the item (all part of the MVP), **v1** = P1 milestones M6–M8, **P2** later, **–** not planned. Menu names follow ELAN 6.3/7.x [M 1.2, 1.5, 2, 3, 4]; [VERIFY] exact order against ELAN 7.1.

```
File
  New…                                         M4
  Open…                                        M4
  Open Recent ▸                                M4
  Close                                        M4
  Save / Save As… / Save as Template…          M4 / M4 / v1
  Save Selection as EAF…                       P2
  Merge Transcriptions…                        P2
  Properties… (author, license, URN)           v1
  Multiple File Processing ▸                   P2
  Export Multiple Files As ▸                   P2
  Import ▸  Praat TextGrid, CSV/Tab-delimited, Subtitles (SRT/WebVTT)       v1
            CHAT, Toolbox, FLEx, Transcriber                                 P2
  Export As ▸  Tab-delimited Text, Traditional Transcript, Interlinear Text,
               Praat TextGrid, Subtitles Text (SRT/WebVTT)                   v1
               CHAT, Toolbox, FLEx, HTML, SMIL, Image…                       P2 / –
  Page Setup / Print Preview / Print           –
  Exit                                         M4

Edit
  Undo / Redo                                  M4
  Copy Annotation / Copy Annotation Group      M4 / v1
  Duplicate Annotation                         v1
  Paste Annotation / Group / Here / Group Here v1
  Copy Current Time                            v1
  Edit Linked Files…                           M4
  Preferences ▸ Edit Preferences…              M4 (basic) / v1 (full)
                Shortcuts…                     v1
                Import / Export Preferences…   v1

Annotation
  New Annotation Here                          M4
  New Annotation Before / After                M4
  New Annotation from Begin–End Time…          v1
  Modify Annotation                            M4
  Modify Annotation Time…                      v1
  Remove Annotation Value                      M4
  Delete Annotation                            M4
  Split / Merge with Next / Merge with Previous v1
  Shift Annotation(s) ▸                        v1
  Delete Annotations in Selection              v1
  Create Annotations from Overlaps / Gaps / Subtraction       P2
  Label and Number Annotations…                P2

Tier
  Add New Tier…                                M4
  Change Tier Attributes…                      M4
  Delete Tier…                                 M4
  Add Participant / Import Tiers…              v1
  Change Parent of Tier…                       v1
  Copy Tier… / Merge Tiers… / Tokenize Tier…   v1
  Annotations from Overlaps…                   P2

Type
  Add New Tier Type…                           M4
  Change Tier Type…                            M4
  Delete Tier Type…                            M4
  Import Tier Types…                           v1
  Edit Controlled Vocabularies…                M4 (inline) / v1 (external)
  Edit Languages…                              v1
  Edit Lexicon Service Links…                  P2

Search
  Find…                                        M4 (substring) / v1 (regex)
  Find and Replace…                            v1
  Go To…                                       M4
  Search Multiple EAF… / Structured Search… / Find and Replace in Multiple Files  P2

View
  Media Player / Waveform / Timeline / Interlinear / Grid / Text / Subtitles / Density   M4–v1
  Spectrogram                                  P2
  Lexicon / Comments / Recognizers / Metadata  P2 / P2 / P2 / –
  Font size ▸, Zoom ▸                          M4

Options
  Annotation Mode / Synchronization Mode / Transcription Mode / Segmentation Mode    M4 / v1 / v1 / v1
  Interlinearization Mode                      P2
  Time Propagation Mode ▸ Normal / Bulldozer / Shift      M5 (Normal) / v1 (others)
  Selection Mode / Loop Mode                   M4
  Frame Length ▸ / Playback Rate ▸ / Volume ▸  M4
  Media Player ▸ (backend choice)              v1
  Language ▸ (UI language)                     P2

Window
  (list of open documents) / Previous / Next   M4

Help
  Contents (opens our manual)                  v1
  Shortcuts                                    M4
  About / Check for Updates                    M4 / –
```

### 5.3 Dialogs (P0 ones)

- **Add/Change tier:** name, parent (combo with "none"), tier type (filtered by parent compatibility), participant, annotator, language, default locale (hidden by default), color/font (stored in `.pfsx`). Validation messages appear inline; OK is disabled while invalid.
- **Add/Change tier type:** name, stereotype (None + four), CV (combo), data category (P2), lexicon link (P2), "use for Transcription mode" checks [VERIFY] (P1).
- **CV editor:** list of CVs; per CV: ID, description per language, entries table (value per language, description, shortcut key, color); add/remove/move; import from `.ecv` (P1).
- **Find:** query, tier multi-select, flags; result table; double-click → go to annotation.
- **Linked files:** list of media descriptors with up/down, add/remove, offsets column (read-only outside Sync mode), "Locate" for missing ones.

### 5.4 Intentional improvements over ELAN's UI

Each item stays out of the way of existing habits: same places, same shortcuts, same terms.

| Change | Why | Why it doesn't break muscle memory |
|---|---|---|
| HiDPI rendering everywhere (crisp waveform, text) | Modern screens | Visual only. |
| Dark mode following the OS (with an override) | Common request, long sessions | Colors only; tier colors keep their hue with adjusted contrast. |
| Native file dialogs | Consistent with the OS | Same entries in the same menus. |
| Waveform for any audio, not only WAV | ELAN users have to convert to WAV today | No new action; it just works. |
| One consistent media backend on all OSes (no "Media Player" choice needed) | Fewer "it plays on Mac but not on Windows" problems | The Options > Media Player menu still exists for the fallback backend. |
| Background peak computation with progress, instant reopen | Hour-long files | Nothing to learn. |
| Command palette (Ctrl+Shift+P on Win/Linux, Cmd+Shift+P on macOS) listing all actions with their shortcuts | Discoverability of ELAN's many actions | Additive; on Win/Linux ELAN uses Ctrl+Shift+P for Page Setup, which we don't implement (printing is Won't), so there is no conflict in practice. [Decision for reviewer: keep or drop.] |
| Undo stack visible in Edit > Undo History (P1) | Clarity for multi-step edits | Ctrl+Z/Y unchanged. |
| Inline validation in dialogs instead of modal error popups | Fewer modal interruptions | Same fields and buttons. |
| Explicit "repair report" for problematic files | ELAN sometimes silently changes or refuses files | Only appears when a file has problems. |

Not changed on purpose: menu names and order, mode names, terminology ("tier type" in the UI, "linguistic type" only in the file format), default shortcuts, inline edit behavior, colors of crosshair (red) and selection (light blue).

---

## 6. Testing and verification

### 6.1 Unit tests (core)

- **Model:** construction, ID allocation, slot sharing, time interpolation of unaligned slots, derived parents, derived reference annotation times.
- **Constraint engine:** at least one test per rule ID in §2.2 (R1–R15, M1–M11, D1–D7, S1–S7), for every stereotype and each propagation mode where it applies. Test names include the rule ID; a CI script checks that every rule ID in this document has a test (`tests/core/test_rule_coverage.py` greps this file).
- **Property-based tests** (hypothesis): random sequences of commands on random tier trees; after each command, all invariants hold; `undo` returns the exact previous state (structural equality); `redo` returns the exact next state; save → load gives an equal model.
- **Undo/redo:** grouping, limits, IDs never reused, cross-checked with the change-set inverse.
- **Import-linter contract:** `elan_ng.core` imports nothing from Qt, PyAV, or `elan_ng.ui`.

### 6.2 Round-trip tests against real `.eaf` files

Corpus in `tests/corpus/`, each file with its source and license in `tests/corpus/LICENSES.md`. Only files whose license allows redistribution are committed (`tests/data/`). Others go in an opt-in, git-ignored external corpus (`tests/corpus/external/`), downloaded by `tests/corpus/fetch.py`, which pins each file's URL and SHA-256; `LICENSES.md` records its provenance and terms (decided, §8.4 #5). Required PR CI runs only on the committed fixtures: tests that need an external file skip when it is missing. A separate, non-required CI job downloads the external corpus and runs the full suite.

Candidate sources (to confirm license per file before adding):
- Sample files shipped with ELAN (the ELAN installer contains example `.eaf` files) — check the license that applies to the samples, since ELAN itself is GPL-3.0.
- `pympi-ling` test files (MIT).
- `speach`/`poio` and other open-source EAF tools' test fixtures (check each license).
- Public archives with CC-licensed EAF: e.g. selected PARADISEC, ELAR, TLA open-access bundles; DoBeS samples; CC-licensed sign-language corpora excerpts (Corpus NGT is CC BY-NC-SA — check compatibility for a test fixture).
- Hand-made files covering edge cases: every stereotype, unaligned slots, nested subdivisions 4 levels deep, multilingual CVs, external CV, 2.7 and 2.8 files, ref links, unknown elements and attributes, comments, empty values, multi-line values, non-BMP characters (emoji, rare scripts), RTL text, very long values, 5,000+ annotations, files with problems that ELAN still opens.
- Files **saved by ELAN 7.1** from each hand-made file (to compare our writer's output with ELAN's own output for the same model).

Checks per file:
1. **Load succeeds** (or produces the expected repair report).
2. **Semantic equality:** `save(load(f))` vs `f` compared with a canonicalizer: parse both, normalize attribute order and whitespace-only text, map time-slot IDs by (value, order) instead of by name, ignore `DATE` and `lastUsedAnnotationId`, then compare trees with xmldiff. Must be empty.
3. **Schema validity** of the output against `EAFv3.0.xsd`.
4. **Idempotency:** `save(load(save(load(f))))` is byte-identical to `save(load(f))`.
5. **ELAN acceptance** (manual at first, automated later): open the output in ELAN 7.1 and re-save from ELAN; the ELAN-saved file must be semantically equal to ours. Automating this needs ELAN in CI (headless Java app); we start with a manual checklist per milestone and try to script ELAN's batch features in M2 [VERIFY whether ELAN has a headless/CLI save].

### 6.3 Golden tests for import/export

For each format: a set of input files and the expected output, checked in. Export: `model → format` must equal the golden file byte for byte (normalized line endings). Import: `format → model → EAF` must equal a golden EAF semantically. Where possible, golden files are produced by ELAN 7.1 from the same EAF (so we test against ELAN's real behavior, e.g. its tab-delimited columns and TextGrid tier handling). Round trips (EAF → TextGrid → EAF) are checked for the information the format can carry.

### 6.4 UI and media tests

- **pytest-qt** tests for viewers and modes using a test document and a synthetic media file (a generated WAV with tones at known times; an MP4 with a frame counter burned into each frame, generated with FFmpeg in a fixture). Examples: frame step shows the expected frame number (read from pixels); crosshair at time t after play-pause; creating an annotation via keyboard only; undo after each.
- **Smoke tests** on all three OSes in CI (GitHub Actions matrix `windows-latest`, `macos-latest` (Apple Silicon), `macos-13` (Intel), `ubuntu-latest`), with Qt's `offscreen` platform on Linux and real window servers on Windows/macOS runners: start the app, open a document with media, play 1 s, create/edit/delete an annotation, save, quit. Plus packaging: build the installer and launch the packaged app with `--self-test`.
- **Manual test script** per milestone (in `elan/tests/manual/`): steps with screenshots next to the corresponding ELAN manual screenshot.

### 6.5 Performance targets

Measured on a 2020-era mid-range laptop (4-core, 16 GB, SSD), recorded in CI as trend data (not hard failures, except where noted):

| Scenario | Target |
|---|---|
| Open a 5,000-annotation, 30-tier EAF (no media) | < 1.0 s (hard CI limit 3 s) |
| Open a 50,000-annotation EAF | < 5 s |
| Save a 5,000-annotation EAF | < 0.5 s |
| First open of a 2-hour 48 kHz stereo WAV: UI usable | < 1 s (waveform fills in progressively) |
| Peak computation for that WAV | < 30 s in background |
| Reopen with cached peaks | < 1 s to full waveform |
| Scroll/zoom timeline + waveform at 1080p with 30 visible tiers | 60 fps (≤ 16 ms per frame), 30 fps minimum on integrated GPUs |
| Crosshair update during playback | every display frame, ≤ 1 frame lag |
| Frame step on 1080p H.264 | < 100 ms per step |
| Any single edit command incl. propagation on 5,000 annotations | < 50 ms |
| Memory with a 2-hour video + 5,000 annotations | < 1 GB |

---

## 7. Roadmap

Each milestone = one branch and one PR, with a progress report (what works, how to run it, test results, screenshots next to the manual's screenshots, what's next). The EAF round-trip suite must stay green from M1 on.

| Milestone | Scope | Acceptance criteria |
|---|---|---|
| **M0 Skeleton** | `elan/` scaffold, `pyproject.toml`, `uv.lock`, ruff, mypy, pytest, import-linter, an empty Qt window, CI on Windows/macOS (Intel + ARM)/Linux, a packaging job that builds a launchable app on each OS, README with build/run instructions per OS. | CI green on all OSes; `uv run elan-ng` opens an empty main window with the menu bar from §5.2 (items disabled); packaged artifact launches with `--self-test`. |
| **M1 EAF core** | Data model, EAF reader/writer (2.7–3.0), residue keeping, ID rules, `.pfsx` and `.ecv` reading, validation, round-trip test corpus. No UI. | All corpus files pass checks 1–4 in §6.2; at least 30 corpus files including every edge case listed; ELAN 7.1 opens all our outputs without warnings (manual check, documented). |
| **M2 Constraint engine + undo** | Rules R1–R15, M1–M11, D1–D7, S1–S4 for all stereotypes in Normal mode; Bulldozer and Shift modes; change sets; undo stack; property-based tests. Every [VERIFY] affecting these rules is resolved against ELAN 7.1 and this document updated. | One passing test per rule ID; hypothesis suite (≥ 10,000 generated cases in CI nightly) green; behavior of each rule matches ELAN 7.1 for a scripted set of 40 scenarios (documented with before/after screenshots from ELAN). |
| **M3 Media + waveform + timeline** | Media service (Qt backend), frame server, media clock, peak cache, waveform viewer, timeline viewer (read-only), ruler, zoom, scrolling, crosshair, selection, play/pause/step/rate/volume/loop, selection playback, keyboard shortcuts for media. | Opens a 2-hour WAV and a 1080p MP4 with the performance targets in §6.5; frame stepping matches the burned-in frame counter; audio/video stay in sync within 1 frame for 10 minutes; all media shortcuts from §2.9 work on all three OSes. |
| **M4 Annotation mode MVP** | Inline editor, create/modify/delete/clear, before/after, active tier/annotation navigation, grid viewer, tier and type dialogs, inline CV editing, linked files dialog, find (substring), save/save as/open/new/recent, preferences (basic), undo/redo in the UI, missing-media dialog. | A user can do the "first annotation" workflow from the manual [M 2.9] entirely with ELAN's default keys; edits obey §2.2; files saved by elan-ng open in ELAN 7.1 and vice versa; UI smoke tests green on all OSes. |
| **M5 MVP polish** | Retime by dragging, propagation mode menu, `.pfsx` writing for tier order/colors/visibility, video window, backups, crash-safe save (write to temp + atomic rename), first user test with 2–3 ELAN users. | Users can complete a 30-minute real annotation task without ELAN; issues triaged. **MVP release (0.1).** |
| **M6** | Transcription mode, Segmentation mode, interlinear viewer, text and subtitle viewers, density viewer. | Each mode's workflow from the manual runs keyboard-only; golden tests for mode-specific edits. |
| **M7** | Import/export: TextGrid, tab-delimited, SRT/WebVTT, traditional transcript, interlinear text; regex search and replace; templates (`.etf`). | Golden tests against ELAN 7.1 exports pass. |
| **M8** | Synchronization mode and multiple videos; external CVs; tier tools (reparent, copy, merge, tokenize); split/merge annotations; full preferences dialog and shortcut editor. **v1.0** | All P1 items done; accessibility check with NVDA (Windows), VoiceOver (macOS), Orca (Linux) on main flows. |
| **M9+ (P2)** | Spectrogram, recognizers (silence), multi-file and structured search, Interlinearization mode with lexicon, CHAT/Toolbox/FLEx/Transcriber, spell checking, comments, plugin API. | Per feature. |

---

## 8. Open questions and risks

### 8.1 Behaviors to verify against ELAN 7.1 (before the matching code is written)

The manual documents ELAN 6.3. Each item below is tagged [VERIFY] in the text above. Plan: install ELAN 7.1 on one machine in M1, run each scenario, record the result (screenshots + resulting `.eaf`) in `elan/docs/verification/`, and update this document.

1. **Overlap handling on root tiers in Normal mode (R3, M6):** does ELAN trim/delete overlapped neighbors, refuse the edit, or stop the drag at the neighbor? What happens when the new annotation lies strictly inside an existing one?
2. **Bulldozer and Shift modes (R4, R5, M6):** exact scope (same tier, tier tree, or all tiers) and the amount shifted.
3. **Time Subdivision details:** value placement on split (R8); which neighbor absorbs space on delete (D3); clamping of inner aligned slots on parent shrink (M3); even interpolation of unaligned slots.
4. **R13 auto-create dependent annotations** for Included In tiers.
5. **Merge/split rules (S1, S2):** value joining, children handling.
6. **Shortcut discrepancies in the manual:** "New annotation here" is Alt+N in [M 2.9] but Ctrl+Alt+N in [M 6.2.3]; "New annotation before" and "after" are both listed as Ctrl+Shift+N; "Show empty slots" is listed as Ctrl+Alt+Shift with no key; macOS mappings; the drag modifier for retiming. We follow the program.
7. **Transcription mode keys and options** (not on the manual pages I could reach).
8. **ID behavior on save:** ELAN-saved files have consecutive slot ids in time order (consistent with renumbering, M1). Still to check in ELAN 7.1 that annotation ids are kept across saves.
9. ~~**Attribute order and formatting** of ELAN's EAF writer.~~ Resolved in M1: alphabetical, see §3.1.3.
10. **`.pfsx` key list and schema version**, and where ELAN 7.1 stores global preferences on each OS.
11. **External CV caching** inside the EAF, and how 2.7 monolingual CVs are converted. Partly resolved in M1: the ELAN-saved sample files keep **no** cached entries for external CVs (just `CV_ID` and `EXT_REF`), and ELAN's 3.0 files use `LANGUAGE LANG_ID="und"` with `LANG_DEF="http://cdb.iso.org/lg/CDB-00130975-001"` and label `undetermined (und)`, which our 2.7 conversion now uses. Still to check: the `CVE_ID` format ELAN generates for converted entries (we use `cveid_<uuid>`).
12. **Zoom level list**, ms-per-pixel at 100%, auto-scroll behavior during playback, selection mode semantics.
13. **Zero-length annotations:** forbidden on creation, but can they occur in files ELAN writes (e.g. after imports)?
14. **Master media choice** and maximum number of videos in 7.1.
15. **Window navigation keys** Shift+Up/Down conflict with text selection in fields: does ELAN only use them outside text fields?

### 8.2 Technical risks

| Risk | Impact | Mitigation |
|---|---|---|
| Qt Multimedia FFmpeg backend has platform bugs (seeking accuracy, rate changes with pitch, audio device switching) | Broken playback on one OS | Frame server (PyAV) for paused frames; libmpv fallback backend behind the same interface; media test suite with synthetic files on all OSes in CI from M3. |
| Audio/video sync across several files | Drift during long playback | Master-clock design with periodic correction (§4.5); 10-minute sync test in M3. |
| Codec licensing and patents (H.264/HEVC/AAC) | Distribution issues in some jurisdictions | Use FFmpeg builds that rely on LGPL components and OS-provided decoders where possible; document; never bundle GPL-only codecs (x264 is an encoder anyway, not needed). [VERIFY the exact configuration of Qt's and PyAV's bundled FFmpeg.] |
| Python performance on very large documents (50k+ annotations) | Slow timeline painting | Interval index per tier (sorted arrays + bisect); paint only visible annotations; profile in M3/M4; compiled extension as a last resort. |
| Packaging Python + Qt + FFmpeg (code signing, notarization, Linux variety) | Install failures | Packaging job in CI from M0; AppImage + Flatpak for Linux; universal or separate macOS builds tested on both architectures. |
| Undocumented ELAN behaviors (the [VERIFY] list) | Users notice differences | Verification phase in M1/M2; every resolved item becomes a test. |
| Users' files with unusual content | Data loss (critical) | Residue keeping; never write invalid XML; atomic saves + backups; round-trip corpus grows with every bug report. |
| Accessibility of custom-painted viewers | Screen reader users can't use timeline | Grid/Transcription views are standard tables (accessible); timeline exposes an accessible list of visible annotations; tested in M8. |

### 8.3 Licensing and naming

- **ELAN is GPL-3.0.** We do not copy or translate ELAN code. This document is based on the manual, the XSD, the format documentation and observed behavior, which carry no such constraint. If we ever need to translate a specific algorithm from ELAN's source, we will (a) stop and ask before doing it, (b) record which part and why in §2.2.6, and (c) get a licensing review from the repository owner first, since that would conflict with the MIT license below. Currently **no part of the design is taken from ELAN's source.**
- **Repository license: MIT** for original LangTools code (decided by the repository owner, see §8.4). The text is in `LICENSE` at the repository root. Third-party dependencies, schemas, fixtures and assets keep their own licenses and notices. Our dependencies (LGPL Qt, BSD/MIT others, LGPL FFmpeg) are compatible with MIT for the elan-ng code, provided we keep Qt and FFmpeg dynamically linked (they are, as shared libraries in the bundle) and ship their license texts.
- **EAF schema file:** `EAFv3.0.xsd` is MPI's and is not committed. `tests/corpus/fetch.py` downloads it, pinned by SHA-256, into the external corpus.
- **Test corpus:** only redistributable files are committed. Others live in the opt-in external corpus (§6.2). Both are listed with sources and licenses in `tests/corpus/LICENSES.md`.
- **Name:** "ELAN" is MPI's name. "elan-ng" is a working name; a public release should use a distinct name and say "compatible with ELAN" rather than imply it is an official ELAN version.

### 8.4 Decisions requested from the reviewer

1. Approve the stack: **Python 3.12 + PySide6 + FFmpeg (Qt Multimedia + PyAV)**, with libmpv as fallback. **Decided: approved**, with dependency licensing and cross-platform distribution details documented (§4.3, §8.3).
2. Approve the MVP scope: milestones M0–M5 (Annotation mode only, Normal propagation mode first, no import/export besides EAF). **Decided: approved** as proposed.
3. Repository license (see §8.3). **Decided: MIT** for original LangTools code. Third-party dependencies, schemas, fixtures and assets keep their own licenses and notices. Any future translation of GPL ELAN source needs a licensing review first.
4. Whether to keep the command palette (§5.4). **Decided: keep it** as an additive M4/M5 discoverability feature built from the shared command registry, not as an early compatibility gate.
5. Whether the test corpus may include files that cannot be committed. **Decided: yes, but only** in an opt-in, git-ignored external corpus with recorded provenance, terms and checksums. Required PR CI must run fully from redistributable committed fixtures (§6.2).

All five were decided by the repository owner in GitHub Discussion #13 (ELAN: agent roll call and work claims): decisions 3–5 first, then 1–2 on 2026-11-12 (<https://github.com/mhulden/langtools/discussions/13#discussioncomment-19572458>). These record design decisions only; they do not approve any pull request.
