"""UniFi Network API Docs MCP Server.

Exposes scraped UniFi API documentation as queryable tools
for use in Claude Desktop or any MCP-compatible client.
"""

import json
import os
from pathlib import Path

from fastmcp import FastMCP
from rapidfuzz import fuzz

DOCS_DIR = Path(os.environ.get("DOCS_DIR", Path(__file__).parent / "docs"))

mcp = FastMCP("unifi-applications", instructions=(
    "You have access to the full UniFi Network API v10.1.84 documentation. "
    "Use list_endpoints to browse, search_endpoints to find relevant endpoints, "
    "and get_endpoint to get full schema details. Use get_endpoint_group to get "
    "all CRUD operations for a resource at once."
))

# --- Data loading ---

_endpoints: dict[str, dict] = {}
_guides: dict[str, dict] = {}
_search_index: list[tuple[str, str, str, str, str]] = []  # (slug, title, method, path, description)
_field_index: dict[str, list[tuple[str, str]]] = {}  # field_name_lower -> [(slug, path)]
_resource_groups: dict[str, list[str]] = {}  # resource path -> [slugs]

VALID_LANGUAGES = ("curl", "go", "nodejs", "python", "ansible")
VALID_MODES = ("local", "remote")


def _index_fields(fields: list[dict], slug: str, path: str = ""):
    """Walk field tree and build reverse index of field_name -> locations."""
    for f in fields:
        current = f"{path}.{f['name']}" if path else f["name"]
        key = f["name"].lower()
        _field_index.setdefault(key, []).append((slug, current))
        _index_fields(f.get("children") or [], slug, current)
        for disc in f.get("discriminator") or []:
            _index_fields(
                disc.get("schema") or [], slug,
                f"{current}[{disc['value']}]"
            )


def _resource_key(path: str) -> str | None:
    """Extract the resource base path, e.g. '/v1/sites/{siteId}/networks/{id}' -> '/v1/sites/{siteId}/networks'."""
    if not path:
        return None
    parts = path.rstrip("/").split("/")
    # Walk backwards past trailing path params like {networkId}
    while parts and parts[-1].startswith("{"):
        parts.pop()
    return "/".join(parts) if parts else None


def _load_docs():
    _endpoints.clear()
    _guides.clear()
    _search_index.clear()
    _field_index.clear()
    _resource_groups.clear()
    for f in sorted(DOCS_DIR.glob("*.json")):
        slug = f.stem
        if slug.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        # Guide pages have type: "guide"
        if data.get("type") == "guide":
            _guides[slug] = data
            continue
        _endpoints[slug] = data
        method = data.get("method", "") or ""
        path = data.get("path", "") or ""
        desc = data.get("description", "") or ""
        _search_index.append((slug, data.get("h1", ""), method, path, desc))
        # Build field index
        for section_key in ("pathParameters", "requestBody"):
            _index_fields(data.get(section_key) or [], slug)
        for resp in data.get("responses") or []:
            _index_fields(resp.get("fields") or [], slug)
        # Group by resource
        rk = _resource_key(path)
        if rk:
            _resource_groups.setdefault(rk, []).append(slug)


_load_docs()

# --- Field traversal helper ---


def _find_field(fields: list[dict], name: str, path: str = "") -> list[tuple[str, dict]]:
    results = []
    for f in fields:
        current = f"{path}.{f['name']}" if path else f["name"]
        if f["name"].lower() == name.lower():
            results.append((current, f))
        results.extend(_find_field(f.get("children") or [], name, current))
        for disc in f.get("discriminator") or []:
            results.extend(_find_field(
                disc.get("schema") or [], name,
                f"{current}[{disc['value']}]"
            ))
    return results


def _summarise_fields(fields: list[dict], depth: int = 0, max_depth: int = 2) -> list[str]:
    """Build a compact text summary of a field tree."""
    lines = []
    indent = "  " * depth
    for f in fields:
        req = " (required)" if f.get("required") else ""
        typ = f.get("type", "")
        desc = f" — {f['description']}" if f.get("description") else ""
        lines.append(f"{indent}- {f['name']}: {typ}{req}{desc}")

        if f.get("discriminator") and depth < max_depth:
            for disc in f["discriminator"]:
                lines.append(f"{indent}  [{disc['value']}]:")
                lines.extend(_summarise_fields(disc.get("schema") or [], depth + 2, max_depth))

        if f.get("children") and depth < max_depth:
            lines.extend(_summarise_fields(f["children"], depth + 1, max_depth))
    return lines


# --- Tools ---


