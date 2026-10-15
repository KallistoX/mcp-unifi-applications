#!/usr/bin/env python3
"""Prepare a patch release when the only unreleased package change is scraped docs.

Run by release.yml, after update-docs has merged its PRs. Compares HEAD with the
last release tag and decides:

- no docs change since the tag: nothing to release (`release=false`);
- docs changed, and nothing else that ships in the package: bump the patch
  version in pyproject.toml and server.json, date a CHANGELOG section that names
  each application's old and new API version, regenerate the README table, and
  write the release notes (`release=true`, `version`, `tag`);
- anything else that ships changed too (server code, pyproject.toml): stop with
  exit 1. That release needs a person to pick the version and write the entry.

It edits the working tree only; committing, tagging and publishing are the
workflow's job. Decisions go to $GITHUB_OUTPUT when it is set.

    python3 scripts/release_docs.py --notes /tmp/notes.md
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_readme_versions  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS = "src/mcp_unifi_applications/docs/"


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def ships_in_package(path: str) -> bool:
    """Whether a changed path alters what `pip install` delivers, docs aside."""
    return path == "pyproject.toml" or (path.startswith("src/") and not path.startswith(DOCS))


def read_meta(root: Path, ref: str | None, app: str) -> dict | None:
    path = f"{DOCS}{app}/_meta.json"
    if ref is None:
        file = root / path
        return json.loads(file.read_text()) if file.exists() else None
    try:
        return json.loads(git(root, "show", f"{ref}:{path}"))
    except subprocess.CalledProcessError:
        return None


def describe_app(root: Path, tag: str, app: str) -> str:
    name = update_readme_versions.DISPLAY_NAMES.get(app, app)
    old, new = read_meta(root, tag, app), read_meta(root, None, app)
    if new is None:
        return f"- {name} API documentation removed."
    if old is None:
        return f"- {name} API documentation added at v{new['version']}."
    if old["version"] == new["version"]:
        return f"- {name} API documentation re-scraped at v{new['version']}."
    return f"- {name} API documentation updated from v{old['version']} to v{new['version']}."


def app_order(app: str) -> tuple[int, str]:
    order = list(update_readme_versions.DISPLAY_NAMES)
    return (order.index(app) if app in order else len(order), app)


def bump_patch(version: str) -> str:
    major, minor, patch = version.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def release_changelog(text: str, old: str, new: str, today: str, bullets: list[str]) -> tuple[str, str]:
    """Return the changelog with a dated section for `new`, and that section's body."""
    head, sep, rest = text.partition("## [Unreleased]\n")
    if not sep:
        raise ValueError("CHANGELOG.md has no '## [Unreleased]' heading")
    match = re.search(r"^## \[", rest, flags=re.MULTILINE)
    unreleased, older = (rest[: match.start()], rest[match.start():]) if match else (rest, "")
    unreleased = unreleased.strip()

    entries = "\n".join(bullets)
    if "### Changed\n" in unreleased:
        # Keep a Changelog wants one heading per kind; join an existing one.
        body = unreleased.replace("### Changed\n\n", f"### Changed\n\n{entries}\n", 1)
    else:
        body = f"### Changed\n\n{entries}" + (f"\n\n{unreleased}" if unreleased else "")

    link = re.compile(r"^\[Unreleased\]: (\S+)/compare/v" + re.escape(old) + r"\.\.\.HEAD$", re.MULTILINE)
    links = link.search(older)
    if not links:
        raise ValueError(f"CHANGELOG.md has no '[Unreleased]: .../compare/v{old}...HEAD' link")
    base = links.group(1)
    older = link.sub(
        lambda _: f"[Unreleased]: {base}/compare/v{new}...HEAD\n[{new}]: {base}/releases/tag/v{new}",
        older,
        count=1,
    )
    return f"{head}{sep}\n## [{new}] - {today}\n\n{body}\n\n{older}", body + "\n"


def set_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as fh:
            for key, value in values.items():
                fh.write(f"{key}={value}\n")


def main(argv: list[str] | None = None, root: Path = ROOT, today: str | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--notes", type=Path, required=True, help="where to write the release notes")
    args = parser.parse_args(argv)
    today = today or datetime.date.today().isoformat()

    tag = git(root, "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "HEAD")
    changed = git(root, "diff", "--name-only", tag, "HEAD").splitlines()
    docs = [p for p in changed if p.startswith(DOCS)]
    if not docs:
        print(f"No docs changes since {tag}: nothing to release.")
        set_output(release="false")
        return 0

    blocking = [p for p in changed if ships_in_package(p)]
    if blocking:
        print(f"::error::main carries unreleased package changes since {tag}; release by hand:")
        for path in blocking:
            print(f"  {path}")
        return 1

    pyproject = (root / "pyproject.toml").read_text()
    current = re.search(r'^version = "([^"]+)"$', pyproject, flags=re.MULTILINE).group(1)
    if f"v{current}" != tag:
        print(f"::error::pyproject.toml says {current} but the last tag is {tag}; fix the version by hand.")
        return 1
    new = bump_patch(current)

    apps = sorted({p[len(DOCS):].split("/", 1)[0] for p in docs}, key=app_order)
    bullets = [describe_app(root, tag, app) for app in apps]

    changelog, notes = release_changelog((root / "CHANGELOG.md").read_text(), current, new, today, bullets)

    (root / "pyproject.toml").write_text(
        pyproject.replace(f'\nversion = "{current}"\n', f'\nversion = "{new}"\n', 1)
    )
    server_path = root / "server.json"
    server_text = server_path.read_text()
    # Edit the text rather than re-serialise it, so the file keeps its formatting.
    server_text = server_text.replace(f'"version": "{current}"', f'"version": "{new}"')
    server = json.loads(server_text)
    versions = [server["version"], *(p["version"] for p in server.get("packages") or [])]
    if set(versions) != {new}:
        print(f"::error::server.json versions {versions} did not all move to {new}")
        return 1
    server_path.write_text(server_text)
    (root / "CHANGELOG.md").write_text(changelog)
    update_readme_versions.main(readme=root / "README.md", docs=root / DOCS)
    args.notes.write_text(notes)

    print(f"Releasing {new}:\n{notes}")
    set_output(release="true", version=new, tag=f"v{new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
