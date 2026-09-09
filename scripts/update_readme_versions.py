#!/usr/bin/env python3
"""Regenerate the docs-versions table in README.md from docs/<app>/_meta.json.

Run by the weekly update-docs workflow after a scrape, so the README never
drifts from the committed docs. Safe to run locally: python3 scripts/update_readme_versions.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
DOCS = ROOT / "docs"

START = "<!-- docs-versions:start -->"
END = "<!-- docs-versions:end -->"

DISPLAY_NAMES = {
    "network": "Network",
    "protect": "Protect",
    "site-manager": "Site Manager",
    "innerspace": "InnerSpace",
}


def build_table() -> str:
    rows = []
    for meta_file in sorted(DOCS.glob("*/_meta.json")):
        meta = json.loads(meta_file.read_text())
        app = meta.get("app") or meta_file.parent.name
        name = DISPLAY_NAMES.get(app, app)
        scraped = str(meta.get("scrapedAt", ""))[:10]
        rows.append(f"| {name} | v{meta.get('version', '?')} | {scraped} | {meta.get('pageCount', '?')} |")
    if not rows:
        sys.exit("No docs/*/_meta.json found — nothing to write.")
    header = ["| Application | API version | Scraped | Pages |", "|---|---|---|---|"]
    return "\n".join(header + rows)


def main() -> int:
    text = README.read_text()
    block = f"{START}\n{build_table()}\n{END}"
    new_text, n = re.subn(
        re.escape(START) + r".*?" + re.escape(END),
        lambda _: block,
        text,
        flags=re.DOTALL,
    )
    if n != 1:
        sys.exit(f"Expected exactly one {START}...{END} block in README.md, found {n}.")
    if new_text == text:
        print("README version table already up to date.")
        return 0
    README.write_text(new_text)
    print("README version table updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
