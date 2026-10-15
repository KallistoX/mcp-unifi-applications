"""Tests for scripts/release_docs.py, the docs-only automatic release.

Each test builds a throwaway git repository with a tag, changes something after
it, and runs the script there: the decision depends on `git describe` and
`git diff` against the tag, so a test that skipped git would skip the seam.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("release_docs", SCRIPTS / "release_docs.py")
release_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_docs)

DOCS = Path("src/mcp_unifi_applications/docs")
BASE = "https://github.com/KallistoX/mcp-unifi-applications"
TODAY = "2026-10-19"

CHANGELOG = f"""# Changelog

Intro.

## [Unreleased]

## [0.4.0] - 2026-09-10

### Fixed

- Something.

[Unreleased]: {BASE}/compare/v0.4.0...HEAD
[0.4.0]: {BASE}/releases/tag/v0.4.0
"""

README = """# Readme

<!-- docs-versions:start -->
stale
<!-- docs-versions:end -->

mcp-name: io.github.KallistoX/mcp-unifi-applications
"""


def _git(root: Path, *args: str) -> str:
    # Signing off: the developer's global config may sign every commit through an
    # SSH agent, which would prompt (or fail) for a throwaway test repository.
    return subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _write_meta(root: Path, app: str, version: str) -> None:
    app_dir = root / DOCS / app
    app_dir.mkdir(parents=True, exist_ok=True)
    meta = {"app": app, "version": version, "scrapedAt": "2026-09-10T00:00:00Z", "pageCount": 1}
    (app_dir / "_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (app_dir / "page.json").write_text(json.dumps({"version": version}) + "\n")


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    (root / "pyproject.toml").write_text('[project]\nname = "mcp-unifi-applications"\nversion = "0.4.0"\n')
    server = {
        "name": "io.github.KallistoX/mcp-unifi-applications",
        "version": "0.4.0",
        "packages": [{"registryType": "pypi", "identifier": "mcp-unifi-applications", "version": "0.4.0"}],
    }
    (root / "server.json").write_text(json.dumps(server, indent=2) + "\n")
    (root / "CHANGELOG.md").write_text(CHANGELOG)
    (root / "README.md").write_text(README)
    pkg = root / "src/mcp_unifi_applications"
    pkg.mkdir(parents=True)
    (pkg / "server.py").write_text("# server\n")
    _write_meta(root, "network", "10.4.57")
    _write_meta(root, "protect", "7.3.47")
    _commit(root, "chore: release 0.4.0")
    _git(root, "tag", "v0.4.0")
    return root


def _run(root: Path, tmp_path: Path, monkeypatch) -> tuple[int, dict[str, str], Path]:
    out = tmp_path / "github_output"
    out.write_text("")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    notes = tmp_path / "notes.md"
    code = release_docs.main(["--notes", str(notes)], root=root, today=TODAY)
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if line)
    return code, outputs, notes


def _snapshot(root: Path) -> dict[str, str]:
    return {name: (root / name).read_text() for name in ("pyproject.toml", "server.json", "CHANGELOG.md", "README.md")}


class TestDecision:
    def test_nothing_since_the_tag_releases_nothing(self, repo, tmp_path, monkeypatch):
        before = _snapshot(repo)
        code, outputs, _ = _run(repo, tmp_path, monkeypatch)
        assert code == 0
        assert outputs == {"release": "false"}
        assert _snapshot(repo) == before

    def test_changes_outside_the_package_release_nothing(self, repo, tmp_path, monkeypatch):
        (repo / "README.md").write_text(README + "\nMore prose.\n")
        _commit(repo, "docs: readme")
        code, outputs, _ = _run(repo, tmp_path, monkeypatch)
        assert code == 0
        assert outputs == {"release": "false"}

    @pytest.mark.parametrize("path", ["src/mcp_unifi_applications/server.py", "pyproject.toml"])
    def test_unreleased_package_change_stops_the_release(self, repo, tmp_path, monkeypatch, capsys, path):
        _write_meta(repo, "network", "10.6.106")
        (repo / path).write_text((repo / path).read_text() + "# changed\n")
        _commit(repo, "mixed")
        before = _snapshot(repo)
        code, outputs, _ = _run(repo, tmp_path, monkeypatch)
        assert code == 1
        assert "release" not in outputs
        assert path in capsys.readouterr().out
        assert _snapshot(repo) == before

    def test_version_that_does_not_match_the_tag_stops_the_release(self, repo, tmp_path, monkeypatch, capsys):
        # pyproject was never bumped for v0.4.0: a patch on top would collide with
        # the version that is already on PyPI.
        _git(repo, "tag", "-d", "v0.4.0")
        _git(repo, "tag", "v0.4.1")
        _write_meta(repo, "network", "10.6.106")
        _commit(repo, "docs(network): v10.6.106")
        code, _, _ = _run(repo, tmp_path, monkeypatch)
        assert code == 1
        assert "0.4.0" in capsys.readouterr().out


class TestRelease:
    @pytest.fixture
    def released(self, repo, tmp_path, monkeypatch):
        _write_meta(repo, "network", "10.6.106")
        _commit(repo, "docs(network): v10.6.106")
        _write_meta(repo, "protect", "7.3.70")
        _commit(repo, "docs(protect): v7.3.70")
        code, outputs, notes = _run(repo, tmp_path, monkeypatch)
        assert code == 0
        return repo, outputs, notes

    def test_outputs_name_the_patch_version(self, released):
        _, outputs, _ = released
        assert outputs == {"release": "true", "version": "0.4.1", "tag": "v0.4.1"}

    def test_every_version_field_is_bumped(self, released):
        repo, _, _ = released
        assert 'version = "0.4.1"' in (repo / "pyproject.toml").read_text()
        server = json.loads((repo / "server.json").read_text())
        assert server["version"] == "0.4.1"
        assert [p["version"] for p in server["packages"]] == ["0.4.1"]

    def test_changelog_gets_a_dated_section_under_unreleased(self, released):
        repo, _, _ = released
        text = (repo / "CHANGELOG.md").read_text()
        assert f"## [Unreleased]\n\n## [0.4.1] - {TODAY}\n\n### Changed\n\n" in text
        assert "- Network API documentation updated from v10.4.57 to v10.6.106.\n" in text
        assert "- Protect API documentation updated from v7.3.47 to v7.3.70.\n" in text
        assert text.index("[0.4.1] -") < text.index("[0.4.0] -")

    def test_changelog_links_move_to_the_new_tag(self, released):
        repo, _, _ = released
        text = (repo / "CHANGELOG.md").read_text()
        assert f"[Unreleased]: {BASE}/compare/v0.4.1...HEAD\n[0.4.1]: {BASE}/releases/tag/v0.4.1\n" in text
        assert f"[0.4.0]: {BASE}/releases/tag/v0.4.0" in text

    def test_notes_are_the_section_body(self, released):
        _, _, notes = released
        body = notes.read_text()
        assert body.startswith("### Changed\n\n- Network API documentation updated")
        assert "## [" not in body

    def test_readme_table_is_regenerated(self, released):
        repo, _, _ = released
        readme = (repo / "README.md").read_text()
        assert "| Network | v10.6.106 |" in readme
        assert "stale" not in readme


class TestChangelogShapes:
    def test_existing_unreleased_entries_join_the_release(self, repo, tmp_path, monkeypatch):
        text = CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Changed\n\n- Hand-written entry.\n")
        (repo / "CHANGELOG.md").write_text(text)
        _write_meta(repo, "network", "10.6.106")
        _commit(repo, "docs(network): v10.6.106")
        code, _, notes = _run(repo, tmp_path, monkeypatch)
        assert code == 0
        out = (repo / "CHANGELOG.md").read_text()
        section = out.split(f"## [0.4.1] - {TODAY}\n", 1)[1].split("\n## [", 1)[0]
        assert section.count("### Changed") == 1
        assert "- Network API documentation updated" in section
        assert "- Hand-written entry." in section
        assert out.split("## [Unreleased]\n", 1)[1].lstrip().startswith("## [0.4.1]")
        assert "- Hand-written entry." in notes.read_text()

    def test_same_version_rescrape_says_so(self, repo, tmp_path, monkeypatch):
        (repo / DOCS / "protect" / "page.json").write_text('{"version": "7.3.47", "fixed": true}\n')
        _commit(repo, "docs(protect): re-scrape after a scraper fix")
        code, _, _ = _run(repo, tmp_path, monkeypatch)
        assert code == 0
        assert "- Protect API documentation re-scraped at v7.3.47.\n" in (repo / "CHANGELOG.md").read_text()

    def test_new_application_reads_as_added(self, repo, tmp_path, monkeypatch):
        _write_meta(repo, "site-manager", "1.0.0")
        _commit(repo, "docs(site-manager): v1.0.0")
        code, _, _ = _run(repo, tmp_path, monkeypatch)
        assert code == 0
        assert "- Site Manager API documentation added at v1.0.0.\n" in (repo / "CHANGELOG.md").read_text()
