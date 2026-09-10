"""UniFi API Docs MCP Server.

Exposes scraped UniFi application API documentation (Network, Protect, Site Manager, InnerSpace, Mobility, Carrier Fabric)
as queryable tools for use in Claude Desktop or any MCP-compatible client.
"""

import json
import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from rapidfuzz import fuzz

DOCS_DIR = Path(os.environ.get("DOCS_DIR", Path(__file__).parent / "docs"))


# --- Data loading ---

_endpoints: dict[str, dict] = {}
_guides: dict[str, dict] = {}
_search_index: list[tuple[str, str, str, str, str, str]] = []  # (slug, title, method, path, description, app)
_field_index: dict[str, list[tuple[str, str, str]]] = {}  # field_name_lower -> [(slug, path, section)]
_resource_groups: dict[str, list[str]] = {}  # resource path -> [slugs]
_loaded_apps: set[str] = set()
_meta: dict[str, dict] = {}  # app -> {"app", "version", "scrapedAt", "pageCount"}

VALID_LANGUAGES = ("curl", "go", "nodejs", "python", "ansible")
VALID_MODES = ("local", "remote")
# Apps whose docs declare only the cloud server, so examples exist only in remote form.
REMOTE_ONLY_APPS = frozenset({"site-manager", "mobility", "carrier-fabric"})
MAX_LIST_LINES = 200
MAX_FIELD_HITS = 50


