// scrape.mjs — UniFi API docs scraper
// Usage: node scrape.mjs [options] [slug...]
//   --version <ver>   API version to scrape (e.g. v10.1.84). Default: latest.
//   --list-versions   Print available versions and exit.
//   --force           Re-scrape even if output file exists.
//   [slug...]         Scrape only these pages (e.g. createnetwork filtering).
//                     Omit to scrape all pages.

import { chromium } from 'playwright';
import { writeFileSync, mkdirSync, existsSync } from 'fs';

const SITE = 'https://developer.ui.com';
const OUTPUT = '/output';
const RETRY_LIMIT = 3;
const NAV_TIMEOUT = 20000;

// --- CLI argument parsing ---

const args = process.argv.slice(2);
let requestedVersion = null;
let listVersions = false;
let force = false;
const slugs = [];

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--version' && args[i + 1]) { requestedVersion = args[++i]; continue; }
  if (args[i] === '--list-versions') { listVersions = true; continue; }
  if (args[i] === '--force') { force = true; continue; }
  if (args[i].startsWith('--')) { console.error(`Unknown option: ${args[i]}`); process.exit(1); }
  slugs.push(args[i]);
}

const singleMode = slugs.length > 0;

async function injectParser(page) {
  await page.addInitScript(() => {
    window.__parseSchema = function(container) {
      if (!container) return [];
      const rows = Array.from(container.querySelectorAll('[class*="SchemaViewer__PropertyRow"]'));
      const getDepth = (row) => {
        let depth = 0, el = row.parentElement;
        while (el && el !== container) {
          if (el.className?.includes('SchemaViewer__ChildrenContainer')) depth++;
          el = el.parentElement;
        }
        return depth;
      };
      const flat = rows.map(row => {
        const name = row.querySelector('[class*="SchemaViewer__PropertyName"]')?.innerText.trim();
        if (!name) return null;
        const required = !!row.querySelector('[class*="SchemaViewer__RequiredBadge"]');
        const type = row.querySelector('[class*="SchemaViewer__PropertyType"]')?.innerText.trim() || null;
        const description = row.querySelector('[class*="SchemaViewer__PropertyDescription"]')?.innerText.trim() || null;
        const radioGroup = row.querySelector('[class*="SchemaViewer__RadioGroup"]');
        const discriminator = radioGroup
          ? Array.from(radioGroup.querySelectorAll('label')).map(l => ({
              value: l.innerText.trim(),
              selected: l.getAttribute('data-ui-selected') === 'true',
              schema: null,
            }))
          : null;
        return { name, depth: getDepth(row), required, type, description, discriminator, children: [] };
      }).filter(Boolean);
      const root = [], stack = [{ depth: -1, children: root }];
      for (const item of flat) {
        while (stack.length > 1 && stack[stack.length - 1].depth >= item.depth) stack.pop();
        const node = { ...item }; delete node.depth;
        stack[stack.length - 1].children.push(node);
        stack.push({ depth: item.depth, children: node.children });
      }
      return root;
    };

    window.__parseSection = function(headerText) {
      const header = Array.from(document.querySelectorAll('[class*="RequestSection__SchemaHeader"]'))
        .find(el => el.innerText.trim().toLowerCase() === headerText.toLowerCase());
      const tree = header?.nextElementSibling?.querySelector('[class*="SchemaViewer__SchemaTree"]');
      return tree ? window.__parseSchema(tree) : [];
    };

    window.__getContainer = function(sectionEl, parentFieldName) {
      if (!parentFieldName) {
        return sectionEl?.querySelector('[class*="SchemaViewer__SchemaTree"]') || null;
      }
      const rows = Array.from(sectionEl.querySelectorAll('[class*="SchemaViewer__PropertyRow"]'));
      for (const row of rows) {
        if (row.querySelector('[class*="SchemaViewer__PropertyName"]')?.innerText.trim() !== parentFieldName) continue;
        let sib = row.nextElementSibling;
        while (sib) {
          if (sib.className?.includes('SchemaViewer__ChildrenContainer')) return sib;
          if (sib.className?.includes('SchemaViewer__PropertyRow')) break;
          sib = sib.nextElementSibling;
        }
      }
      return null;
    };

    window.__parseSiblings = function(headerText, fieldName, parentFieldName) {
      const header = Array.from(document.querySelectorAll('[class*="RequestSection__SchemaHeader"]'))
        .find(el => el.innerText.trim().toLowerCase() === headerText.toLowerCase());
      const sectionEl = header?.nextElementSibling;
      if (!sectionEl) return [];
      const container = window.__getContainer(sectionEl, parentFieldName);
      if (!container) return [];
      return window.__parseSchema(container);
    };

    window.__clickOption = function(headerText, fieldName, optionValue, parentFieldName) {
      const header = Array.from(document.querySelectorAll('[class*="RequestSection__SchemaHeader"]'))
        .find(el => el.innerText.trim().toLowerCase() === headerText.toLowerCase());
      const sectionEl = header?.nextElementSibling;
      if (!sectionEl) return;
      const container = window.__getContainer(sectionEl, parentFieldName);
      if (!container) return;
      const rows = Array.from(container.querySelectorAll('[class*="SchemaViewer__PropertyRow"]'));
      const fieldRow = rows.find(r => {
        if (r.parentElement !== container) return false;
        return r.querySelector('[class*="SchemaViewer__PropertyName"]')?.innerText.trim() === fieldName;
      }) || rows.find(r =>
        r.querySelector('[class*="SchemaViewer__PropertyName"]')?.innerText.trim() === fieldName &&
        r.querySelector('[class*="SchemaViewer__RadioGroup"]')
      );
      Array.from(fieldRow?.querySelectorAll('label') || [])
        .find(l => l.innerText.trim() === optionValue)?.click();
    };
  });
}

