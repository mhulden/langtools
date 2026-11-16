# FFmpeg in the PyAV wheel: license check (C1, REIMPLEMENTATION.md §4.3, §8.3)

elan-ng decodes media with PyAV (`av`, BSD-3-Clause). The PyAV wheels on PyPI ship their own
FFmpeg as shared libraries. This note records what that FFmpeg build is, so the [VERIFY] about
"the exact configuration of Qt's and PyAV's bundled FFmpeg" in §8.3 has evidence behind it.

## What was checked

Pinned version: `av` 19.0.2 (see `uv.lock`), FFmpeg 9.0.2. Checked on the Windows wheel
(`cp312-abi3-win_amd64`) with:

```
uv run python -c "import av._core as c; m = c.library_meta['libavcodec']; print(m['license']); print(m['configuration'])"
```

Findings:

- FFmpeg reports its license as **LGPL version 3 or later**. The configure line has
  `--enable-version3` and `--enable-shared --disable-static`, and it has **no** `--enable-gpl`
  and **no** `--enable-nonfree`. Dynamic LGPL linking is compatible with our MIT code (§8.3).
- The same configure line has **`--enable-libx264` and `--enable-libx265`**, and the wheel's
  `av.libs/` folder contains `libx264-*.dll` and `libx265-*.dll`. x264 and x265 are GPL-2.0
  libraries. Upstream FFmpeg normally refuses those flags without `--enable-gpl`, so the wheel
  build differs from a stock build here. **Open question.** It is unclear how a GPL encoder can sit
  in a build labelled LGPL, and whether shipping the wheel as is puts GPL code into our
  installer.
- x264 and x265 are **encoders only**. elan-ng only decodes (H.264/HEVC decoding is FFmpeg's own
  LGPL code), and our test fixtures encode with FFmpeg's built-in `mpeg4` encoder, not libx264.
  So nothing we run needs them.

## macOS floor (owner decision, 2026-11-16)

Every PyAV release from 16.0 on has only a macOS 14+ wheel for Apple Silicon (15.x needs 13). The
last release with macOS 12 wheels for both architectures, 14.2.0, bundles FFmpeg 7.1 built with
`--enable-gpl` ("GPL version 3 or later"). So no PyPI wheel gives both macOS 12 on Apple
Silicon and an LGPL FFmpeg. mhulden chose **option B**:

- Development and CI use PyAV 19 from PyPI. On Apple Silicon that means macOS 14+ for
  development. Intel Macs work from macOS 12.
- The shipped app still supports macOS 12+ (§1) on both architectures. Before media goes into a
  distributed package, we build our own LGPL-only FFmpeg/PyAV with a macOS 12 deployment target
  (issue #28, with an artifact audit in CI).

## Consequences

1. Development and CI: no problem. We install the wheel and use only LGPL decoding.
2. Packaging (installers, M5): the PyPI wheel is never bundled. The package job uses the
   LGPL-only FFmpeg/PyAV build from issue #28 (no `libx264`/`libx265` or other GPL libraries) and
   ships the FFmpeg LGPL text and a source offer.
3. The macOS (`macosx_14_0_arm64`) and Linux (`manylinux_2_28_x86_64`) wheels of the same
   release also bundle `libx264` and `libx265` (checked by listing the wheel contents, not by
   importing them). Not yet checked: Qt Multimedia's own FFmpeg (C5), so the §8.3 [VERIFY]
   stays open for that one.