def _index_fields(fields: list[dict], slug: str, section: str, path: str = ""):
    """Walk field tree and build reverse index of field_name -> locations.

    The section is carried along so find_field can say whether a hit is in the
    request or the response; the same dotted path often exists in both.
    """
    for f in fields:
        current = f"{path}.{f['name']}" if path else f["name"]
        key = f["name"].lower()
        _field_index.setdefault(key, []).append((slug, current, section))
        _index_fields(f.get("children") or [], slug, section, current)
        for disc in f.get("discriminator") or []:
            _index_fields(
                disc.get("schema") or [], slug, section,
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


def _load_app(app: str, directory: Path):
    """Load all JSON docs from a single app directory."""
    name = app or "network"
    _loaded_apps.add(name)
    meta_file = directory / "_meta.json"
    if meta_file.exists():
        try:
            _meta[name] = json.loads(meta_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    for f in sorted(directory.glob("*.json")):
        slug = f.stem
        if slug.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        # Prefix slug with app name for uniqueness across apps
        qualified = f"{app}/{slug}" if app else slug
        data["_app"] = app or "network"
        # Guide pages have type: "guide"
        if data.get("type") == "guide":
            _guides[qualified] = data
            continue
        _endpoints[qualified] = data
        method = data.get("method", "") or ""
        path = data.get("path", "") or ""
        desc = data.get("description", "") or ""
        _search_index.append((qualified, data.get("h1", ""), method, path, desc, data["_app"]))
        # Build field index
        for section_key in ("pathParameters", "queryParameters", "requestBody"):
            _index_fields(data.get(section_key) or [], qualified, section_key)
        for resp in data.get("responses") or []:
            _index_fields(resp.get("fields") or [], qualified, "response")
        # Group by resource
        rk = _resource_key(path)
        if rk:
            _resource_groups.setdefault(rk, []).append(qualified)


def _load_docs():
    _endpoints.clear()
    _guides.clear()
    _search_index.clear()
    _field_index.clear()
    _resource_groups.clear()
    _loaded_apps.clear()
    _meta.clear()

    # Try loading from app subdirectories first
    subdirs = [d for d in sorted(DOCS_DIR.iterdir())
               if d.is_dir() and not d.name.startswith(("_", "."))
               and any(d.glob("*.json"))]
    if subdirs:
        for d in subdirs:
            _load_app(d.name, d)
    else:
        # Flat layout fallback (backward compat)
        _load_app("", DOCS_DIR)


_load_docs()


def _docs_summary() -> str:
    parts = []
    for app in sorted(_loaded_apps):
        v = _meta.get(app, {}).get("version")
        parts.append(f"{app} v{v}" if v else f"{app} (version unknown)")
    return ", ".join(parts)


try:  # installed distribution; falls back when running from a source checkout
    __version__ = version("mcp-unifi-applications")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0+unknown"

mcp = FastMCP("unifi-applications", version=__version__, instructions=(
    "You have access to UniFi application API documentation (Network, Protect, Site Manager, InnerSpace, Mobility, Carrier Fabric). "
    "Use list_endpoints to browse, search_endpoints to find relevant endpoints, "
    "and get_endpoint to get full schema details. Use get_endpoint_group to get "
    "all CRUD operations for a resource at once. Filter by app name to narrow results. "
    f"Loaded docs: {_docs_summary()}. Use get_docs_info for scrape details."
))

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


MAX_ENUM_INLINE = 12

# Every tool reads bundled JSON and nothing else: no network, no credentials, no
# writes. Stating it in annotations rather than only in prose lets a client know
# without parsing a description.
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def _summarise_fields(
    fields: list[dict], depth: int = 0, max_depth: int = 2, full_enums: bool = False
) -> list[str]:
    """Build a compact text summary of a field tree."""
    lines = []
    indent = "  " * depth
    for f in fields:
        req = " (required)" if f.get("required") else ""
        typ = f.get("type", "")
        desc = f" — {f['description']}" if f.get("description") else ""
        lines.append(f"{indent}- {f['name']}: {typ}{req}{desc}")

        values = f.get("enum") or []
        if values:
            if full_enums or len(values) <= MAX_ENUM_INLINE:
                lines.append(f"{indent}  one of: {', '.join(values)}")
            else:
                shown = ", ".join(values[:MAX_ENUM_INLINE])
                lines.append(
                    f"{indent}  one of: {shown}, +{len(values) - MAX_ENUM_INLINE} more "
                    f"(get_field_schema for the full list)"
                )

        if f.get("discriminator") and depth < max_depth:
            # When the allowed values are already listed above, the bracketed
            # entries are the subset that carries extra fields - say so, rather
            # than letting them read as the complete set of options.
            label = " adds" if values else ""
            for disc in f["discriminator"]:
                lines.append(f"{indent}  [{disc['value']}]{label}:")
                lines.extend(
                    _summarise_fields(disc.get("schema") or [], depth + 2, max_depth, full_enums)
                )

        if f.get("children") and depth < max_depth:
            lines.extend(_summarise_fields(f["children"], depth + 1, max_depth, full_enums))
    return lines


# --- Tools ---


@mcp.tool(annotations=READ_ONLY)
def list_endpoints(method: str | None = None, app: str | None = None) -> str:
    """Browse the endpoint catalogue: one line per endpoint with method, path, slug
    and title.

    Returns at most 200 lines; beyond that the reply says how many were withheld and
    which filters would narrow it. For finding a specific endpoint, search_endpoints
    ranks by relevance instead. Unknown filter values are rejected by name rather
    than returned as an empty result.

    Args:
        method: Optional HTTP method filter (GET, POST, PUT, DELETE, PATCH).
        app: Optional app filter (network, protect, site-manager, innerspace, mobility, carrier-fabric). Omit to list all.
    """
    if not _search_index:
        return "No endpoints loaded. Check DOCS_DIR."
    bad = _bad_filter(app, method)
    if bad:
        return bad
    lines = []
    method_filter = method.strip().upper() if method else None
    app_filter = app.strip().lower() if app else None
    for slug, title, m, path, desc, ep_app in _search_index:
        if method_filter and m.upper() != method_filter:
            continue
        if app_filter and ep_app != app_filter:
            continue
        app_tag = f"[{ep_app}] " if len(_loaded_apps) > 1 else ""
        lines.append(f"{app_tag}{m} {path}  [{slug}]  {title}")
    if not lines:
        filters = []
        if method_filter:
            filters.append(f"method={method_filter}")
        if app_filter:
            filters.append(f"app={app_filter}")
        return f"No endpoints found ({', '.join(filters)})."
    if len(lines) > MAX_LIST_LINES:
        total = len(lines)
        lines = lines[:MAX_LIST_LINES]
        lines.append(
            f"... truncated: showing {MAX_LIST_LINES} of {total} endpoints. "
            f"Filter by app= ({', '.join(sorted(_loaded_apps))}) or method= to narrow."
        )
    return "\n".join(lines)


VALID_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "WS")


def _bad_filter(app: str | None, method: str | None) -> str | None:
    """Reject unknown app/method filters by name.

    Returning "nothing found" for a typo reads as "this app has no such endpoints",
    which is a different and wrong claim.
    """
    if app and app.strip().lower() not in _loaded_apps:
        return (f"Unknown app '{app}'. Loaded: {', '.join(sorted(_loaded_apps))}.")
    if method and method.strip().upper() not in VALID_METHODS:
        return (f"Unknown method '{method}'. Choose from: {', '.join(VALID_METHODS)}.")
    return None


def _truncate(text: str, max_len: int = 120) -> str:
    # Collapse to first line / sentence
    first_line = text.split("\n")[0].strip()
    if len(first_line) <= max_len:
        return first_line
    return first_line[:max_len - 3].rsplit(" ", 1)[0] + "..."


# Measured against the real corpus: genuine typos score 67-98 against their
# intended slug, while nonsense tops out at 42. Suggesting the best of a bad
# field reads as "this is probably what you wanted", which for garbage input is
# a lie - and for 'listnetworks' it pointed at deletenetwork.
MIN_SUGGEST_SCORE = 60
MIN_SEARCH_SCORE = 60


def _suggest_slugs(slug: str, n: int = 3) -> str:
    """Suggest close slug matches, or nothing when none are close."""
    scored = [(fuzz.ratio(slug.lower(), s.lower()), s) for s in _endpoints]
    scored.sort(reverse=True)
    suggestions = [s for score, s in scored[:n] if score >= MIN_SUGGEST_SCORE]
    return f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""


def _resolve_slug(slug: str) -> tuple[str | None, str]:
    """Resolve a slug to a qualified one, or explain why it cannot be.

    Bare slugs are accepted when unambiguous - 179 of 185 are - so the
    'createnetwork' form documented in the tool descriptions actually works.
    """
    if not slug or not slug.strip():
        return None, "Please provide an endpoint slug. Use list_endpoints or search_endpoints to find one."
    slug = slug.strip()
    if slug in _endpoints:
        return slug, ""
    matches = [q for q in _endpoints if q.split("/", 1)[-1] == slug]
    if len(matches) == 1:
        return matches[0], ""
    if len(matches) > 1:
        return None, f"Endpoint '{slug}' is ambiguous. Did you mean: {', '.join(sorted(matches))}?"
    return None, f"Endpoint '{slug}' not found.{_suggest_slugs(slug)}"


@mcp.tool(annotations=READ_ONLY)
def search_endpoints(query: str, method: str | None = None, app: str | None = None) -> str:
    """Find endpoints by name, path fragment, method or description.

    Returns up to ten matches ranked by relevance, each as a slug, method, path,
    title and a one-line description. Matching is fuzzy but floored: a query that
    resembles nothing returns no matches rather than the least-bad guess. Pass a
    result's slug to get_endpoint for the full schema. Unknown filter values are
    rejected by name.

    Args:
        query: Search term (endpoint name, path fragment, or keyword).
        method: Optional HTTP method filter (GET, POST, PUT, DELETE, PATCH).
        app: Optional app filter (network, protect, site-manager, innerspace, mobility, carrier-fabric). Omit to search all.
    """
    if not query.strip():
        return "Please provide a search query."
    bad = _bad_filter(app, method)
    if bad:
        return bad

    q = query.strip().lower()
    method_filter = method.strip().upper() if method else None
    app_filter = app.strip().lower() if app else None
    scored = []
    for slug, title, m, path, desc, ep_app in _search_index:
        if method_filter and m.upper() != method_filter:
            continue
        if app_filter and ep_app != app_filter:
            continue
        # Weight title/slug/path much higher than description
        core = f"{slug} {title} {m} {path}".lower()
        core_score = fuzz.token_set_ratio(q, core)
        desc_score = fuzz.token_set_ratio(q, desc.lower()) * 0.3 if desc else 0
        # Exact substring in core fields gets a big bonus
        bonus = 60 if q in core else (20 if q in desc.lower() else 0)
        score = core_score + desc_score + bonus
        scored.append((score, slug, title, m, path, desc, ep_app))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:10]

    lines = []
    for score, slug, title, m, path, desc, ep_app in top:
        if score < MIN_SEARCH_SCORE:
            break
        app_tag = f"[{ep_app}] " if len(_loaded_apps) > 1 else ""
        lines.append(f"{app_tag}[{slug}] {m} {path}  {title}")
        if desc:
            lines.append(f"    {_truncate(desc)}")
    return "\n".join(lines) if lines else "No matching endpoints found."


