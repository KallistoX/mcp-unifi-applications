# UniFi MCP Server: Queryable API Documentation

<!-- Ownership token for the MCP registry: it fetches this README as the PyPI
     long_description and looks for this exact token. Do not remove. -->
<!-- mcp-name: io.github.KallistoX/mcp-unifi-applications -->

![CI](https://github.com/KallistoX/mcp-unifi-applications/actions/workflows/ci.yml/badge.svg)
[![PyPI](https://img.shields.io/pypi/v/mcp-unifi-applications)](https://pypi.org/project/mcp-unifi-applications/)
[![Python](https://img.shields.io/pypi/pyversions/mcp-unifi-applications)](https://pypi.org/project/mcp-unifi-applications/)
[![Glama](https://glama.ai/mcp/servers/KallistoX/mcp-unifi-applications/badges/score.svg)](https://glama.ai/mcp/servers/KallistoX/mcp-unifi-applications)

An MCP server that makes the official [UniFi API documentation](https://developer.ui.com)
queryable by AI agents: endpoint search, schema drill-down, and code examples in five
languages. It covers every application Ubiquiti publishes API docs for: **Network,
Protect, Site Manager, InnerSpace, Mobility and Carrier Fabric**.

It is **read-only and credential-free**. It serves documentation and never talks to
your controller.

## Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). The scraped
docs ship inside the package, so there is nothing to scrape and no API key to set.

**Claude Code**

```bash
claude mcp add unifi-docs -- uvx mcp-unifi-applications
```

Add `--scope user` to make it available in every project.

**Claude Desktop and other clients** that read an `mcpServers` block take this entry
(Claude Desktop: `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "unifi-docs": {
      "command": "uvx",
      "args": ["mcp-unifi-applications"]
    }
  }
}
```

If the client reports that it cannot find `uvx` (GUI apps often start without your
shell's `PATH`), put the output of `which uvx` in `command` instead.

<details>
<summary>Without uv</summary>

```bash
pip install mcp-unifi-applications
```

Then use `"command": "mcp-unifi-applications"` with no `args`, or the absolute path
to that script if your client does not see your virtualenv.

</details>

What ships in the current release:

<!-- docs-versions:start -->
| Application | API version | Scraped | Pages |
|---|---|---|---|
| Network | v11.0.97 | 2026-11-02 | 82 |
| Protect | v7.3.74 | 2026-11-02 | 81 |
| Site Manager | v1.0.0 | 2026-09-10 | 12 |
| InnerSpace | v1.3.23 | 2026-09-10 | 12 |
| Mobility | v1.0.0 | 2026-09-10 | 9 |
| Carrier Fabric | v1.0.0 | 2026-09-10 | 14 |
<!-- docs-versions:end -->

A workflow checks developer.ui.com every Monday and releases new API versions on its own.

## Example

> *"Without any context, just by using the unifi-applications MCP Server: can you
> tell me how to create a network with Go with the network API from UniFi, and
> what options do I have regarding the managed IPv4 DHCP gateway configuration?"*

Claude answers that through the server, with none of the documentation in its context
to begin with:

| Call | What comes back |
|---|---|
| `search_endpoints("create network")` | `POST /v1/sites/{siteId}/networks` |
| `get_endpoint("network/createnetwork")` | the request body; `management` is a discriminated union |
| `get_field_schema(…, "management[GATEWAY].ipv4Configuration.dhcpConfiguration")` | **only** the DHCP subtree |
| `get_example("network/createnetwork", "go")` | a working request in Go |

The third call is the one that earns the server its place. Instead of the 70 KB
endpoint schema, it returns just the subtree that answers the question:

```text
# management[GATEWAY].ipv4Configuration.dhcpConfiguration (in requestBody)
- dhcpConfiguration: object (Gateway Managed IPv4 DHCP Configuration) — IPv4 DHCP …
  - mode: string (required)
    [RELAY]:
      - dhcpServerIpAddresses: Array of string — DHCP Server IP addresses
    [SERVER]:
      - dnsServerIpAddressesOverride: Array of string — List of DNS servers …
      - domainName: string — Domain name that can be used to access network in the browser.
      - gatewayIpAddressOverride: string — Gateway IP address provided to DHCP clients. …
      - ipAddressRange: object
        - start: string (required)
        - stop: string (required)
      - leaseTimeSeconds: integer — The lease time in seconds for addresses in this range.
      … ntpServerIpAddresses, option43Value, pxeConfiguration, tftpServerAddress, …
```

## Tools

| Tool | What it does |
|---|---|
| `search_endpoints` | Fuzzy search by name, path, method or description |
| `list_endpoints` | Browse all endpoints, filtered by HTTP method or app |
| `get_endpoint` | Full schema for one endpoint, folded to a readable summary |
| `get_endpoint_group` | All operations on one resource, e.g. "networks" |
| `get_field_schema` | One field's subtree, e.g. `management[GATEWAY].dhcpV4` |
| `find_field` | Where a field name occurs across all endpoint schemas |
| `get_example` | A request in curl, Go, Node.js, Python or Ansible, local or remote |
| `get_response_sample` | Example JSON response |
| `get_guide` | Guide pages: filtering syntax, error handling, getting started |
| `get_docs_info` | Which API versions are loaded, with scrape dates and counts |

Tools that return several results take an optional `app` filter (`network`,
`protect`, `site-manager`, `innerspace`, `mobility`, `carrier-fabric`).

## How it differs

Most UniFi MCP servers are **control planes**: they log in to your controller and read
or change live state. This one is a **knowledge plane** and never sees your network.
The two complement each other: this one tells the model what the API looks like, a
control-plane server calls it.

Ubiquiti does publish an OpenAPI spec per application, and it is a good one. But it
carries no code examples and no response samples, has none of the guide pages, and at
around 400 KB for Network it does not fit usefully into a context window. This server
ships up to ten examples and a response sample per endpoint, and hands the model one field subtree at
a time.

## More

- [CONTRIBUTING.md](CONTRIBUTING.md): development setup, the scraper, the JSON format, releases
- [ROADMAP.md](ROADMAP.md): what is planned, what is not, and why
- [CHANGELOG.md](CHANGELOG.md)

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Ubiquiti Inc. The API
documentation content scraped and served by this tool is the property of
[Ubiquiti Inc.](https://ui.com) and is sourced from their public
[developer portal](https://developer.ui.com). "UniFi" is a trademark of Ubiquiti Inc.

## License

MIT
