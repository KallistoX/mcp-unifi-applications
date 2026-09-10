# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Every tool now carries MCP annotations — `readOnlyHint`, `destructiveHint: false`,
  `idempotentHint`, `openWorldHint: false`. All ten read bundled JSON and nothing
  else: no network, no credentials, no writes. A client had no way to know that
  without reading prose.
- Tool descriptions rewritten to say what comes back, how large it tends to be, and
  what happens when a lookup fails, rather than only what the tool is for. Glama's
  tool-definition scoring put the server at an average of 3.8/5 with behavioural
  transparency the weakest dimension across all ten tools, and its server-level
  score weights the worst tool at 40 % — `get_endpoint` sat at 3.2/5 with
  "the description only says 'Get the full schema'". Each description now also
  points at the sibling tool that is a better fit for the neighbouring question.

## [0.3.0] - 2026-09-10

### Fixed

Output that a model reading it would be misled by, found in an acceptance review of
the published 0.2.0 package. No crashes were involved; every item below is a tool
answering a different question than the one asked.

- `find_field` stopped silently at 50 hits. `id` occurs 215 times across 158
  endpoints and returned exactly 50 lines with no indication of a cap, inviting the
  conclusion that an endpoint not listed does not have the field. It now reports the
  total and the number of endpoints, and suggests scoping with `slug=`.
- `find_field` reported "Field 'x' not found in endpoint 'bogus/slug'" for endpoints
  that do not exist, which reads as though the endpoint exists and lacks the field.
  It now rejects the slug the way the other tools do.
- `find_field` returned identical lines for a field present in both the request and
  the response. Each hit now names its schema section.
- `get_guide` matched on the rendered page title rather than the slug, so
  `get_guide("gettingstarted", app="site-manager")` failed while naming
  `site-manager/gettingstarted` as available in the same sentence. Slugs are now
  matched first; three guides were unreachable by slug.
- `get_guide` with no `app` silently returned one arbitrary application's guide when
  several matched. It now lists the candidates and asks.
- `get_guide` now names the application a guide belongs to in its heading.
- `get_guide(app="typo")` answered "No guide pages loaded.", claiming the server has
  none. Unknown applications are now rejected by name, as are unknown methods and
  applications in `list_endpoints` and `search_endpoints`, which returned "no
  endpoints found" — a claim about the corpus rather than about the argument.
- `search_endpoints` returned results for nonsense queries; `zzzzznotathing` matched
  four Protect endpoints. Measured against the corpus, nonsense scores at most 40
  while real queries score at least 162, so the relevance floor moved from 30 to 60.
- Slug suggestions were offered for input nothing resembled — `totallybogusslug`
  suggested `network/getaclrulepage`. Genuine typos score 67–98 against their
  intended slug and nonsense at most 42, so suggestions below 60 are now withheld.
- `get_field_schema` with an empty `field_path` raised `IndexError`, the only
  unhandled exception in the server.
- `get_endpoint_group("")` returned all 581 lines instead of asking for a value.
- `get_example(mode="")` fell through to the default while `mode="remote "` errored.
  Arguments are now stripped consistently.
- `serverInfo.version` reported the FastMCP version instead of the package version.

- Discriminated unions in response schemas were empty everywhere: 892 of 892
  variants across 46 endpoints. Two causes. `enrichSchema` only ever ran against
  the request body, and the option it clicked to reveal a variant was the `<label>`,
  which carries a `for` attribute pointing at an id nothing resolves to — clicking
  it does nothing. Clicking the `input` inside it works. Verified against
  `network/createnetwork`: response variants went from 0/12 to 21/33 populated, the
  remaining twelve being enum values that carry no fields — see the enum entry
  below, which turned out to be the real reason request-body variants also looked
  half populated.
- Where variant fields followed an empty stub they read as siblings of the
  discriminator rather than as members of a variant, so `dhcpServerIpAddresses`
  appeared to be always present rather than `[RELAY]`-only.
