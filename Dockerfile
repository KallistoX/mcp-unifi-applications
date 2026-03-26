FROM mcr.microsoft.com/playwright:v1.58.2-noble

WORKDIR /app
COPY *.mjs .

RUN npm init -y && npm install node-html-markdown playwright @playwright/browser-chromium