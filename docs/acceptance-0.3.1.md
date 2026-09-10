# Acceptance test — mcp-unifi-applications 0.3.1 (PyPI)

Black-box acceptance run against the **published package**, not the working tree.
Installed `mcp-unifi-applications==0.3.1` into a throwaway venv (Python 3.14.7) and
drove it as a foreign MCP client would: raw JSON-RPC over stdio, no MCP SDK.

Date: 2026-09-10 · Scope: the 10 tools across all 6 applications · Nothing was fixed,
this is findings only.

Prior art: 0.2.0 was audited the same way; those findings are fixed and covered by
tests, and were deliberately **not** re-tested here. Focus was the areas that changed
since: search relevance, endpoint-identifier resolution, enum/union rendering, guide
lookup, and the regenerated scraped data.

---

## Summary

| # | Finding | Severity | Layer |
|---|---------|----------|-------|
| [F1](#f1) | `get_endpoint` never renders query parameters | **high** | server |
| [F2](#f2) | Search ignores all query tokens but the strongest | **high** | server |
| [F3](#f3) | "create voucher" ranks DELETE #1, create absent from top-10 | **high** | server |
| [F4](#f4) | Response samples truncated at 58 lines → 7 invalid JSON | medium | data/scraper |
| [F5](#f5) | `get_guide` title lookup bypasses the ambiguity guard | medium | server |
| [Minor](#minor) | Typo asymmetry, empty response headings, casing echo, `--help` | low | mixed |

No crashes, no hangs, no protocol violations, no path traversal in the entire run.

---

<a id="f1"></a>
## F1 — `get_endpoint` never renders query parameters · high

Across all 196 endpoints, `get_endpoint` emits **zero** `## Query Parameters` sections.
42 endpoints have `queryParameters` populated in the shipped data. Path parameters
render correctly (144 sections, none missing), so this is specific to query params.

### Reproduce

```json
get_endpoint {"slug": "network/getnetworksoverviewpage"}
get_endpoint {"slug": "network/deletenetwork"}
get_endpoint {"slug": "carrier-fabric/listsubscribers"}
```

| slug | in shipped data | in rendered output |
|------|-----------------|--------------------|
| `network/getnetworksoverviewpage` | `offset`, `limit`, `filter` | — |
| `network/deletenetwork` | `force` | — |
| `carrier-fabric/listsubscribers` | `limit`, `cursor`, `sort`, `planId`, `suspended` | — |

The data is present and correct — `get_endpoint {"slug": "...", "summary": false}`
returns it in full. Only the default (summary) rendering path drops it.

### Why it matters

The tool's own description promises "method, path, description, **path and query
parameters**, request body and response fields."

A model reading this server never learns that list endpoints are paginated
(`offset`/`limit`/`cursor`/`sort`), that `filter` exists, or that `deletenetwork`
accepts a `force` flag. The compounding case: the Network **Filtering** guide documents
the `filter` query-parameter syntax at length, for a parameter that the endpoint
documentation never mentions — so the two halves of the docs disagree about whether it
exists.

---

<a id="f2"></a>
## F2 — Search ignores all query tokens but the strongest · high

Relevance scoring behaves as a **maximum over single tokens**, not a conjunction.
Additional tokens can only widen the result set, never narrow it.

### Reproduce

```json
search_endpoints {"query": "update camera"}
search_endpoints {"query": "update light"}
search_endpoints {"query": "update banana"}
search_endpoints {"query": "update xyzzy"}
```

All four return the **identical** ranking:

```
#1 [mobility] PUT  mobility/updatedevicenetwork   Update LAN / DHCP settings
#2 [network] PUT   network/updateaclrule          Update ACL Rule
#3 [network] PUT   network/updatednspolicy        Update DNS Policy
```

The correct answer for "update camera" — `protect/patch-v1camerasid`
("Patch camera settings") — does not appear at all. Same shape in the other direction:
`camera banana` ≡ `camera`, `firewall policy banana` ≡ `firewall policy`.

Contributing factor: Protect titles its mutations `Patch <noun> settings`, so
`update` → `patch` is a synonym gap. But the primary defect is that the discriminating
token (`camera`) contributes nothing once `update` scores highly.

### Why it matters

This violates the tool's documented contract:

> Matching is fuzzy but floored: a query that resembles nothing returns no matches
> rather than the least-bad guess.

The floor only catches *standalone* nonsense (`banana`, `zzzzqqq wwww` → no matches).
Nonsense paired with any common token returns ten confident results with no uncertainty
signal: `update banana`, `list zzzzqqq`, `zzzzqqq update` all return 10 hits.
`get zzzzqqq` returns 0 — the behaviour is not even consistent across common verbs.

### Not affected

Exact-title search is solid. All 196 endpoint titles were used as queries: 185 rank #1,
and the 11 exceptions are genuine cross-app title collisions
(`Connector - GET` etc. in 3 apps, `List Devices` in 2). None absent from top-10.

---

<a id="f3"></a>
## F3 — "create voucher" ranks DELETE #1, create absent from top-10 · high

Formally a special case of [F2](#f2), listed separately because the error points at a
destructive operation for a create intent.

### Reproduce

```json
search_endpoints {"query": "create voucher"}
search_endpoints {"query": "new voucher"}
search_endpoints {"query": "issue voucher"}
```

All three return `DELETE network/deletevoucher` at rank #1, and
**`network/createvouchers` appears nowhere in the top 10.**

### Mechanism

The create endpoint is titled "Generate Vouchers", not "Create Voucher". The slug
*is* indexed, but only matches as a whole string — the single-token query
`createvoucher` finds it at rank #1 immediately, while the two-token `create voucher`
never reaches it.

```json
search_endpoints {"query": "createvoucher"}     // → #1 network/createvouchers
search_endpoints {"query": "generate vouchers"} // → #1 network/createvouchers
search_endpoints {"query": "create vouchers"}   // → #1 DELETE, #2 network/createvouchers
```

---

<a id="f4"></a>
## F4 — Response samples truncated at 58 lines · medium

This is a **data/scraper defect shipped in the package**, surfaced by the server
without any truncation notice.

### Reproduce

```json
get_response_sample {"slug": "protect/get-v1sensorsid"}
```

Output ends after `"highThreshold": null` with no closing braces:
`json.loads()` → `Expecting ',' delimiter: line 58 column 26`.

Across all 125 samples the **maximum line count is exactly 58** — a hard cap.
Nine samples sit at 58 lines; seven of them are invalid JSON:

```
innerspace/get-v1project
protect/get-v1alarm-hubsid      protect/patch-v1alarm-hubsid
protect/get-v1link-stationsid   protect/patch-v1link-stationsid
protect/get-v1sensorsid         protect/patch-v1sensorsid
```

### Why it matters

The tool states it "Returns raw JSON exactly as the documentation shows it." A consumer
parsing the sample fails; a consumer reading it concludes the response object ends
where the truncation happens. Fixing this needs a scraper change plus a re-scrape, not
a server change — but the server could also detect unbalanced JSON and say so.

---

<a id="f5"></a>
## F5 — `get_guide` title lookup bypasses the ambiguity guard · medium

Slug resolution correctly refuses to guess. Title resolution silently picks one.

### Reproduce

```json
get_guide {"topic": "gettingstarted"}   // ✅ ambiguity notice, names 4 apps
get_guide {"topic": "getting-started"}  // ✅ ambiguity notice, names 2 apps
get_guide {"topic": "getting started"}  // ❌ silently returns carrier-fabric
get_guide {"topic": "Introduction"}     // ❌ silently returns protect (also innerspace, network)
get_guide {"topic": "Installation"}     // ❌ silently returns protect (also network)
get_guide {"topic": "error handling"}   // ❌ silently returns network (also carrier-fabric)
```

### Why it matters

The documented contract is:

> Topics resolve by slug first, then by title; when the same slug exists in several
> applications the reply lists them and asks for an app rather than picking one.

The guard is slug-only, but titles collide just as often — three guides are titled
exactly `Introduction`, two `Installation`, two `Error Handling`. Someone working on
Network who asks for "getting started" receives Carrier Fabric's guide. Severity is
medium rather than high only because the app name appears in the returned heading
(`# Getting Started (carrier-fabric)`), so the mistake is recoverable.

---

<a id="minor"></a>
## Minor observations

- **Typo tolerance is asymmetric.** `vouhcer`, `frewall`, `devcies` → "No matching
  endpoints found", while `update banana` returns 10 hits. `firewal policy` returns
  *Create DNS Policy* as #1 rather than anything firewall-related.
- **Empty `## Response [200]` headings** (45 endpoints). Faithful to the data — these
  are 204/No-Content and delete endpoints with no body — but a bare heading with
  nothing under it reads like a truncation. An explicit `(no body)` would be clearer.
- **Input casing is echoed into headings.** `get_example {"language": "CURL"}` →
  `# Create Network — CURL (local)`; `get_field_schema {"field_path": "TYPE[IPV4].ENABLED"}`
  → `# TYPE[IPV4].ENABLED (in requestBody)`. Cosmetic.
- **`search_endpoints` accepts `WS`, `HEAD`, `OPTIONS`** (its error message lists all
  eight), but its `method` parameter description names only the five common verbs.
- **`--help` is ignored** — the binary starts the server instead of printing usage.

---

## Verified clean

These areas were exercised systematically and found correct. Worth not re-litigating.

**Endpoint identifier resolution** *(changed area)* — all 179 unique bare slugs resolve;
all 196 app-qualified slugs resolve. The 6 ambiguous bare slugs (`connectorget`,
`connectordelete`, `connectorpatch`, `connectorpost`, `connectorput`, `listdevices`)
return a proper disambiguation listing every candidate. Unknown slugs return near
matches rather than a bare error.

**Enum / union rendering** *(changed area)* — enums render inline as
`one of: ALLOW, BLOCK, REJECT`; discriminator variants as `[ALLOW] adds:` and dotted
paths as `type[IPV4].enabled`. No empty union variants found anywhere — the 0.3.0
scraper fix holds in the published data.

**`get_field_schema`** — every one of **336** field paths emitted by `find_field` was
fed back in: 336/336 resolved. Case-insensitive. `type.enabled` (a path that skips a
discriminator) returns a resolution hint listing where `enabled` actually lives, rather
than failing.

**`find_field`** — counts internally consistent; all 50 shown rows unique on
(slug, path, section); the cap notice states the true total and endpoint count.
Endpoint counts match an independent walk of the shipped JSON.

**`get_example`** — all 5 languages × 2 modes checked across all 196 endpoints. The
cloud-only applications (site-manager, mobility, carrier-fabric) ship `remote` only and
default to it; `mode: "local"` is refused cleanly with the available pairs listed. No
example belongs to the wrong application or the wrong access mode. The two Protect
WebSocket endpoints have no curl example and say so instead of failing.

**Counts** — `get_docs_info` matches the shipped files exactly (11 / 11 / 8 / 78 / 79 / 9
endpoints; 3 / 1 / 1 / 4 / 2 / 3 guides). `list_endpoints` returns exactly 196 rows;
every app and method filter sums correctly, including the two `WS` endpoints, which are
reachable via `{"method": "WS"}` and would otherwise be invisible to method filtering.

**Robustness** — no path traversal (`../../../etc/passwd`, `network/_meta` both refused
cleanly); Unicode, emoji and 500-character queries handled; clean validation errors for
missing and mistyped arguments; unknown tool returns `isError` rather than a protocol
error. `stdout` stays pure JSON-RPC — the FastMCP banner correctly goes to `stderr`.

---

## Coverage

All 10 tools, each with and without its optional parameters.

- Full sweeps over all 196 endpoints for `get_endpoint` (both `summary` values),
  `get_example`, and `get_response_sample`
- All 14 guides, by slug, by title, and with/without `app`
- ~120 search queries: exact titles, path fragments, typos, natural-language phrasings,
  near-miss concepts, and nonsense
- ~40 error and edge cases for identifier forms — casing, surrounding whitespace,
  separator variants (`site_manager` / `sitemanager` / `Site Manager`), bare vs.
  app-qualified

**Not covered:** correctness of the scraped content against Ubiquiti's live
documentation. Everything was validated against the data shipped inside the package.
[F4](#f4) is the only place where that data is provably defective on its own terms.

---

## Reproducing

Install the published package and talk to it over stdio — no MCP SDK required:

```bash
python3 -m venv venv
./venv/bin/pip install "mcp-unifi-applications==0.3.1"
```

Minimal client: spawn `venv/bin/mcp-unifi-applications`, write newline-delimited
JSON-RPC to stdin, read responses from stdout.

1. `initialize` with `{"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {...}}`
2. `notifications/initialized` (notification, no id)
3. `tools/call` with `{"name": "<tool>", "arguments": {...}}`

Note that tool-level failures come back as `result.isError: true` with the message in
`result.content[].text`, **not** as a JSON-RPC `error` — a driver that only checks for
`error` will read every failure as a success.