@mcp.tool(annotations=READ_ONLY)
def get_endpoint(slug: str, summary: bool = True) -> str:
    """Get everything documented about one endpoint: method, path, description,
    path and query parameters, request body and response fields.

    Returns readable text: a nested field list with types, required markers and
    descriptions, discriminator variants in brackets and enum values inline, folded
    at three levels deep. Large endpoints run to tens of thousands of characters —
    when you already know which field you need, get_field_schema returns that
    subtree alone. An unknown slug returns close matches rather than an error.

    Args:
        slug: Endpoint identifier, app-qualified ('network/createnetwork') or bare
              ('createnetwork') when only one application has it. Use
              search_endpoints or list_endpoints to find one.
        summary: True (default) returns the folded text above. False returns the raw
                 scraped JSON — complete and unfolded to every depth, several times
                 larger, and only worth it when the folding hides something you need.
    """
    slug, err = _resolve_slug(slug)
    if err:
        return err
    ep = _endpoints[slug]

    if not summary:
        return json.dumps(ep, indent=2)

    app_label = f" ({ep['_app']})" if ep.get("_app") and len(_loaded_apps) > 1 else ""
    lines = [
        f"# {ep.get('h1', slug)}{app_label}",
        f"{ep.get('method', '?')} {ep.get('path', '?')}",
    ]
    if ep.get("description"):
        lines.append(f"\n{ep['description']}")
    lines.append(f"\nSource: {ep.get('sourceUrl', 'N/A')}")

    if ep.get("pathParameters"):
        lines.append("\n## Path Parameters")
        lines.extend(_summarise_fields(ep["pathParameters"], max_depth=1))

    if ep.get("queryParameters"):
        lines.append("\n## Query Parameters")
        lines.extend(_summarise_fields(ep["queryParameters"], max_depth=1))

    if ep.get("requestBody"):
        lines.append("\n## Request Body")
        lines.extend(_summarise_fields(ep["requestBody"], max_depth=3))

    if ep.get("responses"):
        for resp in ep["responses"]:
            statuses = ", ".join(str(s) for s in (resp.get("statuses") or []))
            lines.append(f"\n## Response [{statuses}]")
            lines.extend(_summarise_fields(resp.get("fields") or [], max_depth=3))

    return "\n".join(lines)


