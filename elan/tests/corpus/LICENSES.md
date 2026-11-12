# Test corpus sources and licenses

## Committed files (`tests/data/`)

| File | Source | License |
|---|---|---|
| `minimal.eaf` | The example in REIMPLEMENTATION.md §3.1.4 | MIT (this repository) |
| `edge_cases.eaf` | Written for this project: every stereotype, nested subdivision with unaligned slots, multilingual CV, external CV, lexicon ref, ref links, licenses, unknown elements and attributes, comments, empty and multi-line values, non-BMP and RTL text | MIT (this repository) |
| `old_cv_2_7.eaf` | Written for this project in the EAF 2.7 form (monolingual CVs) | MIT (this repository) |
| `problems.eaf` | Written for this project: overlaps, a zero-length annotation, decreasing time order, an unused slot, two associations for one parent, a dangling reference, an unknown tier type | MIT (this repository) |
| `nested_subdivision_4.eaf` | Written for this project: a subdivision chain nested four levels deep (utterance, word, morph, syllable, phone), with unaligned time slots | MIT (this repository) |
| `format_2_8.eaf` | Written for this project in the EAF 2.8 form (multilingual controlled vocabularies, LANG_REF and CVE_REF on annotations) | MIT (this repository) |

## External corpus (`tests/corpus/external/`, opt-in, not committed)

Files that may not be redistributed live only in this git-ignored folder. Getting them is opt-in: run `uv run python tests/corpus/fetch.py` from `elan/`. Each entry in `fetch.py` pins the source URL and a SHA-256 checksum, and the table below records where each file comes from and its terms. Required PR CI does not download these files: tests that need them skip when they are missing. A separate, non-required CI job (`external-corpus` in `.github/workflows/elan.yml`) downloads them and runs the full suite.

| File | Source | License |
|---|---|---|
| `pympi_sample_2.7.eaf`, `pympi_sample_2.8.eaf`, `pympi_sample_3.0.eaf` | Test files of [pympi](https://github.com/dopefishh/pympi) (commit `e9eccc4`), saved by ELAN. 8,778 annotations on six tiers covering all four stereotypes, with 1,572 unaligned time slots. | The pympi repository is MIT-licensed. The files carry an MPI demo-material license (`<LICENSE LICENSE_URL="http://www.mpi.nl/license.txt">`), which is why they are downloaded instead of committed. |
| `EAFv3.0.xsd` | <https://www.mpi.nl/tools/elan/EAFv3.0.xsd> | MPI. Used only to validate our output. |

More real-world files (ELAN's own sample files, open archive material) are to be added as their licenses are checked (REIMPLEMENTATION.md §6.2).
