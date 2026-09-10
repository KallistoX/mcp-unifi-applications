# Roadmap

What is planned, what is not, and why. Items are ordered by what they cost the people
using the server, not by how interesting they are to build.

## Near term — findings from the 0.3.1 acceptance review

The published 0.3.1 package was audited black-box by a reviewer with no knowledge of the
implementation ([`docs/acceptance-0.3.1.md`](docs/acceptance-0.3.1.md)). No crashes, no
protocol violations. Five substantive findings, three of them high:

- **`get_endpoint` never renders query parameters.** 42 endpoints have them in the
  shipped data; the summary path emits zero `## Query Parameters` sections. A model
  therefore never learns that list endpoints are paginated, that `filter` exists, or
  that `deletenetwork` takes a `force` flag — while the Filtering guide documents the
  `filter` syntax at length. The tool's own description promises query parameters, so
  the server currently contradicts itself.
- **Search scores a maximum over tokens rather than a conjunction.** `update camera`,
  `update light` and `update banana` return the identical ranking; the discriminating
  token contributes nothing once a common one scores highly. The relevance floor added
  in 0.3.0 catches standalone nonsense but not nonsense paired with a common verb.
- **`create voucher` ranks a DELETE endpoint first** and never surfaces
  `network/createvouchers` in the top ten, because that endpoint is titled *Generate
  Vouchers*. A create intent pointing at a destructive operation deserves its own entry.
- **Response samples are truncated at 58 lines.** A hard cap in the scraper leaves seven
  samples as invalid JSON, presented as "raw JSON exactly as the documentation shows
  it". Needs a scraper change and a re-scrape; the server could also detect unbalanced
  JSON and say so.
- **`get_guide` title lookup bypasses the ambiguity guard.** Slug resolution refuses to
  guess between applications; title resolution silently picks one. Three guides are
  titled `Introduction`, two `Installation`, two `Error Handling`.

Plus the minor observations in the report: empty `## Response [200]` headings that read
like truncation, input casing echoed into headings, a `method` description naming five
of the eight accepted verbs, and `--help` starting the server instead of printing usage.

## Use more than one of MCP's three primitives

The server advertises `tools`, `resources` and `prompts`, and exposes ten tools, zero
resources and zero prompts. That is the largest structural gap, and it predates any
recent specification work.

The 14 guide pages are static addressable documents — exactly what `resources` are for —
reachable today only through a tool call. Endpoint documentation would fit a resource
template such as `unifi://network/createnetwork`, letting a client attach one endpoint's
schema to the context without a model deciding to call a tool first. A small number of
prompts could cover the recurring shapes, such as writing a client for a given endpoint
in a given language.

## Verify coverage against Ubiquiti's own spec

Ubiquiti publishes `developer.ui.com/<app>/v<version>/openapi.json`. Nothing checks the
scrape against it, so a page the scraper silently misses stays missed. A CI step
comparing endpoint parity would turn "we believe the coverage is complete" into a fact,
and would catch upstream additions between the weekly version checks.

The spec is not a replacement for the scrape — it carries no code examples, no response
samples and no guide pages — but it is an excellent oracle for what should exist.

## Cross-check response samples against schemas

The 0.2.0 review found `network/getconnectedclientdetails` shipping a response sample
with a top-level `type` that its schema does not declare. One instance was found by
hand; a systematic comparison of every sample against its schema would say how many
there are.

## Reduce the cost of union-heavy pages

`network/createfirewallpolicy` takes roughly eight minutes to scrape because every one
of its 463 variants replays the full click path from the root. The weekly job only
scrapes applications whose upstream version changed, so this is rarely felt — worth
doing when it starts to hurt, not before.

## Smaller things worth doing

- Optional parameters are typed `str | None`, which JSON Schema encodes as
  `anyOf: [string, null]`. Some clients render that as a choice between two branches
  rather than an input field. Since every optional parameter already treats an empty
  string as absent, plain string types would be equivalent in behaviour and simpler for
  clients and models to consume.
- `CONTRIBUTING` should note that tool failures come back as `result.isError: true` with
  the message in `result.content[].text`, not as a JSON-RPC `error`. A test driver that
  only checks for `error` reads every failure as a success — this has now cost two
  people time.

## Not planned

**The 2026-07-28 specification features.** The server negotiates up to `2025-11-25`, the
maximum FastMCP 4.0.3 supports, and correctly negotiates down when a client offers
something newer. When FastMCP adopts the revision it will arrive with a dependency
update. Adopting its features deliberately is a different question, and the answer is
no:

| Feature | Applies here? |
|---|---|
| Stateless core, standardised HTTP surface | No — this is a stdio server |
| Multi Round-Trip Requests | No — no tool asks the user anything |
| MCP Apps (server-rendered UI) | No — the server returns text |
| Tasks (long-running work) | No — the slowest tool returns in milliseconds |
| OAuth / OIDC authorisation | No — there is nothing to authorise |
| Roots, Sampling, Logging (deprecated) | Not used |

The revision targets stateful HTTP servers with authentication, user prompts and
long-running jobs. This one is a stateless, read-only, credential-free server that reads
bundled files.

**Talking to a live controller.** That is a different product, and several good ones
exist — see the related servers on
[Glama](https://glama.ai/mcp/servers/KallistoX/mcp-unifi-applications). This server is
useful precisely because it needs no credentials and touches nothing.