async function expandAll(page) {
  let round = 0;
  while (round < 20) {
    const expanders = await page.$$('[class*="SchemaViewer__ExpandButton"]');
    const toClick = [];
    for (const el of expanders) {
      if (!await el.isVisible()) continue;
      if ((await el.innerText()).trim() === 'Expand') toClick.push(el);
    }
    if (toClick.length === 0) break;
    round++;
    for (const el of toClick) try { await el.click(); } catch (_) {}
    await page.waitForTimeout(400);
  }
}

async function enrichSchema(page, fields, sectionHeaderText, clickPath = [], depth = 0, parentFieldName = null, skipNames = new Set()) {
  if (depth > 8) return fields;

  for (const field of fields) {
    if (skipNames.has(field.name)) continue;

    if (field.children?.length > 0) {
      await enrichSchema(page, field.children, sectionHeaderText, clickPath, depth + 1, field.name, new Set());
    }

    if (!field.discriminator) continue;

    for (const disc of field.discriminator) {
      if (clickPath.length > 0) {
        for (const cp of clickPath) {
          await page.evaluate((cp) => window.__clickOption(cp.headerText, cp.fieldName, cp.option, cp.parentFieldName), cp);
          await page.waitForTimeout(200);
        }
        await expandAll(page);
      }

      await page.evaluate(({ headerText, fieldName, option, parentFieldName }) =>
        window.__clickOption(headerText, fieldName, option, parentFieldName),
        { headerText: sectionHeaderText, fieldName: field.name, option: disc.value, parentFieldName });
      await page.waitForTimeout(500);
      await expandAll(page);

      const siblings = await page.evaluate(({ headerText, fieldName, parentFieldName }) =>
        window.__parseSiblings(headerText, fieldName, parentFieldName),
        { headerText: sectionHeaderText, fieldName: field.name, parentFieldName });

      const newClickPath = [...clickPath, { headerText: sectionHeaderText, fieldName: field.name, option: disc.value, parentFieldName }];
      const newSkipNames = new Set([...skipNames, field.name]);
      await enrichSchema(page, siblings, sectionHeaderText, newClickPath, depth + 1, parentFieldName, newSkipNames);

      disc.schema = siblings.filter(s => s.name !== field.name);
    }

    if (field.discriminator[0]) {
      await page.evaluate(({ headerText, fieldName, option, parentFieldName }) =>
        window.__clickOption(headerText, fieldName, option, parentFieldName),
        { headerText: sectionHeaderText, fieldName: field.name, option: field.discriminator[0].value, parentFieldName });
      await page.waitForTimeout(300);
      await expandAll(page);
    }
  }

  return fields;
}

