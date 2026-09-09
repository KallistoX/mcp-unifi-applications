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
pytest tests/ -v
```

## Scraper Development

The scraper requires Playwright with Chromium. The easiest way to run it is via Docker:

```bash
docker build -t unifi-scraper .
docker run --rm -v $(pwd)/docs:/output unifi-scraper node scrape.mjs --app network
```

To run locally without Docker, install Playwright and its browser dependencies:

```bash
npm install
npx playwright install chromium
node scrape.mjs --app network
```

Note: when running locally, output goes to `/output` by default (the Docker mount point). Override by editing the `OUTPUT` constant or symlinking.

## Adding a New Application

If Ubiquiti adds a new developer docs application at `developer.ui.com/<app-name>`:

1. Add the app to the `APPS` object in `scrape.mjs` with its path and supported modes
2. Run the scraper: `node scrape.mjs --app <app-name>`
3. The MCP server auto-discovers new app subdirectories — no server changes needed

## Pull Requests

- Keep changes focused — one feature or fix per PR
- Add or update tests for any new functionality
- Run `pytest tests/ -v` and make sure all tests pass before submitting

## Publishing to the MCP Registry

`server.json` is the manifest for the [official MCP registry](https://registry.modelcontextprotocol.io).
Bump its `version` in the same commit as `pyproject.toml`'s, then publish with the
[`mcp-publisher`](https://github.com/modelcontextprotocol/registry/tree/main/cmd/publisher) CLI:

```bash
mcp-publisher login github    # opens a browser; namespace io.github.KallistoX is proven by the login
mcp-publisher publish
```

The manifest currently carries repository metadata only. Once the package is on PyPI, add a
`packages` entry (`registryType: "pypi"`) so clients can install it without cloning.