@mcp.tool(annotations=READ_ONLY)
def get_example(slug: str, language: str = "curl", mode: str | None = None) -> str:
    """Get a runnable request for one endpoint, in one language, as published by
    Ubiquiti.

    Returns a heading naming the endpoint, language and mode, followed by a single
    code block. The request shape is authoritative; host addresses, site ids and API
    keys are placeholders to fill in. Bodies show the schema's default values, not a
    worked example — combine with get_endpoint or get_field_schema when the payload
    matters. If the requested language and mode pair does not exist, the reply lists
    the pairs that do instead of failing.

    Args:
        slug: Endpoint identifier, app-qualified or bare when unambiguous.
        language: One of curl, go, nodejs, python, ansible.
        mode: 'local' addresses the console directly (https://<console-ip>/proxy/…);
              'remote' goes through the UniFi cloud API (api.ui.com). Defaults to
              'local', except for the cloud-only applications — site-manager,
              mobility and carrier-fabric — which have no local form and default to
              'remote'.
    """
    slug, err = _resolve_slug(slug)
    if err:
        return err
    ep = _endpoints[slug]

    lang = (language or "").strip().lower()
    # Default mode based on app: some apps are cloud-only
    app = ep.get("_app", "network")
    mode = (mode or "").strip()
    m = (mode or ("remote" if app in REMOTE_ONLY_APPS else "local")).lower()
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
            return f"# {ep.get('h1', slug)} — {language} ({m})\n\n{code}"
        # Show what's available
        available = []
        for mk, mv in examples.items():
            for lk in mv:
                available.append(f"{lk} ({mk})")
        return f"No {language} ({m}) example for '{slug}'. Available: {', '.join(available)}"

    # Legacy format: ansibleExample only
    if lang == "ansible" and ep.get("ansibleExample"):
        return f"# {ep.get('h1', slug)} — ansible (local)\n\n{ep['ansibleExample']}"

    return f"No examples available for '{slug}'."


