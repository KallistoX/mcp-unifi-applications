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

# Node (scraper, pinned in package.json) - or use Docker
npm ci
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
npm ci
npx playwright install chromium
node scrape.mjs --app network
```

Note: when running locally, output goes to `/output` by default (the Docker mount point). Override by editing the `OUTPUT` constant or symlinking. Scraped docs belong in `src/mcp_unifi_applications/docs/<app>/` — they ship inside the package, so the server finds them after `pip install`.

### Scraper CLI

```
node scrape.mjs [options] [slug...]

Options:
  --app <name>      Application: network (default), protect, site-manager, innerspace, mobility, carrier-fabric.
  --version <ver>   API version to scrape (e.g. v10.1.84). Default: latest.
  --list-versions   Print available versions and exit.
  --force           Re-scrape even if output file exists.

Arguments:
  [slug...]         Scrape only these pages. Omit to scrape all pages.
```

The slug is the last path segment of the docs URL:
`https://developer.ui.com/network/v10.1.84/createnetwork` -> `createnetwork`

Output is written to `<output>/<app>/` — mount the package's docs directory (`src/mcp_unifi_applications/docs/`) so a scrape lands where the server reads it.

The full scan is resumable - already-scraped pages are skipped. Use `--force` to re-scrape.

The Docker image takes the same arguments, e.g.
`docker run --rm unifi-scraper node scrape.mjs --app protect --list-versions`.

Playwright is pinned twice and the two must agree: the version in `package.json`
(locked in `package-lock.json`) and the tag of the `mcr.microsoft.com/playwright` base
image in the `Dockerfile`, which ships the matching browsers.

### Supported applications

| Application | URL | Local/Remote | Notes |
|---|---|---|---|
| Network | `developer.ui.com/network` | Both | Default app |
| Protect | `developer.ui.com/protect` | Both | |
| Site Manager | `developer.ui.com/site-manager` | Remote only | No local/remote switch |
| InnerSpace | `developer.ui.com/innerspace` | Both | Early Access; version label reads `v1.3.23 (EA)` |
| Mobility | `developer.ui.com/mobility` | Remote only | Sidebar links out to `mobility.ui.com` |
| Carrier Fabric | `developer.ui.com/carrier-fabric` | Remote only | Subscriber API |

All applications share the same docs SPA structure with version dropdowns, endpoint pages, and guide pages, so adding one is a single entry in the `APPS` object in `scrape.mjs` — the server discovers new app directories on its own.

### Serving a fresh scrape

The server reads `src/mcp_unifi_applications/docs/` inside the installed package. Set
`DOCS_DIR` to point it at another directory with one subdirectory per application
(`network/`, `protect/`, ...), for example a checkout's freshly scraped output.

### Output format

What the scraper writes, and what the server reads.

#### Endpoint pages

```json
{
  "h1": "Create Network",
  "method": "POST",
  "path": "/v1/sites/{siteId}/networks",
  "description": "Create a new network on a site.",
  "pathParameters": [ "...fields" ],
  "requestBody": [ "...fields" ],
  "responses": [{ "statuses": ["201"], "fields": [ "...fields" ] }],
  "examples": {
    "local": { "curl": "...", "go": "...", "nodejs": "...", "python": "...", "ansible": "..." },
    "remote": { "curl": "...", "go": "...", "nodejs": "...", "python": "...", "ansible": "..." }
  },
  "responseSample": "{ ... }",
  "sourceUrl": "https://developer.ui.com/network/v10.1.84/createnetwork"
}
```

#### Guide pages

```json
{
  "h1": "Filtering",
  "type": "guide",
  "content": "Markdown content...",
  "sourceUrl": "https://developer.ui.com/network/v10.1.84/filtering"
}
```

#### Field objects (recursive)

```json
{
  "name": "management",
  "required": true,
  "type": "string",
  "description": null,
  "discriminator": [
    { "value": "UNMANAGED", "selected": true, "schema": [ "...sibling fields" ] },
    { "value": "GATEWAY", "selected": false, "schema": [ "...sibling fields" ] }
  ],
  "children": [ "...child fields for object types" ]
}
```

- `discriminator.schema` contains sibling fields visible when that option is active (not the discriminator field itself)
- Nesting is recursive - discriminators within variants are fully expanded
- `children` captures statically expanded object fields

## Adding a New Application

If Ubiquiti adds a new developer docs application at `developer.ui.com/<app-name>`:

1. Add the app to the `APPS` object in `scrape.mjs` with its path and supported modes
2. Run the scraper: `node scrape.mjs --app <app-name>`
3. Add it to the version-check loop in `.github/workflows/update-docs.yml`
4. The MCP server auto-discovers new app subdirectories under `src/mcp_unifi_applications/docs/` — no server changes needed

## Project Structure

```
mcp-unifi-applications/
├── scrape.mjs          # Playwright scraper (runs in Docker)
├── lib/
│   └── parse.mjs       # Scraper parsing logic, kept out of the browser so it is testable
├── Dockerfile          # Scraper container image
├── package.json        # Scraper dependencies (Playwright), locked in package-lock.json
├── Dockerfile.mcp      # The MCP server as a container image
├── pyproject.toml      # Python project config
├── server.json         # MCP registry manifest
├── CHANGELOG.md        # Keep a Changelog
├── ROADMAP.md          # What is planned, what is not, and why
├── glama.json          # Glama maintainer declaration
├── src/
│   └── mcp_unifi_applications/
│       ├── server.py   # MCP server (Python, stdio transport)
│       └── docs/       # Scraped JSON, shipped with the package
│           ├── network/
│           ├── protect/
│           ├── site-manager/
│           ├── innerspace/
│           ├── mobility/
│           └── carrier-fabric/
├── scripts/
│   └── update_readme_versions.py   # Regenerates the README version table (run on main by CI)
└── tests/
    ├── test_mcp_server.py    # pytest
    └── scrape-parse.test.mjs # node --test
```

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

The table under *Install* in the README is generated from the committed
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
