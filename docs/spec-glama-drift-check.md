# Spec — detect when the Glama listing drifts from the repository

Status: ready to implement · Written 2026-09-13 · Not yet implemented

## The question this answers

The Glama listing and the hosted deployment are built from a release image, not from
`main`. After a release they can lag: on 2026-09-10 the deployment served 0.3.1 —
including seven malformed response samples that 0.4.0 had already fixed — until a
Build & Release was triggered by hand and the machine next woke.

Today the only way to notice is to open the Glama Inspector and call `get_docs_info`
by eye. That is a check nobody performs on a Tuesday. It should run itself.

## What the Glama API actually offers

Verified 2026-09-13 against the published OpenAPI description.

| | |
|---|---|
| Base | `https://glama.ai/api/mcp` |
| Description | `https://glama.ai/api/mcp/openapi.json` |
| Catalog | `https://glama.ai/.well-known/api-catalog` (RFC 9727) — names this API and no other |
| Auth | Bearer token; keys at `https://glama.ai/settings/api-keys` |

Nine operations, eight read-only; the only write is `POST /v1/telemetry/usage`. There
is **no** API for deployments, releases, machine type, environment variables or tool
toggles — those are web UI only. There is no CLI: nothing on npm or PyPI, and the npm
package `glama` is an unrelated alias of a TypeScript MCP framework, last published
2025-03-06.

The relevant operation is `GET /v1/servers/{namespace}/{slug}`, here
`KallistoX/mcp-unifi-applications`.

### The trap

**`McpServer` carries no version and no scrape dates.** Its required fields are
`attributes`, `description`, `environmentVariablesJsonSchema`, `id`, `name`,
`namespace`, `qualityScore`, `repository`, `slug`, `spdxLicense`, `thumbnailUrl`,
`tools`, `url`.

So "is Glama serving the current release?" cannot be asked directly. Do not spend an
hour looking for a version field — there isn't one.

What *can* be compared is the **tool surface**. Glama re-introspects a server on each
release, so `tools` reflects whatever build is deployed. Comparing it against the tool
list the repository produces answers the question by proxy, and answers it in the terms
that matter: if the descriptions match, a client reading the listing sees what this
repository ships.

## What to build

A scheduled workflow that compares the two and reports a mismatch. Nothing more.

1. Read the repository's own tool surface. `await mcp.mcp._list_tools()` returns ten
   `FunctionTool` objects carrying `.name`, `.description` and `.parameters` — verified
   2026-09-13. No subprocess or stdio handshake is needed; `tests/test_mcp_server.py`
   shows the in-process pattern.
2. `GET /v1/servers/KallistoX/mcp-unifi-applications` with the bearer token. Each entry
   of `tools` has `name`, `description` and `inputSchema`, all three required by the
   schema, so `.parameters` is comparable against `inputSchema`.
3. Compare: tool names present on each side, and for each shared name the description.
   Treat `inputSchema` as a second, optional signal — it is the stronger tell that a
   different build is deployed, but it is also the noisier one, so start with names and
   descriptions and only add it if it proves stable.
4. Report. Do not fail loudly on the first mismatch — see below.

### Constraints that are not negotiable

**Drift is expected right after a release** and is not a defect. The deployment picks
up a new image when the machine next wakes, and it suspends when idle. A workflow that
fails the moment the two differ will cry wolf every release. Give it a grace period —
a scheduled weekly run, or a check that only reports drift older than a day.

**Never fail the build on Glama being unreachable, slow, or rate-limiting.** This is an
external service telling us about a cosmetic listing. A network error is a skip, not a
failure.

**The API key is a repository secret.** It is not needed by any other workflow and must
not be added to `ci.yml`, which runs on pull requests from forks.

**The data licence has teeth.** The 401 body states it plainly: use of this data
"requires visible attribution to Glama on every page that displays it, and a link to a
record's Glama listing wherever you present that record". A workflow that compares two
values and writes a line into its own log does not display anything. **Writing the
quality score into `README.md` would**, and would then require the attribution and the
link — the `url` field exists for exactly that. Prefer not to publish the score at all;
the badge already links to the listing and is served by Glama itself.

## Acceptance criteria

- Running it while the listing matches the repository reports no drift and exits zero.
- Running it against a deliberately altered local tool description reports that tool by
  name. Prove this the way the other fixes in this repository were proven: make the
  change, watch the check fail, revert, watch it pass.
- Glama unreachable, a 401, or a 429 produces a skip with a readable reason, never a
  red build.
- No API key appears in any log line, including an error path.
- `CONTRIBUTING.md` gains a sentence on where the secret comes from and what the check
  is for.

## Out of scope

- Publishing the score anywhere. See the licence note.
- Triggering a Glama build or release. No API exists for it.
- Anything touching the MCP registry or PyPI; both already expose versions directly and
  neither has drifted.
- Reacting to the drift automatically. Report it; a human decides whether to press
  Build & Release.

## Background worth knowing before starting

`ROADMAP.md` explains what this project is and what it deliberately does not do.
`docs/acceptance-0.3.1.md` is a black-box review of the published package and shows the
standard of evidence expected here: measure first, then change, then show the numbers.