@mcp.tool(annotations=READ_ONLY)
def get_response_sample(slug: str) -> str:
    """Get the sample response body published for one endpoint.

    Returns raw JSON exactly as the documentation shows it, with placeholder values.
    About two thirds of endpoints have one; the rest say so plainly. This is the
    shape of a successful reply — for the field-by-field schema including types and
    which fields are optional, use get_endpoint.

    Args:
        slug: Endpoint identifier (e.g. 'network/getnetworksoverviewpage').
    """
    slug, err = _resolve_slug(slug)
    if err:
        return err
    ep = _endpoints[slug]
    sample = ep.get("responseSample")
    if not sample:
        return f"No response sample available for '{slug}'."
    return sample


@mcp.tool(annotations=READ_ONLY)
def find_field(field_name: str, slug: str | None = None) -> str:
    """Locate a field by name across every endpoint, including inside discriminator
    variants.

    Returns one line per occurrence: endpoint slug, dotted path, and which schema
    section it sits in (request body, parameters, or response). Common names appear
    hundreds of times; the reply is capped at 50 and states the true total and how
    many endpoints are involved, so a short list is never mistaken for a complete
    one. Paths from here can be passed straight to get_field_schema. A name that
    matches nothing returns close alternatives.

    Args:
        field_name: The field name to search for (case-insensitive).
        slug: Optional — limit search to a specific endpoint.
    """
    if slug:
        # Otherwise "not found in endpoint 'bogus'" reads as though the endpoint
        # exists and merely lacks the field.
        slug, err = _resolve_slug(slug)
        if err:
            return err
    key = field_name.strip().lower()
    if not key:
        return "Please provide a field name."
    hits = _field_index.get(key, [])
    if slug:
        hits = [h for h in hits if h[0] == slug]
    if not hits:
        similar = [
            k for score, k in sorted(
                ((fuzz.ratio(key, k), k) for k in _field_index), reverse=True
            )[:5] if score >= MIN_SUGGEST_SCORE
        ]
        scope = f"endpoint '{slug}'" if slug else "any endpoint"
        msg = f"Field '{field_name}' not found in {scope}."
        if similar:
            msg += f"\nSimilar fields: {', '.join(similar)}"
        return msg

    total = len(hits)
    endpoints = len({h[0] for h in hits})
    lines = [f"[{s}] {path}  ({section})" for s, path, section in hits[:MAX_FIELD_HITS]]
    if total > MAX_FIELD_HITS:
        # Silently stopping at a cap invites the reader to conclude that an
        # endpoint not listed here does not have the field.
        lines.append(
            f"... truncated: showing {MAX_FIELD_HITS} of {total} occurrences across "
            f"{endpoints} endpoints. Pass slug= to scope the search to one endpoint."
        )
    return "\n".join(lines)


def _resolve_path(fields: list[dict], path_parts: list[str]) -> dict | None:
    """Walk a field tree following a dotted path like 'management[GATEWAY].dhcpV4'.

    Supports:
      - field names: 'dhcpV4'
      - discriminator variants: 'management[GATEWAY]'
      - dotted paths: 'management[GATEWAY].dhcpV4.gateway'
    """
    if not path_parts:
        return None
    segment = path_parts[0]
    rest = path_parts[1:]

    # Parse segment: 'fieldName' or 'fieldName[VARIANT]'
    field_name = segment
    variant = None
    if "[" in segment and segment.endswith("]"):
        field_name, variant = segment[:-1].split("[", 1)

    for f in fields:
        if f["name"].lower() != field_name.lower():
            continue

        # If a variant is requested, navigate into the discriminator
        if variant and f.get("discriminator"):
            for disc in f["discriminator"]:
                if disc["value"].lower() == variant.lower():
                    next_fields = disc.get("schema") or []
                    if not rest:
                        # Return a synthetic node representing this variant
                        return {
                            "name": f"{f['name']}[{disc['value']}]",
                            "type": f.get("type", ""),
                            "description": f.get("description"),
                            "children": next_fields,
                        }
                    return _resolve_path(next_fields, rest)
            return None  # variant not found

        if not rest:
            return f
        # Continue into children
        return _resolve_path(f.get("children") or [], rest)

    return None