@mcp.tool()
def list_endpoints(method: str | None = None) -> str:
    """List all available UniFi API endpoints with their HTTP method and path.

    Args:
        method: Optional HTTP method filter (GET, POST, PUT, DELETE, PATCH).
    """
    if not _search_index:
        return "No endpoints loaded. Check DOCS_DIR."
    lines = []
    method_filter = method.upper() if method else None
    for slug, title, m, path, desc in _search_index:
        if method_filter and m.upper() != method_filter:
            continue
        lines.append(f"{m} {path}  [{slug}]  {title}")
    if not lines:
        return f"No endpoints found for method {method_filter}."
    return "\n".join(lines)


def _truncate(text: str, max_len: int = 120) -> str:
    # Collapse to first line / sentence
    first_line = text.split("\n")[0].strip()
    if len(first_line) <= max_len:
        return first_line
    return first_line[:max_len - 3].rsplit(" ", 1)[0] + "..."


def _suggest_slugs(slug: str, n: int = 3) -> str:
    """Suggest closest matching slugs using fuzzy match."""
    scored = [(fuzz.ratio(slug.lower(), s.lower()), s) for s in _endpoints]
    scored.sort(reverse=True)
    suggestions = [s for _, s in scored[:n]]
    return f"Did you mean: {', '.join(suggestions)}?"


@mcp.tool()
def search_endpoints(query: str, method: str | None = None) -> str:
    """Search UniFi API endpoints by name, path, method, or description.

    Returns the top matching endpoints ranked by relevance.
    Use the slug from results with get_endpoint for full details.

    Args:
        query: Search term (endpoint name, path fragment, or keyword).
        method: Optional HTTP method filter (GET, POST, PUT, DELETE, PATCH).
    """
    if not query.strip():
        return "Please provide a search query."

    q = query.lower()
    method_filter = method.upper() if method else None
    scored = []
    for slug, title, m, path, desc in _search_index:
        if method_filter and m.upper() != method_filter:
            continue
        # Weight title/slug/path much higher than description
        core = f"{slug} {title} {m} {path}".lower()
        core_score = fuzz.token_set_ratio(q, core)
        desc_score = fuzz.token_set_ratio(q, desc.lower()) * 0.3 if desc else 0
        # Exact substring in core fields gets a big bonus
        bonus = 60 if q in core else (20 if q in desc.lower() else 0)
        score = core_score + desc_score + bonus
        scored.append((score, slug, title, m, path, desc))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:10]

    lines = []
    for score, slug, title, m, path, desc in top:
        if score < 30:
            break
        lines.append(f"[{slug}] {m} {path}  {title}")
        if desc:
            lines.append(f"    {_truncate(desc)}")
    return "\n".join(lines) if lines else "No matching endpoints found."


@mcp.tool()
def get_endpoint(slug: str, summary: bool = True) -> str:
    """Get the full schema for a UniFi API endpoint.

    Args:
        slug: Endpoint identifier (e.g. 'createnetwork', 'listnetworks').
              Use list_endpoints or search_endpoints to find slugs.
        summary: If True, return a compact field summary. If False, return raw JSON.
    """
    ep = _endpoints.get(slug)
    if not ep:
        return f"Endpoint '{slug}' not found. {_suggest_slugs(slug)}"

    if not summary:
        return json.dumps(ep, indent=2)

    lines = [
        f"# {ep.get('h1', slug)}",
        f"{ep.get('method', '?')} {ep.get('path', '?')}",
    ]
    if ep.get("description"):
        lines.append(f"\n{ep['description']}")
    lines.append(f"\nSource: {ep.get('sourceUrl', 'N/A')}")

    if ep.get("pathParameters"):
        lines.append("\n## Path Parameters")
        lines.extend(_summarise_fields(ep["pathParameters"], max_depth=1))

    if ep.get("requestBody"):
        lines.append("\n## Request Body")
        lines.extend(_summarise_fields(ep["requestBody"], max_depth=3))

    if ep.get("responses"):
        for resp in ep["responses"]:
            statuses = ", ".join(str(s) for s in (resp.get("statuses") or []))
            lines.append(f"\n## Response [{statuses}]")
            lines.extend(_summarise_fields(resp.get("fields") or [], max_depth=3))

    return "\n".join(lines)


