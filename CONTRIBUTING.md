# Contributing

Contributions are welcome! Here's how to get started.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/KallistoX/mcp-unifi-applications.git
cd mcp-unifi-applications

# Python (MCP server)
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

# Node (scraper) — or use Docker
npm install
```

## Running Tests

```bash
pytest tests/ -v      # MCP server
node --test tests/*.test.mjs   # scraper parsers (lib/parse.mjs)
```

The scraper's parsing logic lives in `lib/parse.mjs` rather than inside the
`page.evaluate` callbacks, because Playwright serialises those into the browser
where no test can reach them. Keep it that way: have the browser read the DOM
and return plain data, and make every decision in `lib/`.

## Scraper Development

The scraper requires Playwright with Chromium. The easiest way to run it is via Docker:

```bash
docker build -t unifi-scraper .
docker run --rm -v "$(pwd)/src/mcp_unifi_applications/docs:/output" unifi-scraper node scrape.mjs --app network
```

To run locally without Docker, install Playwright and its browser dependencies:

```bash
npm install
npx playwright install chromium
node scrape.mjs --app network
```

Note: when running locally, output goes to `/output` by default (the Docker mount point). Override by editing the `OUTPUT` constant or symlinking. Scraped docs belong in `src/mcp_unifi_applications/docs/<app>/` — they ship inside the package, so the server finds them after `pip install`.

## Adding a New Application

If Ubiquiti adds a new developer docs application at `developer.ui.com/<app-name>`:

1. Add the app to the `APPS` object in `scrape.mjs` with its path and supported modes
2. Run the scraper: `node scrape.mjs --app <app-name>`
3. Add it to the version-check loop in `.github/workflows/update-docs.yml`
4. The MCP server auto-discovers new app subdirectories under `src/mcp_unifi_applications/docs/` — no server changes needed

## Pull Requests

- Keep changes focused — one feature or fix per PR
- Add or update tests for any new functionality
- Run `pytest tests/ -v` and make sure all tests pass before submitting

## Writing a test client

Tool failures come back as `result.isError: true` with the message in
`result.content[].text` — **not** as a JSON-RPC `error`. A driver that only checks for
`error` reads every failure as a success. This has caught two people out; check both.

## Changelog

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Add your entry under `## [Unreleased]` in the same PR as the change, rather than
reconstructing it at release time. On release, rename that heading to the version
and open a fresh `Unreleased` section. The same text goes into the GitHub release
notes and into Glama's changelog field, which has to be filled in by hand.

## The README version table

The table in the Quick Start is generated from the committed
`src/mcp_unifi_applications/docs/<app>/_meta.json` files by
`scripts/update_readme_versions.py`, between the `<!-- docs-versions -->` markers.

Do not edit it by hand, and do not regenerate it inside a docs PR. The weekly
`update-docs` workflow opens one PR per outdated app, and each would rewrite the
same block from its own branch, so the first merge would leave the rest
conflicting. `sync-readme-table.yml` regenerates it on `main` after a merge
instead, and because a merge made by the workflow itself may not start it,
`scripts/release_docs.py` regenerates it in every automatic release as well. Run
the script locally if you want to preview the result.

## Releases

**Docs refreshes release themselves.** The weekly `update-docs` workflow merges
each docs PR once the scrape has passed ruff and pytest, then calls `release.yml`.
That runs `scripts/release_docs.py`, which compares `main` with the last tag. When
scraped docs are the only change that ships in the package, it bumps the patch
version in `pyproject.toml` and `server.json`, adds a dated changelog section that
names each application's old and new API version, commits, tags, creates the
GitHub release and dispatches `publish.yml`. Dispatch `release.yml` by hand to
release docs that reached `main` some other way; `dry_run` shows the release
commit without pushing anything.

**Everything else is released by hand**, and the automatic release refuses to run
while such a change is unreleased: anything under `src/` outside the scraped docs,
or `pyproject.toml`. Bump the version in `pyproject.toml` and `server.json` in the
same commit (a test checks that they agree), move the `Unreleased` entries under
the new version, merge, and publish a GitHub release tagged `v<version>`.

Either way, `publish.yml` builds and checks the wheel, uploads it to PyPI through
Trusted Publishing, and publishes `server.json` to the
[official MCP registry](https://registry.modelcontextprotocol.io) with
`mcp-publisher login github-oidc`. There is no manual `mcp-publisher publish` step
any more. Should the registry job fail, fix the cause and re-run that job; the
workstation route still works as a fallback:

```bash
mcp-publisher login github    # opens a browser; namespace io.github.KallistoX is proven by the login
mcp-publisher publish
```

**Glama needs one click after every release.** Its listing auto-builds and releases
the new version, but only once it has synced from GitHub, and nothing triggers that
sync: press *Sync Server* on the listing's settings page. Without it the hosted
deployment stays on the previous version; on 2026-10-16 it still served 0.4.0 the
day after 0.4.1 shipped, then built and released 0.4.1 by itself once synced by
hand. Glama has no write API, so neither the sync nor its changelog field can be
automated.
