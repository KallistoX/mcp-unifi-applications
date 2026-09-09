// Pure parsing helpers for scrape.mjs.
//
// These used to live inside page.evaluate/$$eval callbacks, which Playwright
// serialises into the browser — code that cannot be imported, and therefore
// cannot be tested. Both scraper bugs that reached production were in here:
// an Early Access version label ("v1.3.23 (EA)") interpolated straight into a
// URL, and a substring nav filter that matched an external host. The browser
// side now only reads the DOM; every decision is made here.

/** Extract the bare semver from a version dropdown label.
 *  Labels are not bare versions: Early Access apps read "v1.3.23 (EA)".
 *  Returns null when the label carries no version at all. */
export function parseVersionLabel(label) {
  if (typeof label !== 'string') return null;
  const m = label.match(/v?(\d+(?:\.\d+)*)/);
  return m ? m[1] : null;
}

/** Build the version list from raw dropdown items ({ label, selected }).
 *  Keeps the full label for display; entries without a version are dropped. */
export function buildVersionsFromItems(items) {
  return (items || [])
    .map(({ label, selected }) => {
      const version = parseVersionLabel(label);
      return version ? { version, label, selected: Boolean(selected) } : null;
    })
    .filter(Boolean);
}

/** Fallback when no dropdown is present: recover versions from nav hrefs. */
export function buildVersionsFromHrefs(hrefs, appPath) {
  const re = new RegExp(`/${appPath.replace(/[.*+?^${}()|[\]\\-]/g, '\\$&')}/v([\\d.]+)`);
  const seen = new Set();
  const out = [];
  for (const href of hrefs || []) {
    const m = String(href).match(re);
    if (!m || seen.has(m[1])) continue;
    seen.add(m[1]);
    out.push({ version: m[1], selected: false });
  }
  return out;
}

/** Pick the version to scrape. Returns { version } or { error }. */
export function resolveVersion(versions, requestedVersion) {
  if (!versions || versions.length === 0) return { error: 'Could not discover any API versions.' };
  const latest = versions.find(v => v.selected)?.version || versions[0].version;
  const version = requestedVersion ? String(requestedVersion).replace(/^v/, '') : latest;
  if (!versions.some(v => v.version === version)) {
    return { error: `Version v${version} not found. Available: ${versions.map(v => 'v' + v.version).join(', ')}` };
  }
  return { version };
}

/** Select the doc pages from every anchor on the page, de-duplicated by href.
 *  Internal nav links are relative and version-scoped; matching on a bare
 *  `/${appPath}` substring also catches https://mobility.ui.com/api-keys,
 *  because "//mobility" contains "/mobility". Raw files are not doc pages. */
export function selectNavLinks(links, appPath) {
  const prefix = `/${appPath}/v`;
  return [...new Map(
    (links || [])
      .filter(l => l && typeof l.href === 'string' && l.href.startsWith(prefix)
        && l.text && !l.href.endsWith('.json'))
      .map(l => [l.href, { href: l.href, text: l.text }])
  ).values()];
}

/** Last path segment of a docs URL: '/network/v10.4.57/createnetwork' -> 'createnetwork'. */
export function slugFromHref(href) {
  const s = String(href ?? '');
  return s.split('/').pop() || s.replace(/\//g, '_');
}