@mcp.tool()
def get_example(slug: str, language: str = "curl", mode: str = "local") -> str:
    """Get a code example for a specific UniFi API endpoint.

    Args:
        slug: Endpoint identifier (e.g. 'createnetwork').
        language: Programming language — one of: curl, go, nodejs, python, ansible.
        mode: 'local' (direct console access) or 'remote' (via cloud API).
    """
    ep = _endpoints.get(slug)
    if not ep:
        return f"Endpoint '{slug}' not found. {_suggest_slugs(slug)}"

    lang = language.lower()
    m = mode.lower()
    if lang not in VALID_LANGUAGES:
        return f"Unknown language '{language}'. Choose from: {', '.join(VALID_LANGUAGES)}"
    if m not in VALID_MODES:
        return f"Unknown mode '{mode}'. Choose from: {', '.join(VALID_MODES)}"

    # New format: examples.{mode}.{language}
    examples = ep.get("examples")
    if examples:
        mode_examples = examples.get(m, {})
        code = mode_examples.get(lang)
        if code:
            return f"# {ep.get('h1', slug)} — {language} ({mode})\n\n{code}"
        # Show what's available
        available = []
        for mk, mv in examples.items():
            for lk in mv:
                available.append(f"{lk} ({mk})")
        return f"No {language} ({mode}) example for '{slug}'. Available: {', '.join(available)}"

    # Legacy format: ansibleExample only
    if lang == "ansible" and ep.get("ansibleExample"):
        return f"# {ep.get('h1', slug)} — ansible (local)\n\n{ep['ansibleExample']}"

    return f"No examples available for '{slug}'."


@mcp.tool()
def get_response_sample(slug: str) -> str:
    """Get the example JSON response for a specific UniFi API endpoint.

    Args:
        slug: Endpoint identifier (e.g. 'listnetworks').
    """
    ep = _endpoints.get(slug)
    if not ep:
        return f"Endpoint '{slug}' not found. {_suggest_slugs(slug)}"
    sample = ep.get("responseSample")
    if not sample:
        return f"No response sample available for '{slug}'."
    return sample


@mcp.tool()
def find_field(field_name: str, slug: str | None = None) -> str:
    """Find where a field appears across endpoint schemas.

    Searches through request bodies, path parameters, and responses
    including inside discriminator variants. Uses a pre-built index for speed.

    Args:
        field_name: The field name to search for (case-insensitive).
        slug: Optional — limit search to a specific endpoint.
    """
    key = field_name.lower()
    hits = _field_index.get(key, [])
    if slug:
        hits = [(s, p) for s, p in hits if s == slug]
    if not hits:
        # Try fuzzy match on field names
        similar = sorted(
            _field_index.keys(),
            key=lambda k: fuzz.ratio(key, k),
            reverse=True,
        )[:5]
        scope = f"endpoint '{slug}'" if slug else "any endpoint"
        msg = f"Field '{field_name}' not found in {scope}."
        if similar:
            msg += f"\nSimilar fields: {', '.join(similar)}"
        return msg
    lines = [f"[{s}] {p}" for s, p in hits[:50]]
    return "\n".join(lines)


@mcp.tool()
def get_endpoint_group(resource: str) -> str:
    """Get all CRUD operations for a resource (e.g. 'networks', 'firewall', 'wifi').

    Returns a summary of every endpoint that operates on the same resource path,
    so you can see all available operations at once.

    Args:
        resource: Resource name or path fragment (e.g. 'networks', 'acl-rules', 'wifi/broadcasts').
    """
    q = resource.lower().strip("/")
    matching_keys = [k for k in _resource_groups if q in k.lower()]
    if not matching_keys:
        return f"No resource group found matching '{resource}'. Try a path fragment like 'networks' or 'firewall/policies'."

    lines = []
    for rk in sorted(matching_keys):
        lines.append(f"## {rk}")
        for slug in _resource_groups[rk]:
            ep = _endpoints[slug]
            m = ep.get("method", "?")
            title = ep.get("h1", slug)
            desc = ep.get("description", "") or ""
            lines.append(f"  {m} [{slug}] {title}")
            if desc:
                lines.append(f"    {_truncate(desc)}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_guide(topic: str | None = None) -> str:
    """Get a UniFi API guide page (e.g. filtering syntax, error handling, getting started).

    Args:
        topic: Guide slug or search term. Omit to list all available guides.
    """
    if not topic:
        if not _guides:
            return "No guide pages loaded."
        lines = ["Available guides:"]
        for slug, data in sorted(_guides.items()):
            title = data.get("h1") or slug
            lines.append(f"  [{slug}] {title}")
        return "\n".join(lines)

    # Exact match
    if topic in _guides:
        g = _guides[topic]
        title = g.get("h1") or topic
        return f"# {title}\n\n{g.get('content', 'No content.')}\n\nSource: {g.get('sourceUrl', 'N/A')}"

    # Fuzzy match
    scored = [(fuzz.token_set_ratio(topic.lower(), f"{s} {g.get('h1', '')}".lower()), s)
              for s, g in _guides.items()]
    scored.sort(reverse=True)
    if scored and scored[0][0] > 50:
        best_slug = scored[0][1]
        g = _guides[best_slug]
        title = g.get("h1") or best_slug
        return f"# {title}\n\n{g.get('content', 'No content.')}\n\nSource: {g.get('sourceUrl', 'N/A')}"

    available = ", ".join(sorted(_guides.keys()))
    return f"No guide found for '{topic}'. Available: {available}"


if __name__ == "__main__":
    mcp.run()
