# Update Round Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh scraped UniFi docs to current upstream versions, make the served docs version visible (scraper `_meta.json` + server `get_docs_info`), fix small MCP server gaps, and add a weekly GitHub Actions pipeline that auto-opens PRs when upstream publishes a new API version.

**Architecture:** The Playwright scraper (`scrape.mjs`, runs in Docker) gains version metadata output; the FastMCP stdio server (`mcp_server.py`) loads that metadata and exposes it. CI stays on GitHub Actions (public repo): the existing `ci.yml` gains ruff, and a new `update-docs.yml` does a cheap curl-based upstream version check weekly, scraping + opening a PR only when outdated.

**Tech Stack:** Node/Playwright (scraper, Docker), Python 3.11+/fastmcp/rapidfuzz/pytest/ruff (server), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-17-update-round-design.md`

**Repo:** `/home/kallisto/dev/Docker/mcp-unifi-applications` (work directly on `main`; push only in the final task)

**Verified facts the plan relies on (checked 2026-07-17):**
- Upstream latest: network v10.3.58 (local: v10.1.84), protect v7.1.87 (local: v6.2.88), site-manager v1.0.0 (local: same).
- The version list appears in the **static HTML** of `https://developer.ui.com/<app>` — `curl | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+'` works without Playwright (verified from this network).
- fastmcp 3.4.4's `@mcp.tool()` still returns the plain function (verified in a throwaway venv), so existing tests that call `m.list_endpoints(...)` directly keep working after the dep bump.
- 31 endpoint JSONs have non-empty `queryParameters` — the Task 5 test genuinely fails before the fix.
- Existing tests: 39, all invoke tools as plain functions on `import mcp_server as m`.
- `docs/tmp_pageClarification/` is gitignored, but one stray file (`docs/tmp_pageClarification/docs/network/_index.json`) is tracked from before the ignore rule — cleaned up in Task 2.

---

### Task 1: Scraper — write `_meta.json`, only write index/meta on full runs, clear stale `_failed.txt`

**Files:**
- Modify: `scrape.mjs` (imports at line 11, output block at lines 513-550)

There is no JS test infra (and none is being added — YAGNI); verification is `node --check` here plus the real scrape in Task 2.

- [ ] **Step 1: Extend the fs import**

At line 11, change:

```js
import { writeFileSync, mkdirSync, existsSync } from 'fs';
```

to:

```js
import { writeFileSync, mkdirSync, existsSync, rmSync } from 'fs';
```

- [ ] **Step 2: Clear a stale `_failed.txt` at the start of every run**

Right after `mkdirSync(outDir, { recursive: true });` (line 515), add:

```js
rmSync(`${outDir}/_failed.txt`, { force: true });
```

Without this, a failed run followed by a clean re-run leaves the old `_failed.txt` behind and the CI guard in Task 9 would false-positive forever.

- [ ] **Step 3: Only write `_index.json` on full runs, and also write `_meta.json`**

Replace (currently lines 543-544):

```js
const index = links.map(({ href, text }) => ({ slug: href.split('/').pop(), title: text, file: `${href.split('/').pop()}.json` }));
writeFileSync(`${outDir}/_index.json`, JSON.stringify(index, null, 2));
```

with:

```js
if (!singleMode) {
  const index = links.map(({ href, text }) => ({ slug: href.split('/').pop(), title: text, file: `${href.split('/').pop()}.json` }));
  writeFileSync(`${outDir}/_index.json`, JSON.stringify(index, null, 2));
  writeFileSync(`${outDir}/_meta.json`, JSON.stringify({
    app: requestedApp,
    version,
    scrapedAt: new Date().toISOString(),
    pageCount: links.length,
  }, null, 2));
}
```

This fixes the pre-existing bug where a slug-filtered run (`node scrape.mjs createnetwork`) overwrote `_index.json` with only the selected slugs.

- [ ] **Step 4: Syntax check**

Run: `node --check scrape.mjs`
Expected: no output, exit 0. (If `node` is missing locally: `nix shell nixpkgs#nodejs --command node --check scrape.mjs`)

- [ ] **Step 5: Commit**

