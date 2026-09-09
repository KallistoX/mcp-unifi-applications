FROM mcr.microsoft.com/playwright:v1.58.2-noble

WORKDIR /app
COPY *.mjs .
# scrape.mjs imports ./lib/parse.mjs — a bare `COPY *.mjs` leaves it out
# and the container dies on the import.
COPY lib/ ./lib/

RUN npm init -y && npm install node-html-markdown playwright @playwright/browser-chromium