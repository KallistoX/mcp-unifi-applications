# Update Round: Docs Refresh, Version Metadata, MCP Fixes, Auto-Update Pipeline

**Date:** 2026-07-17
**Status:** Approved
**Scope:** Deliberately small. A full server overhaul (search ranking, module split, structured outputs, PyPI publishing) is explicitly deferred to a future brainstorm session (see Future Work).

## Context

The repo serves scraped UniFi application API docs (Network, Protect, Site Manager) through a FastMCP stdio server. Current state as of 2026-07-17:

| Area | Current | Target |
|------|---------|--------|
| Network docs | v10.1.84 (77 pages) | v10.3.58 |
| Protect docs | v6.2.88 (43 pages) | v7.1.87 (major bump) |
| Site Manager docs | v1.0.0 (13 pages) | unchanged |
| fastmcp | pinned `>=3.1.1`, venv has 3.1.1 | range `>=3.4` |
| CI | pytest only | pytest + ruff + scheduled auto-update |

Key findings that shaped the design:

- The version list for each app is present in the **static HTML** of `developer.ui.com/<app>` (extractable with `curl` + regex, no Playwright). Only the actual scraping needs the Playwright container. This makes a cheap upstream version check in CI possible.
- The scraped version is only implicit today (inside each page's `sourceUrl`). Neither the repo nor the MCP server can state which docs version is being served.
- `find_field` / the field index skip `queryParameters`, while `get_field_schema` does search them — inconsistent.
- Automation runs on **GitHub Actions** (repo is public there: free unlimited runners, native cron, no homelab secrets needed). The homelab Gitea's single runner and a Gitea→GitHub sync were considered and rejected (runner blocked 30–90 min by Playwright; sync adds a failure mode for zero benefit).

## 1. One-time docs refresh (local, via Docker)

- Re-scrape Network at v10.3.58 and Protect at v7.1.87 with `--force` using the existing scraper image.
- Site Manager stays as-is (v1.0.0 is still latest).
- Verification: full pytest run against the new docs, spot-check a handful of endpoints (including one discriminator-heavy one), and confirm no `_failed.txt` remains.
- The commit message summarises the endpoint diff (added/removed pages), since Protect v6→v7 is a major jump that consumers should be able to trace.

## 2. Version metadata (scraper + server)

**Scraper:** after a successful run, write `docs/<app>/_meta.json`:

```json
{
  "app": "network",
  "version": "10.3.58",
  "scrapedAt": "2026-07-17T12:00:00Z",
  "pageCount": 77
}
```

`_`-prefixed files are already skipped by the server's doc loader, so this is backward compatible. The scraper overwrites `_meta.json` on every full run; single-page (slug-filtered) runs do not touch it, so the metadata always describes a complete scrape. This also fixes an existing bug of the same shape: single-page runs currently overwrite `_index.json` with only the selected slugs, truncating the index — both `_index.json` and `_meta.json` are only written on full runs.

**Server:**

- Load `_meta.json` per app at startup (missing file → app listed with `version: unknown`, never a crash).
- Append a line to the FastMCP `instructions` naming the loaded apps and their API versions.
- New tool `get_docs_info()`: returns per app the API version, scrape date, endpoint count, and guide count.
- Tests: `_meta.json` parses, matches the app dir it sits in, `get_docs_info` output contains every loaded app.

## 3. MCP server fixes (no restructuring)

- **Field index gap:** `_load_app` also indexes `queryParameters` in `_index_fields`, making `find_field` consistent with `get_field_schema`. Test: a field that only exists in query parameters is findable.
- **`list_endpoints` cap:** cap output at 150 lines; when the cap hits, append a note with the total count and a hint to filter by `app`/`method`. (Currently ~120 endpoints total, so the cap only bites once more apps/versions grow the corpus.)
- **Dependency bump:** `fastmcp>=3.4`, `rapidfuzz>=3.14.5` in `pyproject.toml`; reinstall venv; verify server starts and tests pass.
- **Lint:** add ruff (default rules, line-length matched to the existing code) as dev dependency + config in `pyproject.toml`; fix any findings; add a ruff step to CI before pytest.

## 4. Auto-update pipeline (GitHub Actions: `update-docs.yml`)

Weekly cron + `workflow_dispatch`.

**Job `check`** (seconds, no Playwright):

- For each app: `curl` the app landing page, extract version strings (`v\d+\.\d+\.\d+` regex), take the highest; compare against `docs/<app>/_meta.json`.
- Output: matrix of apps whose upstream version is newer.
- If the HTML yields zero version strings (site layout changed), the job **fails loudly** rather than silently reporting "up to date".

**Job `scrape`** (only for outdated apps, matrix per app):

- Build the scraper image, run `node scrape.mjs --app <app> --force` (latest version).
- Guard: if `docs/<app>/_failed.txt` exists after the run, fail the job — no broken PR.
- Run pytest against the fresh docs.
- Open a PR via `peter-evans/create-pull-request`: branch `update-docs/<app>-v<version>`, title with the version bump, body with page count diff and failed/added/removed page stats. Human reviews and merges.

The existing CI workflow (ruff + pytest) runs on that PR as the merge gate.

## 5. Future Work (deferred, own brainstorm session)

- Search overhaul: proper ranking (e.g. BM25) instead of pure rapidfuzz scoring.
- Module split of `mcp_server.py` (loader / index / tools).
- FastMCP structured outputs / resources.
- Optional PyPI publishing.

## Non-goals

- No Gitea mirror or homelab-side CI for this repo.
- No change to the scraping approach (Playwright DOM parsing stays as-is).
- No new MCP tools beyond `get_docs_info`.