async function navigateWithRetry(page, url) {
  for (let i = 0; i <= RETRY_LIMIT; i++) {
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
      await page.waitForSelector('h1', { timeout: 10000 });
      await page.waitForTimeout(800);
      return true;
    } catch (e) {
      if (i === RETRY_LIMIT) { console.warn(`  ✗ Gave up: ${e.message}`); return false; }
      console.warn(`  ↺ Retry ${i + 1}/${RETRY_LIMIT}...`);
      await page.waitForTimeout(1000 * (i + 1));
    }
  }
}

// --- Guide page parser (MDX content -> markdown) ---

async function scrapeGuidePage(page, url) {
  const content = await page.evaluate(() => {
    const h1 = Array.from(document.querySelectorAll('h1')).map(el => el.innerText.trim()).find(t => t !== 'Developer') || null;
    const mdx = document.querySelector('[class*="MDXRenderer"]');
    if (!mdx) return null;

    function nodeToMarkdown(el) {
      const lines = [];
      for (const child of el.childNodes) {
        if (child.nodeType === Node.TEXT_NODE) {
          const t = child.textContent;
          if (t.trim()) lines.push(t);
          continue;
        }
        if (child.nodeType !== Node.ELEMENT_NODE) continue;
        const tag = child.tagName.toLowerCase();
        if (tag === 'h2') lines.push(`\n## ${child.innerText.trim()}\n`);
        else if (tag === 'h3') lines.push(`\n### ${child.innerText.trim()}\n`);
        else if (tag === 'h4') lines.push(`\n#### ${child.innerText.trim()}\n`);
        else if (tag === 'p') lines.push(`${inlineText(child)}\n`);
        else if (tag === 'ul') {
          for (const li of child.querySelectorAll(':scope > li'))
            lines.push(`- ${inlineText(li)}`);
          lines.push('');
        }
        else if (tag === 'ol') {
          let i = 1;
          for (const li of child.querySelectorAll(':scope > li'))
            lines.push(`${i++}. ${inlineText(li)}`);
          lines.push('');
        }
        else if (tag === 'pre') lines.push(`\`\`\`\n${child.innerText.trim()}\n\`\`\`\n`);
        else if (tag === 'table') {
          const rows = Array.from(child.querySelectorAll('tr'));
          if (rows.length === 0) continue;
          const headerCells = Array.from(rows[0].querySelectorAll('th, td'));
          lines.push('| ' + headerCells.map(c => inlineText(c)).join(' | ') + ' |');
          lines.push('| ' + headerCells.map(() => '---').join(' | ') + ' |');
          for (const row of rows.slice(1)) {
            const cells = Array.from(row.querySelectorAll('td'));
            lines.push('| ' + cells.map(c => inlineText(c)).join(' | ') + ' |');
          }
          lines.push('');
        }
        else {
          // Recurse into unknown containers (divs, etc.)
          const inner = nodeToMarkdown(child);
          if (inner) lines.push(inner);
        }
      }
      return lines.join('\n');
    }

    function inlineText(el) {
      let out = '';
      for (const child of el.childNodes) {
        if (child.nodeType === Node.TEXT_NODE) { out += child.textContent; continue; }
        if (child.nodeType !== Node.ELEMENT_NODE) continue;
        const tag = child.tagName.toLowerCase();
        if (tag === 'code') out += '`' + child.innerText + '`';
        else if (tag === 'strong' || tag === 'b') out += '**' + child.innerText + '**';
        else if (tag === 'em' || tag === 'i') out += '*' + child.innerText + '*';
        else if (tag === 'a') out += `[${child.innerText}](${child.href})`;
        else out += child.innerText;
      }
      return out.trim();
    }

    return { h1, markdown: nodeToMarkdown(mdx) };
  });

  if (!content) return null;
  return {
    h1: content.h1,
    type: 'guide',
    content: content.markdown,
    sourceUrl: url,
  };
}

// --- Code example scraper (all languages, local + remote) ---

const LANGUAGES = [
  { label: 'cURL', aria: 'Switch to cURL', key: 'curl' },
  { label: 'Go', aria: 'Switch to Go', key: 'go' },
  { label: 'Node.js', aria: 'Switch to Node.js', key: 'nodejs' },
  { label: 'Python', aria: 'Switch to Python', key: 'python' },
  { label: 'Ansible', aria: 'Switch to Ansible', key: 'ansible' },
];

