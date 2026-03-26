# Contributing

Contributions are welcome! Here's how to get started.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/dbussemas/mcp-unifi-applications.git
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
