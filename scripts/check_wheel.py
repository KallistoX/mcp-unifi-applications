#!/usr/bin/env python3
"""Assert the built wheel actually ships the server and its docs.

Guards the failure this script was written for: without explicit setuptools
configuration, flat-layout auto-discovery once produced a wheel containing no
Python module at all (top_level.txt said "screenshots"), so `pip install .`
installed nothing and the console script could not import. Run in CI after
`python -m build --wheel`.
"""

import glob
import zipfile

MIN_DOC_FILES = 100


def main() -> int:
    wheels = sorted(glob.glob("dist/*.whl"))
    if not wheels:
        print("error: no wheel in dist/ — did `python -m build --wheel` run?")
        return 1
    names = zipfile.ZipFile(wheels[-1]).namelist()

    problems = []
    if not any(n.endswith("mcp_unifi_applications/server.py") for n in names):
        problems.append("server.py is missing from the wheel")
    docs = sum(1 for n in names if "/docs/" in n and n.endswith(".json"))
    if docs < MIN_DOC_FILES:
        problems.append(f"wheel ships only {docs} doc JSON files (expected at least {MIN_DOC_FILES})")

    if problems:
        for p in problems:
            print(f"error: {p}")
        return 1
    print(f"{wheels[-1]}: ships server.py and {docs} doc files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