- Nullable types rendered as glued tokens — `stringnull`, `numbernull` — in 301
  fields across 47 endpoints. The docs viewer emits a single `<span>stringnull</span>`
  for `["string","null"]`, so the join is undone in the scraper. Verified against
  `protect/get-v1sensorsid`: 20 glued tokens became 20 readable ones.
- Six guides shipped with a null title and displayed their slug instead, because
  those pages render no `<h1>`. The nav link text is used as a fallback.
- Enums were stored as discriminated unions with empty variants. The docs viewer
  renders both in the same radio group, so `protocol.name` — 48 IP protocols of
  which only `ICMP` carries an extra field — became 48 variants, 47 of them with
  nothing inside. The server printed them as bracketed labels with no contents,
  which reads as variants whose fields went missing rather than as the allowed
  values of a string. Options are now listed in `enum` and only those that
  actually reveal fields stay variants, marked as additive. That one field drops
  from 52 rendered lines to 6, without losing a single value. Across `network`,
  222 fields and 2314 values are affected; the 2202 empty variants become enum
  values and all 2977 variants that carry fields are preserved exactly. The other
  five applications have no enums.

### Changed

- The scraper's fixed waits after a click were sized for a network round trip
  that never happens. Measured with a `MutationObserver` against the live docs:
  clicking a discriminator variant or an expand button issues zero requests — the
  page is fetched once and everything after is a client-side re-render — and the
  DOM settles in one mutation batch after 3–5 ms. The 200/300/400/500 ms sleeps
  are now a single 50 ms settle. `expandAll` also checked visibility and text per
  element over the debug protocol, three round trips per expander, twice for every
  variant on the page; it now does one round trip per round. A union-heavy page
  (`network/createnetwork`, 54 variants) drops from 65 s to 18 s, with
  byte-identical output.
- A variant click now waits for the variant to report itself selected rather than
  for a fixed number of milliseconds. The measurement was taken on a developer
  machine; a slower CI runner that exceeded the sleep would have captured a
  half-rendered variant, which fails silently — the same class of bug this
  release fixes elsewhere.

### Added

- `update-docs` accepts a `force_apps` input, so a scraper fix can trigger a
  re-scrape when the upstream version is unchanged but the output is not.
- Bare, unqualified endpoint slugs now resolve when only one application has them —
  179 of 185 do. The tool descriptions documented this form (`createnetwork`) while
  the server rejected it.

## [0.2.0] - 2026-09-09

### Added

- InnerSpace, Mobility and Carrier Fabric, completing coverage of all six
  applications Ubiquiti publishes API documentation for.
- `server.json` for the official MCP registry, with a PyPI package entry.
- Published to PyPI: `pip install mcp-unifi-applications`.

### Fixed

- The built wheel contained no Python module and no documentation. Without
  `[build-system]` or `[tool.setuptools]` configuration, flat-layout auto-discovery
  packaged `screenshots/`; `pip install .` installed only dependencies and the
  console script could not import. Moving to a `src` layout ships the server and all
  222 documentation files, and `scripts/check_wheel.py` guards both in CI.
- The scraper interpolated Early Access version labels (`v1.3.23 (EA)`) into the docs
  URL, producing a zero-page scrape that still exited successfully. Labels are now
  parsed for the bare version, and a run finding no pages fails.
- The scraper's nav filter matched any URL containing `/<app>`, which caught
  Mobility's external link to `mobility.ui.com`. Matching is now version-scoped.
- `get_example` printed the raw `mode` argument, so calls that omitted it — the
  documented default — rendered as `(None)`.

## [0.1.0] - 2026-03-27

### Added

- Initial release: Network, Protect and Site Manager documentation served over stdio
  through ten MCP tools, with a Playwright scraper and a weekly refresh workflow.

[Unreleased]: https://github.com/KallistoX/mcp-unifi-applications/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/KallistoX/mcp-unifi-applications/releases/tag/v0.3.0
[0.2.0]: https://github.com/KallistoX/mcp-unifi-applications/releases/tag/v0.2.0
[0.1.0]: https://github.com/KallistoX/mcp-unifi-applications/releases/tag/v0.1.0