@mcp.tool(annotations=READ_ONLY)
def get_field_schema(slug: str, field_path: str) -> str:
    """Drill into a specific field's schema within an endpoint.

    Instead of fetching the full 70KB endpoint schema, use this to get just the
    subtree you need. Paths from find_field output work directly.

    Args:
        slug: Endpoint identifier (e.g. 'network/createnetwork').
        field_path: Dotted path to the field, with discriminator variants in brackets.
                    Examples: 'dhcpV4', 'management[GATEWAY].dhcpV4',
                    'management[GATEWAY].dhcpV4.gateway'.
    """
    slug, err = _resolve_slug(slug)
    if err:
        return err
    ep = _endpoints[slug]

    parts = [p for p in (field_path or "").split(".") if p]
    if not parts:
        return (f"Please provide a field path within '{slug}'. "
                "Use find_field to locate one, or get_endpoint for the whole schema.")

    # Search across all schema sections
    for section_key in ("requestBody", "pathParameters", "queryParameters"):
        result = _resolve_path(ep.get(section_key) or [], parts)
        if result:
            lines = [f"# {field_path} (in {section_key})"]
            lines.extend(_summarise_fields([result], max_depth=10, full_enums=True))
            if result.get("discriminator"):
                lines.append(
                    f"\nVariants with extra fields: "
                    f"{', '.join(d['value'] for d in result['discriminator'])}"
                    if result.get("enum")
                    else f"\nVariants: {', '.join(d['value'] for d in result['discriminator'])}"
                )
            return "\n".join(lines)

    for resp in ep.get("responses") or []:
        result = _resolve_path(resp.get("fields") or [], parts)
        if result:
            lines = [f"# {field_path} (in response)"]
            lines.extend(_summarise_fields([result], max_depth=10, full_enums=True))
            if result.get("discriminator"):
                lines.append(
                    f"\nVariants with extra fields: "
                    f"{', '.join(d['value'] for d in result['discriminator'])}"
                    if result.get("enum")
                    else f"\nVariants: {', '.join(d['value'] for d in result['discriminator'])}"
                )
            return "\n".join(lines)

    # Try find_field as fallback to suggest the right path
    name = parts[-1].split("[")[0]
    hits = _find_field(ep.get("requestBody") or [], name)
    for resp in ep.get("responses") or []:
        hits.extend(_find_field(resp.get("fields") or [], name))
    if hits:
        paths = [h[0] for h in hits[:5]]
        return f"Field path '{field_path}' not resolved. '{name}' exists at:\n" + "\n".join(f"  {p}" for p in paths)

    return f"Field path '{field_path}' not found in endpoint '{slug}'."