```bash
git add scrape.mjs
git commit -m "feat(scraper): write _meta.json; index/meta only on full runs; clear stale _failed.txt"
```

---

### Task 2: One-time docs refresh (network v10.3.58, protect v7.1.87, site-manager re-scrape)

**Files:**
- Replace contents of: `docs/network/`, `docs/protect/`, `docs/site-manager/`
- Delete from git: `docs/tmp_pageClarification/docs/network/_index.json` (stray tracked file in an otherwise-ignored dir)

**Heads-up:** the scrape is sequential Playwright DOM-walking with many `waitForTimeout`s — expect 30-90 min total. Run the three scrape commands in the background and check on them; do NOT declare failure on slowness. Site-manager is re-scraped even though the version is unchanged, so that all three apps get a `_meta.json` (and content drift is picked up).

- [ ] **Step 1: Build the scraper image (picks up Task 1 changes)**

```bash
cd /home/kallisto/dev/Docker/mcp-unifi-applications
docker build -t unifi-scraper .
```

Expected: image builds; `COPY *.mjs` layer is NOT cached (scrape.mjs changed).

- [ ] **Step 2: Remove stale pages, then scrape all three apps (background, sequential)**

Removed-upstream endpoints must show up as deletions, so wipe each app dir first (`--force` alone only overwrites, never deletes):

```bash
rm -f docs/network/*.json docs/network/_failed.txt
rm -f docs/protect/*.json docs/protect/_failed.txt
rm -f docs/site-manager/*.json docs/site-manager/_failed.txt
docker run --rm -v "$PWD/docs:/output" unifi-scraper node scrape.mjs --app network --force \
  && docker run --rm -v "$PWD/docs:/output" unifi-scraper node scrape.mjs --app protect --force \
  && docker run --rm -v "$PWD/docs:/output" unifi-scraper node scrape.mjs --app site-manager --force
```

Expected (per app): `Using API version: v10.3.58` / `v7.1.87` / `v1.0.0`, then per-page ✓ lines, final `Done. N <app> pages (vX.Y.Z).`

If upstream released an even newer version since 2026-07-17, the default "latest" is what we want — just note the actual version in the commit message.

- [ ] **Step 3: Verify the scrape is clean**

```bash
ls docs/network/_failed.txt docs/protect/_failed.txt docs/site-manager/_failed.txt 2>&1
cat docs/network/_meta.json docs/protect/_meta.json docs/site-manager/_meta.json
```

Expected: all three `_failed.txt` **missing** (`No such file`); each `_meta.json` shows the right `app`, the new `version`, a current `scrapedAt`, `pageCount` > 0.

If `_failed.txt` exists: re-run that app's scrape (without `rm`, without `--force` — it skips existing pages and retries only missing ones... note failed pages were written as `{"error": ...}` stubs, so delete the stub files listed in `_failed.txt` first, then re-run without `--force`).

- [ ] **Step 4: Run the test suite against the fresh docs**

Run: `.venv/bin/pytest tests/ -v`
Expected: all 39 tests PASS. (`test_all_json_files_parse` / `test_endpoints_have_required_fields` are the real guards here — they fail if any scraped page is malformed.)

- [ ] **Step 5: Spot-check one discriminator-heavy endpoint**

```bash
.venv/bin/python -c "
import mcp_server as m
out = m.get_endpoint('network/createnetwork')
print(out[:800])
assert 'GATEWAY' in out or 'management' in out, 'discriminator variants missing'
print('OK')"
```

Expected: schema summary with discriminator variants, then `OK`.

- [ ] **Step 6: Stage, collect diff stats, drop the stray tracked file**

```bash
git rm -r --cached docs/tmp_pageClarification
git add -A docs/network docs/protect docs/site-manager
for app in network protect site-manager; do
  echo "$app: added=$(git diff --cached --name-status -- docs/$app | grep -c '^A') modified=$(git diff --cached --name-status -- docs/$app | grep -c '^M') deleted=$(git diff --cached --name-status -- docs/$app | grep -c '^D')"
done
```

Expected: per-app add/modify/delete counts (protect will churn heavily — v6→v7 major).

