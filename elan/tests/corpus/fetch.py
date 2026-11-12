"""Download the external test corpus into tests/corpus/external/ (git-ignored).

These files are not committed: their content belongs to others (see LICENSES.md), and
some are large. Each download is pinned by URL and SHA-256. Getting them is opt-in:
tests that need a file skip when it is missing. Required PR CI does not run this script;
only the non-required external-corpus job does (REIMPLEMENTATION.md §6.2).

Usage (from elan/): uv run python tests/corpus/fetch.py
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE / "external"
PYMPI = "https://raw.githubusercontent.com/dopefishh/pympi/e9eccc4ec37a142f1d0d643f74fa12d342a95c8f/test"

FILES = {
    "pympi_sample_2.7.eaf": (
        f"{PYMPI}/sample_2.7.eaf",
        "91c3af27ae1044ad0519824939f3ecb0f5ac8b54ee087d1e40a548ac23e53ffa",
    ),
    "pympi_sample_2.8.eaf": (
        f"{PYMPI}/sample_2.8.eaf",
        "6b57a949b461a2dcc455df3e1d83e26deaf576d0cf21237d261c944a040e5d69",
    ),
    "pympi_sample_3.0.eaf": (
        f"{PYMPI}/sample_3.0.eaf",
        "05a396cd3c80f14ed091159bb24c49c3ad7f4860eb5581b10b1d29566466375e",
    ),
    "EAFv3.0.xsd": (
        "https://www.mpi.nl/tools/elan/EAFv3.0.xsd",
        "59e76f90d5840813314b1e635480d044287b811ebd63a40e25cb4e73c6ad72bb",
    ),
}


def fetch(name: str, url: str, sha256: str) -> None:
    path = TARGET / name
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha256:
        print(f"ok        {name}")
        return
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise SystemExit(f"checksum mismatch for {name}: {digest}")
    path.write_bytes(data)
    print(f"fetched   {name}")


def main() -> int:
    TARGET.mkdir(exist_ok=True)
    for name, (url, sha256) in FILES.items():
        fetch(name, url, sha256)
    return 0


if __name__ == "__main__":
    sys.exit(main())