const MODES = [
  { label: 'Local', key: 'local' },
  { label: 'Remote', key: 'remote' },
];

async function scrapeExamples(page) {
  const examples = {};
  const responseSample = await page.evaluate(() => {
    const visible = Array.from(document.querySelectorAll('pre')).filter(el => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && el.innerText.trim().length > 0;
    });
    return visible.find(el => el.innerText.trim().startsWith('{'))?.innerText.trim() || null;
  });

  for (const mode of MODES) {
    try {
      await page.click(`label:has-text("${mode.label}")`, { timeout: 2000 });
      await page.waitForTimeout(400);
    } catch (_) { continue; }

    examples[mode.key] = {};
    for (const lang of LANGUAGES) {
      try {
        await page.click(`[aria-label="${lang.aria}"]`, { timeout: 2000 });
        await page.waitForTimeout(400);
      } catch (_) { continue; }

      const code = await page.evaluate(() => {
        const visible = Array.from(document.querySelectorAll('pre')).filter(el => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0 && el.innerText.trim().length > 0;
        });
        // The request example is typically the first visible pre that isn't a JSON response
        return (visible.find(el => !el.innerText.trim().startsWith('{')) ?? visible[0])?.innerText.trim() || null;
      });
      if (code) examples[mode.key][lang.key] = code;
    }
  }

  // If only one mode worked, still return what we got
  return { examples: Object.keys(examples).length > 0 ? examples : null, responseSample };
}

// --- Main page scraper ---

async function scrapePage(page, url) {
  await injectParser(page);
  const ok = await navigateWithRetry(page, url);
  if (!ok) return null;

  // Detect guide pages (no HTTP method badge)
  const isGuide = await page.evaluate(() => !document.querySelector('[class*="HttpMethod"], [class*="MethodBadge"]'));
  if (isGuide) return scrapeGuidePage(page, url);

  // Click Local first for initial schema parse
  try { await page.click('label:has-text("Local")', { timeout: 3000 }); await page.waitForTimeout(400); } catch (_) {}
  await expandAll(page);

  const base = await page.evaluate(() => {
    const h1 = Array.from(document.querySelectorAll('h1')).map(el => el.innerText.trim()).find(t => t !== 'Developer') || null;
    const methodEl = document.querySelector('[class*="HttpMethod"], [class*="MethodBadge"]');
    const method = methodEl?.innerText.trim() || null;
    const path = methodEl?.nextElementSibling?.innerText.trim() || null;
    const innerContent = document.querySelector('[class*="parts__InnerContent"]');
    const descEl = innerContent ? Array.from(innerContent.querySelectorAll('p')).find(p => !p.innerText.includes('Ansible') && p.innerText.trim().length > 0) : null;
    const description = descEl?.innerText.trim() || null;
    const pathParameters = window.__parseSection('path Parameters');
    const queryParameters = window.__parseSection('query Parameters');
    const requestBody = window.__parseSection('request Body');
    const responseSection = document.querySelector('[class*="ResponseSection__Section"]');
    const responses = responseSection ? [{
      statuses: Array.from(responseSection.querySelectorAll('[class*="ResponseSection__TabsContainer"] button')).map(b => b.innerText.trim()),
      fields: (() => { const t = responseSection.querySelector('[class*="SchemaViewer__SchemaTree"]'); return t ? window.__parseSchema(t) : []; })(),
    }] : [];
    return { h1, method, path, description, pathParameters, queryParameters, requestBody, responses };
  });

  base.requestBody = await enrichSchema(page, base.requestBody, 'request Body');

  const { examples, responseSample } = await scrapeExamples(page);

  return { ...base, examples, responseSample, sourceUrl: url };
}

// --- Version discovery ---