@mcp.tool(annotations=READ_ONLY)
def get_endpoint_group(resource: str) -> str:
    """See every operation on one resource at once, grouped by API path.

    Returns each matching resource path with its endpoints beneath it — method, slug,
    title and a one-line description — so the available verbs on a resource are
    visible together rather than found one at a time. Matching is a substring of the
    path, so 'networks' also finds nested paths, and one query can span applications.

    Args:
        resource: Resource name or path fragment (e.g. 'networks', 'acl-rules', 'wifi/broadcasts').
    """
    q = (resource or "").strip().strip("/").lower()
    if not q:
        return ("Please provide a resource name or path fragment, e.g. 'networks', "
                "'firewall/policies' or 'cameras'. Use list_endpoints to browse.")
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
            app_tag = f"[{ep.get('_app')}] " if len(_loaded_apps) > 1 else ""
            lines.append(f"  {app_tag}{m} [{slug}] {title}")
            if desc:
                lines.append(f"    {_truncate(desc)}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool(annotations=READ_ONLY)
def get_guide(topic: str | None = None, app: str | None = None) -> str:
    """Read a prose guide page: filtering syntax, error handling, getting started,
    response formats.

    Returns the page as markdown with its title and source URL. Omit the topic to
    list what is available. Topics resolve by slug first, then by title; when the
    same slug exists in several applications the reply lists them and asks for an
    app rather than picking one. These pages carry the conventions that endpoint
    schemas assume but do not repeat.

    Args:
        topic: Guide slug or search term. Omit to list all available guides.
        app: Optional app filter (network, protect, site-manager, innerspace, mobility, carrier-fabric). Omit to search all.
    """
    if app:
        bad = _bad_filter(app, None)
        if bad:
            # "No guide pages loaded." for a typo'd app claims the server has none.
            return bad
    app_filter = app.strip().lower() if app else None
    guides = {s: g for s, g in _guides.items() if not app_filter or g.get("_app") == app_filter}

    def _render(slug: str) -> str:
        g = guides[slug]
        title = g.get("h1") or slug
        app_tag = f" ({g.get('_app')})" if len(_loaded_apps) > 1 else ""
        return f"# {title}{app_tag}\n\n{g.get('content', 'No content.')}\n\nSource: {g.get('sourceUrl', 'N/A')}"

    if not guides:
        return "No guide pages loaded."

    if not topic or not topic.strip():
        lines = ["Available guides:"]
        for slug, data in sorted(guides.items()):
            title = data.get("h1") or slug
            app_tag = f"[{data.get('_app')}] " if len(_loaded_apps) > 1 else ""
            lines.append(f"  {app_tag}[{slug}] {title}")
        return "\n".join(lines)

    topic = topic.strip()
    if topic in guides:
        return _render(topic)

    # Slug before title. Matching only on the rendered h1 made
    # get_guide("gettingstarted", app="site-manager") fail while listing
    # site-manager/gettingstarted as available in the same sentence.
    bare = [s for s in guides if s.split("/", 1)[-1] == topic]
    if len(bare) == 1:
        return _render(bare[0])
    if len(bare) > 1:
        return (f"Guide '{topic}' exists in several applications: {', '.join(sorted(bare))}. "
                "Pass app= to choose one.")

    scored = [(fuzz.token_set_ratio(topic.lower(), f"{s} {g.get('h1', '')}".lower()), s)
              for s, g in guides.items()]
    scored.sort(reverse=True)
    if scored and scored[0][0] > 50:
        # Titles collide as often as slugs do - three guides are titled
        # "Introduction", two "Installation", two "Error Handling" - and they score
        # identically. Taking scored[0] let sort order decide which application the
        # reader got.
        best = scored[0][0]
        tied = [s for score, s in scored if score == best]
        if len(tied) == 1:
            return _render(tied[0])
        return (f"'{topic}' matches {len(tied)} guides equally well: "
                f"{', '.join(sorted(tied))}. Pass app= to choose one.")

    available = ", ".join(sorted(guides.keys()))
    return f"No guide found for '{topic}'. Available: {available}"


@mcp.tool(annotations=READ_ONLY)
def get_docs_info() -> str:
    """Report what documentation this server is serving.

    Returns one line per application: API version, when it was scraped, and how many
    endpoints and guides it holds. Worth checking before trusting an answer about a
    recent API change — the documentation is a point-in-time copy, not a live view.
    """
    if not _loaded_apps:
        return "No docs loaded. Check DOCS_DIR."
    lines = []
    for app in sorted(_loaded_apps):
        meta = _meta.get(app, {})
        n_ep = sum(1 for e in _endpoints.values() if e["_app"] == app)
        n_gd = sum(1 for g in _guides.values() if g["_app"] == app)
        lines.append(
            f"{app}: API v{meta.get('version', 'unknown')}, "
            f"scraped {meta.get('scrapedAt', 'unknown')}, "
            f"{n_ep} endpoints, {n_gd} guides"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
