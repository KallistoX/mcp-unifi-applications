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

/** Primitive type names the docs viewer emits. */
const PRIMITIVE_TYPES = ['string', 'number', 'integer', 'boolean', 'object', 'array'];

/** Split a nullable type the docs viewer renders without a separator.
 *  Ubiquiti's own SchemaViewer emits a single <span>stringnull</span> for
 *  ["string","null"], so there is nothing in the DOM to split on — the join has
 *  to be undone here. 301 fields across the corpus are affected. */
export function normalizeType(type) {
  if (typeof type !== 'string') return type;
  const t = type.trim();
  for (const prim of PRIMITIVE_TYPES) {
    if (t === prim + 'null') return `${prim} | null`;
  }
  return t;
}

/** Apply normalizeType across a parsed schema tree, in place. */
export function normalizeSchemaTypes(fields) {
  for (const f of fields || []) {
    if (f && typeof f === 'object') {
      if ('type' in f) f.type = normalizeType(f.type);
      normalizeSchemaTypes(f.children);
      for (const disc of f.discriminator || []) normalizeSchemaTypes(disc.schema);
    }
  }
  return fields;
}

/** Separate a radio group's allowed values from the variants that add structure.
 *
 *  The docs viewer renders enums and discriminated unions in the same
 *  SchemaViewer__RadioGroup, and the common real shape is a mixture: protocol.name
 *  offers 48 values of which only ICMP carries an extra field. Storing all 48 as
 *  variants makes the server print 47 bracketed labels with nothing under them,
 *  which reads as variants whose contents went missing.
 *
 *  So: list every option in `enum`, and keep as variants only those that actually
 *  reveal fields. A group where none do loses its discriminator entirely; a group
 *  where all do is left alone, since the values are already evident.
 *
 *  Must run after enrichSchema has filled the variant schemas - before that every
 *  schema is null and this would flatten real unions.
 */
export function collapseEnums(fields) {
  for (const f of fields || []) {
    if (!f || typeof f !== 'object') continue;
    const disc = f.discriminator;
    if (Array.isArray(disc) && disc.length > 0) {
      const structural = disc.filter(d => d.schema && d.schema.length);
      if (structural.length < disc.length) {
        f.enum = disc.map(d => d.value);
        if (structural.length) f.discriminator = structural;
        else delete f.discriminator;
      }
      for (const d of f.discriminator || []) collapseEnums(d.schema);
    }
    collapseEnums(f.children);
  }
  return fields;
}
