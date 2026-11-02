# The Playwright scraper. (Dockerfile.mcp builds the MCP server itself.)
# Keep this tag equal to the playwright version in package.json: the image ships
# the browsers for exactly that release.
FROM mcr.microsoft.com/playwright:v1.64.1-noble

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
# A no-op while the tag above matches package.json. When an update moves only
# one of the two, this fetches the browser the installed playwright expects
# instead of letting the scrape die on a missing executable.
RUN npx playwright install chromium

COPY *.mjs .
# scrape.mjs imports ./lib/parse.mjs — a bare `COPY *.mjs` leaves it out
# and the container dies on the import.
COPY lib/ ./lib/