- [ ] **Step 7: Commit with the diff summary**

Fill in the real numbers/versions from Steps 2 and 6 (write the message to a temp file and use `git commit -F` — fish-safe):

```bash
git commit -F- <<'EOF'
docs: refresh scraped docs (network v10.3.58, protect v7.1.87, site-manager v1.0.0)

network v10.1.84 -> v10.3.58: <A> added, <M> modified, <D> removed pages
protect v6.2.88 -> v7.1.87 (major): <A> added, <M> modified, <D> removed pages
site-manager v1.0.0 re-scrape: <A> added, <M> modified, <D> removed pages

Each app dir now carries _meta.json (app, version, scrapedAt, pageCount).
Also removes a stray tracked file under the gitignored docs/tmp_pageClarification/.
EOF
```

(Replace the `<A>/<M>/<D>` placeholders with the actual counts before committing.)

---

### Task 3: Server — load `_meta.json`, name versions in instructions

**Files:**
- Modify: `mcp_server.py` (globals ~line 27, `_load_app` line 63, `_load_docs` line 97, move `mcp = FastMCP(...)` from line 18 to after `_load_docs()`)
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_server.py` (add `import re` to the imports at the top):

```python
# --- Version metadata ---


class TestMeta:
    def test_meta_files_parse_and_match_dir(self):
        docs_dir = Path(__file__).parent.parent / "docs"
        found = 0
        for app_dir in docs_dir.iterdir():
            if not app_dir.is_dir() or app_dir.name.startswith(("_", ".")) or app_dir.name == "tmp_pageClarification":
                continue
            meta_file = app_dir / "_meta.json"
            if not meta_file.exists():
                continue
            data = json.loads(meta_file.read_text())
            assert data["app"] == app_dir.name, f"{meta_file}: app mismatch"
            assert re.fullmatch(r"\d+(\.\d+)*", data["version"]), f"{meta_file}: bad version"
            assert data["pageCount"] > 0
            found += 1
        assert found > 0, "no _meta.json found in any app dir"

    def test_meta_loaded_for_known_apps(self):
        for app in ("network", "protect", "site-manager"):
            if app in m._loaded_apps:
                assert app in m._meta, f"{app} has no _meta loaded"

    def test_instructions_name_versions(self):
        for app, meta in m._meta.items():
            assert f"{app} v{meta['version']}" in m.mcp.instructions
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_mcp_server.py::TestMeta -v`
Expected: FAIL — `AttributeError: module 'mcp_server' has no attribute '_meta'`.

- [ ] **Step 3: Implement**

(a) In `mcp_server.py`, **delete** the `mcp = FastMCP(...)` block (currently lines 18-23) from its position above the data-loading section. It moves below in (d) — the first `@mcp.tool()` use is far later, so this is safe.

(b) Add a `_meta` global next to the other module state (after `_loaded_apps`, ~line 32):

```python
_meta: dict[str, dict] = {}  # app -> {"app", "version", "scrapedAt", "pageCount"}
```

(c) In `_load_app`, normalize the app name, record it, and load the metadata — replace the first two lines of the function body:

```python
def _load_app(app: str, directory: Path):
    """Load all JSON docs from a single app directory."""
    name = app or "network"
    _loaded_apps.add(name)
    meta_file = directory / "_meta.json"
    if meta_file.exists():
        try:
            _meta[name] = json.loads(meta_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
```

(`_loaded_apps.add(app)` becomes `add(name)` — the flat-layout fallback used to add `""`; nothing reads members except `len()`, so this is a safe consistency fix.)

(d) In `_load_docs`, add `_meta.clear()` next to the other `.clear()` calls. Then, directly **after** the `_load_docs()` call (currently line 117), create the server:

```python
def _docs_summary() -> str:
    parts = []
    for app in sorted(_loaded_apps):
        v = _meta.get(app, {}).get("version")
        parts.append(f"{app} v{v}" if v else f"{app} (version unknown)")
    return ", ".join(parts)


mcp = FastMCP("unifi-applications", instructions=(
    "You have access to UniFi application API documentation (Network, Protect, Site Manager). "
    "Use list_endpoints to browse, search_endpoints to find relevant endpoints, "
    "and get_endpoint to get full schema details. Use get_endpoint_group to get "
    "all CRUD operations for a resource at once. Filter by app name to narrow results. "
    f"Loaded docs: {_docs_summary()}. Use get_docs_info for scrape details."
))
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all tests PASS (39 old + 3 new).

- [ ] **Step 5: Commit**

```bash
git add mcp_server.py tests/test_mcp_server.py
git commit -m "feat(server): load _meta.json, name docs versions in server instructions"
```

---

### Task 4: `get_docs_info` tool

**Files:**
- Modify: `mcp_server.py` (new tool, place after `get_guide`)
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_server.py`:

```python
# --- get_docs_info ---


class TestGetDocsInfo:
    def test_lists_every_loaded_app(self):
        out = m.get_docs_info()
        for app in m._loaded_apps:
            assert app in out

    def test_contains_versions_and_counts(self):
        out = m.get_docs_info()
        for app, meta in m._meta.items():
            assert f"API v{meta['version']}" in out
        assert "endpoints" in out
        assert "guides" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_mcp_server.py::TestGetDocsInfo -v`
Expected: FAIL — `AttributeError: module 'mcp_server' has no attribute 'get_docs_info'`.

- [ ] **Step 3: Implement**

Add after the `get_guide` tool in `mcp_server.py`:

```python
@mcp.tool()
def get_docs_info() -> str:
    """Show which UniFi API docs are loaded: API version, scrape date, endpoint and guide counts per app."""
    if not _loaded_apps:
        return "No docs loaded. Check DOCS_DIR."
    lines = []
    for app in sorted(_loaded_apps):
        meta = _meta.get(app, {})
        n_ep = sum(1 for e in _endpoints.values() if e["_app"] == app)
        n_gd = sum(1 for g in _guides.values() if g["_app"] == app)
        lines.append(
            f"{app}: API v{meta.get('version', 'unknown')}, "
            f"scraped {meta.get('scrapedAt', 'unknown')}, "
            f"{n_ep} endpoints, {n_gd} guides"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp_server.py tests/test_mcp_server.py
git commit -m "feat(server): get_docs_info tool exposing docs version metadata"
```

---

### Task 5: Index `queryParameters` in the field index

**Files:**
- Modify: `mcp_server.py:87-88` (the `section_key` loop in `_load_app`)
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing test**

Append inside a new class in `tests/test_mcp_server.py`:

```python
# --- Field index covers query parameters ---


class TestQueryParameterIndex:
    def test_query_parameters_indexed(self):
        checked = 0
        for slug, ep in m._endpoints.items():
            for f in ep.get("queryParameters") or []:
                assert f["name"].lower() in m._field_index, (
                    f"query param '{f['name']}' of {slug} missing from field index"
                )
                checked += 1
        assert checked > 0, "corpus unexpectedly has no queryParameters"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_mcp_server.py::TestQueryParameterIndex -v`
Expected: FAIL on a missing query param (31 endpoints in the corpus have them).

- [ ] **Step 3: Implement**

In `_load_app`, change:

```python
        for section_key in ("pathParameters", "requestBody"):
```

to:

```python
        for section_key in ("pathParameters", "queryParameters", "requestBody"):
```

This makes `find_field` consistent with `get_field_schema`, which already searches `queryParameters`.

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp_server.py tests/test_mcp_server.py
git commit -m "fix(server): index queryParameters so find_field sees them"
```

---

### Task 6: Cap `list_endpoints` output

**Files:**
- Modify: `mcp_server.py` (`list_endpoints`, lines 160-187)
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing test**

```python
# --- list_endpoints cap ---


class TestListEndpointsCap:
    def test_caps_output_with_hint(self, monkeypatch):
        fake = [
            (f"network/fake{i}", f"Fake {i}", "GET", f"/v1/fake/{i}", "", "network")
            for i in range(300)
        ]
        monkeypatch.setattr(m, "_search_index", fake)
        out = m.list_endpoints()
        lines = out.split("\n")
        assert len(lines) == m.MAX_LIST_LINES + 1
        assert "truncated" in lines[-1]
        assert "app" in lines[-1] and "method" in lines[-1]

    def test_no_cap_below_limit(self):
        out = m.list_endpoints()
        assert "truncated" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_mcp_server.py::TestListEndpointsCap -v`
Expected: first test FAILS — `AttributeError: module 'mcp_server' has no attribute 'MAX_LIST_LINES'`. Second PASSES (current corpus ~120 endpoints).

- [ ] **Step 3: Implement**

Add a constant next to `VALID_LANGUAGES` (~line 34):

```python
MAX_LIST_LINES = 150
```

In `list_endpoints`, replace the final `return "\n".join(lines)` with:

```python
    if len(lines) > MAX_LIST_LINES:
        total = len(lines)
        lines = lines[:MAX_LIST_LINES]
        lines.append(
            f"... truncated: showing {MAX_LIST_LINES} of {total} endpoints. "
            "Filter by app= (network, protect, site-manager) or method= to narrow."
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp_server.py tests/test_mcp_server.py
git commit -m "feat(server): cap list_endpoints output at 150 lines with filter hint"
```

---

### Task 7: Dependency bumps (fastmcp >=3.4, rapidfuzz >=3.14.5)

**Files:**
- Modify: `pyproject.toml` (dependencies block)

- [ ] **Step 1: Bump the ranges**

In `pyproject.toml`, change:

```toml
dependencies = [
    "fastmcp>=3.1.1",
    "rapidfuzz>=3.14.3",
]
```

to:

```toml
dependencies = [
    "fastmcp>=3.4",
    "rapidfuzz>=3.14.5",
]
```

- [ ] **Step 2: Upgrade the venv**

Run: `.venv/bin/pip install -U "fastmcp>=3.4" "rapidfuzz>=3.14.5"`
Expected: fastmcp 3.4.x, rapidfuzz 3.14.x installed.

- [ ] **Step 3: Verify server import + full suite on the new versions**

```bash
.venv/bin/python -c "import mcp_server as m; print(m.mcp.name, len(m._endpoints), 'endpoints')"
.venv/bin/pytest tests/ -v
```

Expected: server imports, prints endpoint count; all tests PASS. (Pre-verified: fastmcp 3.4.4's `@mcp.tool()` still returns the plain function, so direct-call tests keep working.)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore(deps): fastmcp >=3.4, rapidfuzz >=3.14.5"
```

---

### Task 8: ruff (config, fixes, CI step)

**Files:**
- Modify: `pyproject.toml` (dev extras + `[tool.ruff]`)
- Modify: `.github/workflows/ci.yml`
- Possibly modify: `mcp_server.py`, `tests/test_mcp_server.py` (lint findings)

- [ ] **Step 1: Add ruff as dev dependency + config**

In `pyproject.toml`, change the dev extras and append a ruff section:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.14"]
```

```toml
[tool.ruff]
line-length = 120
target-version = "py311"
```

(line-length 120: the existing code has ~100-char lines; do not reformat the codebase.)

- [ ] **Step 2: Install and run**

```bash
.venv/bin/pip install "ruff>=0.14"
.venv/bin/ruff check .
```

Expected: zero or a handful of findings (default rule set E4/E7/E9/F on a small clean codebase). Fix exactly what it reports — `--fix` for safe autofixes is fine; no drive-by refactoring. Re-run until clean.

- [ ] **Step 3: Wire into CI**

In `.github/workflows/ci.yml`, replace the install + test steps:

```yaml
      - name: Install dependencies
        run: pip install .[dev]

      - name: Lint
        run: ruff check .

      - name: Run tests
        run: pytest tests/ -v
```

(The old install line was `pip install . pytest` — `.[dev]` now brings pytest and ruff.)

- [ ] **Step 4: Full suite once more**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .github/workflows/ci.yml mcp_server.py tests/test_mcp_server.py
git commit -m "chore: add ruff lint (config + CI step)"
```

(Only add the .py files if Step 2 actually changed them.)

---

### Task 9: Auto-update pipeline (`update-docs.yml`)

**Files:**
- Create: `.github/workflows/update-docs.yml`

- [ ] **Step 1: Create the workflow**

```yaml
name: Update docs

on:
  schedule:
    - cron: "17 5 * * 1"  # Mondays 05:17 UTC
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

concurrency:
  group: update-docs
  cancel-in-progress: false

jobs:
  check:
    runs-on: ubuntu-latest
    outputs:
      apps: ${{ steps.compare.outputs.apps }}
    steps:
      - uses: actions/checkout@v5

      - name: Compare upstream vs scraped versions
        id: compare
        run: |
          set -euo pipefail
          outdated=()
          for app in network protect site-manager; do
            html=$(curl -fsSL --max-time 30 "https://developer.ui.com/${app}")
            latest=$(echo "$html" | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | sort -uV | tail -1 || true)
            if [ -z "$latest" ]; then
              echo "::error::No version strings found in https://developer.ui.com/${app} - site layout may have changed"
              exit 1
            fi
            current="v$(python3 -c "import json; print(json.load(open('docs/${app}/_meta.json'))['version'])" 2>/dev/null || echo 0.0.0)"
            echo "${app}: scraped=${current} upstream=${latest}"
            if [ "$latest" != "$current" ]; then
              outdated+=("$app")
            fi
          done
          if [ "${#outdated[@]}" -eq 0 ]; then
            apps="[]"
          else
            apps=$(printf '%s\n' "${outdated[@]}" | jq -R . | jq -cs .)
          fi
          echo "apps=${apps}" >> "$GITHUB_OUTPUT"

  scrape:
    needs: check
    if: needs.check.outputs.apps != '[]'
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        app: ${{ fromJSON(needs.check.outputs.apps) }}
    steps:
      - uses: actions/checkout@v5

      - name: Build scraper image
        run: docker build -t unifi-scraper .

      - name: Scrape ${{ matrix.app }}
        run: |
          rm -f "docs/${{ matrix.app }}"/*.json "docs/${{ matrix.app }}/_failed.txt"
          docker run --rm -v "${{ github.workspace }}/docs:/output" unifi-scraper \
            node scrape.mjs --app "${{ matrix.app }}" --force

      - name: Fail if pages failed to scrape
        run: |
          if [ -f "docs/${{ matrix.app }}/_failed.txt" ]; then
            echo "::error::Scrape had failures - not opening a PR"
            cat "docs/${{ matrix.app }}/_failed.txt"
            exit 1
          fi

      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Test against fresh docs
        run: |
          pip install .[dev]
          ruff check .
          pytest tests/ -v

      - name: Read scraped version and diff stats
        id: stats
        run: |
          set -euo pipefail
          version=$(python3 -c "import json; print(json.load(open('docs/${{ matrix.app }}/_meta.json'))['version'])")
          git add -A "docs/${{ matrix.app }}"
          added=$(git diff --cached --name-status -- "docs/${{ matrix.app }}" | grep -c '^A' || true)
          modified=$(git diff --cached --name-status -- "docs/${{ matrix.app }}" | grep -c '^M' || true)
          deleted=$(git diff --cached --name-status -- "docs/${{ matrix.app }}" | grep -c '^D' || true)
          {
            echo "version=${version}"
            echo "added=${added}"
            echo "modified=${modified}"
            echo "deleted=${deleted}"
          } >> "$GITHUB_OUTPUT"

      - name: Open PR
        uses: peter-evans/create-pull-request@v7
        with:
          branch: update-docs/${{ matrix.app }}-v${{ steps.stats.outputs.version }}
          title: "docs(${{ matrix.app }}): update scraped docs to v${{ steps.stats.outputs.version }}"
          commit-message: "docs(${{ matrix.app }}): update scraped docs to v${{ steps.stats.outputs.version }}"
          add-paths: docs/${{ matrix.app }}/**
          body: |
            Automated docs refresh: upstream published **v${{ steps.stats.outputs.version }}** for `${{ matrix.app }}`.

            - Pages: ${{ steps.stats.outputs.added }} added, ${{ steps.stats.outputs.modified }} modified, ${{ steps.stats.outputs.deleted }} removed
            - Scrape had no failed pages; ruff + pytest passed against the fresh docs.

            Weekly `update-docs` workflow.
```

- [ ] **Step 2: Validate the YAML**

Run: `.venv/bin/python -c "import yaml, sys; yaml.safe_load(open('.github/workflows/update-docs.yml')); print('OK')"` — if PyYAML isn't in the venv, use `nix shell nixpkgs#yq-go --command yq e '.name' .github/workflows/update-docs.yml` (expected output: `Update docs`).

- [ ] **Step 3: Dry-run the check logic locally**

```bash
for app in network protect site-manager; do
  latest=$(curl -fsSL --max-time 30 "https://developer.ui.com/${app}" | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | sort -uV | tail -1)
  current="v$(python3 -c "import json; print(json.load(open('docs/${app}/_meta.json'))['version'])")"
  echo "${app}: scraped=${current} upstream=${latest}"
done
```

Expected after Task 2: all three lines show scraped == upstream.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/update-docs.yml
git commit -m "ci: weekly auto-update pipeline (version check -> scrape -> PR)"
```

---

### Task 10: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the pre-scraped versions line**

Find `Pre-scraped docs for Network API v10.1.84 are included in \`docs/network/\`.` and replace with:

```markdown
Pre-scraped docs are included: Network API v10.3.58 (`docs/network/`), Protect v7.1.87 (`docs/protect/`), Site Manager v1.0.0 (`docs/site-manager/`). Each app dir carries a `_meta.json` (API version, scrape date, page count). A weekly GitHub Action checks upstream for new versions and opens a PR with freshly scraped docs.
```

(If the exact sentence differs, adapt — the point is: current versions, `_meta.json`, auto-update mention.)

- [ ] **Step 2: Add `get_docs_info` to the tools documentation**

Locate the section listing the MCP tools (search for `list_endpoints` outside the quick-start). Append in the same style as the existing entries:

```markdown
- **`get_docs_info()`** — which docs are loaded: API version, scrape date, endpoint/guide counts per app
```

Adapt formatting to the surrounding list/table.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README - current versions, _meta.json, auto-update workflow, get_docs_info"
```

---

### Task 11: Push, verify CI, smoke-test the update workflow

- [ ] **Step 1: Push**

```bash
git push origin main
```

- [ ] **Step 2: Watch CI**

```bash
gh run watch --repo KallistoX/mcp-unifi-applications --exit-status $(gh run list --repo KallistoX/mcp-unifi-applications --branch main --limit 1 --json databaseId --jq '.[0].databaseId')
```

Expected: `CI` workflow (ruff + pytest) green.

- [ ] **Step 3: Smoke-test `update-docs` via dispatch**

```bash
gh workflow run update-docs.yml --repo KallistoX/mcp-unifi-applications
sleep 30
gh run list --repo KallistoX/mcp-unifi-applications --workflow update-docs.yml --limit 1
```

Expected: the `check` job succeeds and logs `scraped == upstream` for all apps; the `scrape` job is **skipped** (`apps == []`). That proves the pipeline end-to-end minus the scrape leg, which was just exercised locally in Task 2. If `curl` from GitHub runners is blocked by the docs site (bot protection), the check job fails loudly — then note it and we reconsider (e.g. retry with headers) rather than shipping a silent workflow.

- [ ] **Step 4: Reload the live MCP session**

The `unifi-applications` server registered in `homelab-infra/.mcp.json` runs this repo's venv directly — tell the user: **Reload Window** (or restart Claude Code session) to pick up the new server code and fresh docs; then `get_docs_info` should report the new versions.

---

## Self-review notes

- Spec coverage: §1 → Task 2; §2 → Tasks 1, 3, 4; §3 → Tasks 5, 6, 7, 8; §4 → Task 9; §5 stays deferred (no task, by design). README (implied by public repo) → Task 10.
- Type consistency: `_meta` keyed by normalized app name (`app or "network"`), matching `_loaded_apps` after the Task 3 normalization; `get_docs_info` counts via `e["_app"]`, which is already normalized today.
- Task 2 runs before Tasks 3-6 because their tests assert against real `_meta.json` files.