async function discoverVersions(page) {
  await page.goto(`${SITE}/network`, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
  await page.waitForTimeout(800);
  // Open the version dropdown
  try {
    const versionBtn = await page.$('[class*="VersionSelect"], [class*="version-select"], select');
    if (versionBtn) await versionBtn.click();
    await page.waitForTimeout(500);
  } catch (_) {}
  // Extract versions from the dropdown list items
  const versions = await page.evaluate(() => {
    const items = Array.from(document.querySelectorAll('[data-ui-portal-container] li'));
    if (items.length > 0) {
      return items.map(li => ({
        version: li.innerText.trim().replace(/^v/, ''),
        selected: li.getAttribute('data-ui-selected') === 'true',
      }));
    }
    // Fallback: look for version in URL or nav links
    const links = Array.from(document.querySelectorAll('a[href*="/network/v"]'));
    const seen = new Set();
    return links.map(a => {
      const m = a.href.match(/\/network\/v([\d.]+)/);
      if (!m || seen.has(m[1])) return null;
      seen.add(m[1]);
      return { version: m[1], selected: false };
    }).filter(Boolean);
  });
  // Close dropdown by pressing Escape
  try { await page.keyboard.press('Escape'); } catch (_) {}
  return versions;
}

// --- Main ---

const browser = await chromium.launch({ args: ['--no-sandbox'] });
const page = await browser.newPage();

// Discover available versions
console.log('Discovering API versions...');
const versions = await discoverVersions(page);

if (versions.length === 0) {
  console.error('Could not discover any API versions.');
  await browser.close();
  process.exit(1);
}

if (listVersions) {
  console.log('\nAvailable versions:');
  for (const v of versions) console.log(`  ${v.selected ? '* ' : '  '}v${v.version}`);
  await browser.close();
  process.exit(0);
}

// Resolve version
const latestVersion = versions.find(v => v.selected)?.version || versions[0].version;
const version = requestedVersion?.replace(/^v/, '') || latestVersion;
const validVersion = versions.find(v => v.version === version);
if (!validVersion) {
  console.error(`Version v${version} not found. Available: ${versions.map(v => 'v' + v.version).join(', ')}`);
  await browser.close();
  process.exit(1);
}

const BASE = `${SITE}/network/v${version}`;
console.log(`Using API version: v${version}\n`);

// Discover nav links
console.log('Discovering nav links...');
await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
await page.waitForTimeout(800);

let links = await page.$$eval('a[href]', els =>
  [...new Map(
    els.map(el => ({ href: el.getAttribute('href'), text: el.innerText.trim() }))
      .filter(l => l.href && l.href.includes('/network') && l.text)
      .map(l => [l.href, l])
  ).values()]
);

// Filter to requested slugs if in single mode
if (singleMode) {
  const slugSet = new Set(slugs);
  links = links.filter(l => slugSet.has(l.href.split('/').pop()));
  const found = new Set(links.map(l => l.href.split('/').pop()));
  for (const s of slugs) {
    if (!found.has(s)) {
      console.warn(`  ⚠ Slug '${s}' not found in nav, will try direct URL`);
      links.push({ href: `/network/v${version}/${s}`, text: s });
    }
  }
}

console.log(`${singleMode ? 'Selected' : 'Found'} ${links.length} pages\n`);
mkdirSync(OUTPUT, { recursive: true });

const failed = [];
let done = 0;

for (const { href, text } of links) {
  const url = href.startsWith('http') ? href : `${SITE}${href}`;
  const slug = href.split('/').pop() || href.replace(/\//g, '_');
  const outPath = `${OUTPUT}/${slug}.json`;

  if (!force && existsSync(outPath)) { console.log(`  ⟳ Skip: ${text}`); done++; continue; }

  process.stdout.write(`[${++done}/${links.length}] ${text}... `);
  const data = await scrapePage(page, url);
  if (!data) {
    failed.push({ url, text });
    writeFileSync(outPath, JSON.stringify({ error: 'Failed to scrape', sourceUrl: url }, null, 2));
    console.log('✗');
    continue;
  }
  writeFileSync(outPath, JSON.stringify(data, null, 2));
  console.log('✓');

  if (singleMode) {
    console.log(JSON.stringify(data, null, 2));
  }
}

const index = links.map(({ href, text }) => ({ slug: href.split('/').pop(), title: text, file: `${href.split('/').pop()}.json` }));
writeFileSync(`${OUTPUT}/_index.json`, JSON.stringify(index, null, 2));

if (failed.length) {
  console.log(`\n✗ Failed (${failed.length}):`);
  failed.forEach(f => console.log(`  - ${f.text}: ${f.url}`));
  writeFileSync(`${OUTPUT}/_failed.txt`, failed.map(f => `${f.text}\t${f.url}`).join('\n'));
}

console.log(`\nDone. ${done} pages (v${version}).`);
await browser.close();
