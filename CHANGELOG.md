# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

### Added

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

[Unreleased]: https://github.com/KallistoX/mcp-unifi-applications/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/KallistoX/mcp-unifi-applications/releases/tag/v0.2.0
[0.1.0]: https://github.com/KallistoX/mcp-unifi-applications/releases/tag/v0.1.0
