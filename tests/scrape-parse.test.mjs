// Tests for the pure parsing helpers extracted from scrape.mjs.
// Every case below that names a real app is a regression: both scraper bugs that
// reached production lived in code that page.evaluate hid from any test runner.

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  buildVersionsFromHrefs,
  buildVersionsFromItems,
  normalizeSchemaTypes,
  normalizeType,
  parseVersionLabel,
  resolveVersion,
  selectNavLinks,
  slugFromHref,
} from '../lib/parse.mjs';

describe('parseVersionLabel', () => {
  it('strips an Early Access suffix', () => {
    // The bug: "1.3.23 (EA)" went straight into the docs URL, which then 404ed
    // and yielded a zero-page scrape.
    assert.equal(parseVersionLabel('v1.3.23 (EA)'), '1.3.23');
    assert.equal(parseVersionLabel('v0.9.7 (EA)'), '0.9.7');
  });

  it('handles the plain labels of the other apps', () => {
    assert.equal(parseVersionLabel('v10.4.57'), '10.4.57');
    assert.equal(parseVersionLabel('v7.3.47'), '7.3.47');
    assert.equal(parseVersionLabel('v1.0.0'), '1.0.0');
    assert.equal(parseVersionLabel('1.0.0'), '1.0.0');
  });

  it('accepts partial versions and other suffixes', () => {
    assert.equal(parseVersionLabel('v9 (legacy)'), '9');
    assert.equal(parseVersionLabel('v2.1'), '2.1');
  });

  it('returns null when there is no version', () => {
    assert.equal(parseVersionLabel('Beta'), null);
    assert.equal(parseVersionLabel(''), null);
    assert.equal(parseVersionLabel(undefined), null);
    assert.equal(parseVersionLabel(null), null);
  });
});

describe('buildVersionsFromItems', () => {
  it('keeps the label and the selected flag', () => {
    const out = buildVersionsFromItems([
      { label: 'v1.3.23 (EA)', selected: true },
      { label: 'v0.9.7 (EA)', selected: false },
    ]);
    assert.deepEqual(out, [
      { version: '1.3.23', label: 'v1.3.23 (EA)', selected: true },
      { version: '0.9.7', label: 'v0.9.7 (EA)', selected: false },
    ]);
  });

  it('drops entries that carry no version instead of emitting a bogus one', () => {
    const out = buildVersionsFromItems([{ label: 'Choose a version' }, { label: 'v1.0.0' }]);
    assert.deepEqual(out.map(v => v.version), ['1.0.0']);
  });

  it('coerces a missing selected flag to false', () => {
    assert.equal(buildVersionsFromItems([{ label: 'v1.0.0' }])[0].selected, false);
  });

  it('tolerates an empty or missing list', () => {
    assert.deepEqual(buildVersionsFromItems([]), []);
    assert.deepEqual(buildVersionsFromItems(undefined), []);
  });
});

describe('buildVersionsFromHrefs', () => {
  it('recovers versions from nav hrefs and de-duplicates', () => {
    const out = buildVersionsFromHrefs([
      'https://developer.ui.com/network/v10.4.57/createnetwork',
      'https://developer.ui.com/network/v10.4.57/listnetworks',
      'https://developer.ui.com/network/v9.5.21/createnetwork',
    ], 'network');
    assert.deepEqual(out.map(v => v.version), ['10.4.57', '9.5.21']);
  });

  it('handles hyphenated app paths', () => {
    // 'carrier-fabric' and 'site-manager' must not be read as regex ranges.
    for (const app of ['carrier-fabric', 'site-manager']) {
      const out = buildVersionsFromHrefs([`https://developer.ui.com/${app}/v1.0.0/getting-started`], app);
      assert.deepEqual(out.map(v => v.version), ['1.0.0'], app);
    }
  });

  it('ignores hrefs for a different app', () => {
    assert.deepEqual(buildVersionsFromHrefs(['/protect/v7.3.47/x'], 'network'), []);
  });
});

describe('resolveVersion', () => {
  const versions = [
    { version: '1.3.23', selected: true },
    { version: '0.9.7', selected: false },
  ];

  it('prefers the selected version', () => {
    assert.deepEqual(resolveVersion(versions, null), { version: '1.3.23' });
  });

  it('falls back to the first entry when nothing is selected', () => {
    assert.deepEqual(resolveVersion([{ version: '2.0.0' }, { version: '1.0.0' }], null), { version: '2.0.0' });
  });

  it('accepts an explicit version with or without the v prefix', () => {
    assert.deepEqual(resolveVersion(versions, 'v0.9.7'), { version: '0.9.7' });
    assert.deepEqual(resolveVersion(versions, '0.9.7'), { version: '0.9.7' });
  });

  it('reports an unknown version instead of scraping a 404', () => {
    const { error } = resolveVersion(versions, 'v9.9.9');
    assert.match(error, /v9\.9\.9 not found/);
    assert.match(error, /v1\.3\.23, v0\.9\.7/);
  });

  it('reports an empty version list', () => {
    assert.match(resolveVersion([], null).error, /Could not discover/);
    assert.match(resolveVersion(undefined, null).error, /Could not discover/);
  });
});

describe('selectNavLinks', () => {
  it('excludes links to another host', () => {
    // The bug: Mobility's sidebar links to https://mobility.ui.com/api-keys, and
    // "//mobility" contains "/mobility", so a substring match counted it as a page.
    const out = selectNavLinks([
      { href: '/mobility/v1.0.0/listdevices', text: 'List devices' },
      { href: 'https://mobility.ui.com/api-keys', text: 'mobility.ui.com/api-keys' },
    ], 'mobility');
    assert.deepEqual(out.map(l => l.href), ['/mobility/v1.0.0/listdevices']);
  });

  it('excludes raw files', () => {
    const out = selectNavLinks([
      { href: '/mobility/v1.0.0/openapi.json', text: 'OpenAPI' },
      { href: '/mobility/v1.0.0/postman-collection.json', text: 'Postman' },
      { href: '/mobility/v1.0.0/getdevice', text: 'Get device detail' },
    ], 'mobility');
    assert.deepEqual(out.map(l => l.href), ['/mobility/v1.0.0/getdevice']);
  });

  it('requires a version segment, so app-level links do not qualify', () => {
    const out = selectNavLinks([
      { href: '/network', text: 'Network' },
      { href: '/network/v10.4.57/createnetwork', text: 'Create Network' },
    ], 'network');
    assert.deepEqual(out.map(l => l.href), ['/network/v10.4.57/createnetwork']);
  });

  it('does not confuse one app for another', () => {
    const out = selectNavLinks([{ href: '/protect/v7.3.47/x', text: 'X' }], 'network');
    assert.deepEqual(out, []);
  });

  it('de-duplicates by href, keeping the last occurrence', () => {
    // Map-based dedupe: a later entry overwrites an earlier one. Documented
    // rather than changed - this is what produced the committed titles in
    // _index.json, and flipping it would rewrite them on the next scrape.
    const out = selectNavLinks([
      { href: '/network/v10.4.57/createnetwork', text: 'Create Network' },
      { href: '/network/v10.4.57/createnetwork', text: 'Create Network (sidebar)' },
    ], 'network');
    assert.equal(out.length, 1);
    assert.equal(out[0].text, 'Create Network (sidebar)');
  });

  it('skips links without text and malformed entries', () => {
    const out = selectNavLinks([
      { href: '/network/v10.4.57/a', text: '' },
      { href: null, text: 'x' },
      null,
      { href: '/network/v10.4.57/b', text: 'B' },
    ], 'network');
    assert.deepEqual(out.map(l => l.href), ['/network/v10.4.57/b']);
  });

  it('tolerates an empty or missing list', () => {
    assert.deepEqual(selectNavLinks([], 'network'), []);
    assert.deepEqual(selectNavLinks(undefined, 'network'), []);
  });
});

describe('slugFromHref', () => {
  it('takes the last path segment', () => {
    assert.equal(slugFromHref('/network/v10.4.57/createnetwork'), 'createnetwork');
    assert.equal(slugFromHref('/mobility/v1.0.0/getting-started'), 'getting-started');
    assert.equal(slugFromHref('/innerspace/v1.3.23/get-v1access_points'), 'get-v1access_points');
  });

  it('falls back for a href with no usable last segment', () => {
    assert.equal(slugFromHref('/'), '_');
    assert.equal(slugFromHref(''), '');
  });
});

describe('normalizeType', () => {
  it('splits every nullable form the corpus contains', () => {
    // 301 fields across 47 endpoints, all six primitives.
    assert.equal(normalizeType('stringnull'), 'string | null');
    assert.equal(normalizeType('numbernull'), 'number | null');
    assert.equal(normalizeType('objectnull'), 'object | null');
    assert.equal(normalizeType('integernull'), 'integer | null');
    assert.equal(normalizeType('arraynull'), 'array | null');
    assert.equal(normalizeType('booleannull'), 'boolean | null');
  });

  it('leaves plain and composite types alone', () => {
    for (const t of ['string', 'object', 'Array of string', 'Array of object (Port matching)']) {
      assert.equal(normalizeType(t), t);
    }
  });

  it('does not split a type that merely ends in those letters', () => {
    assert.equal(normalizeType('nullable'), 'nullable');
    assert.equal(normalizeType('null'), 'null');
  });

  it('passes through non-strings', () => {
    assert.equal(normalizeType(null), null);
    assert.equal(normalizeType(undefined), undefined);
  });
});

describe('normalizeSchemaTypes', () => {
  it('walks children and discriminator variants', () => {
    const tree = [{
      name: 'a',
      type: 'stringnull',
      children: [{ name: 'b', type: 'numbernull', children: [] }],
      discriminator: [{ value: 'X', schema: [{ name: 'c', type: 'booleannull', children: [] }] }],
    }];
    normalizeSchemaTypes(tree);
    assert.equal(tree[0].type, 'string | null');
    assert.equal(tree[0].children[0].type, 'number | null');
    assert.equal(tree[0].discriminator[0].schema[0].type, 'boolean | null');
  });

  it('tolerates missing branches', () => {
    assert.deepEqual(normalizeSchemaTypes(undefined), undefined);
    assert.deepEqual(normalizeSchemaTypes([{ name: 'a' }]), [{ name: 'a' }]);
  });
});
