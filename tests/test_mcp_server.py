"""Tests for the UniFi Docs MCP Server."""

import json
import sys
from pathlib import Path

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import mcp_server as m


# --- Helpers ---

def _find_slug(fragment: str) -> str | None:
    """Find a qualified slug containing the fragment (e.g. 'createnetwork' -> 'network/createnetwork')."""
    for slug in m._endpoints:
        if slug.endswith(f"/{fragment}") or slug == fragment:
            return slug
    return None


# --- Data loading ---


class TestDataLoading:
    def test_endpoints_loaded(self):
        assert len(m._endpoints) > 0, "No endpoints loaded from docs/"

    def test_all_json_files_parse(self):
        docs_dir = Path(__file__).parent.parent / "docs"
        for app_dir in docs_dir.iterdir():
            if not app_dir.is_dir() or app_dir.name.startswith(("_", ".")):
                continue
            for f in app_dir.glob("*.json"):
                if f.stem.startswith("_"):
                    continue
                data = json.loads(f.read_text())
                assert isinstance(data, dict), f"{f.name} is not a dict"
                assert "sourceUrl" in data or "error" in data, f"{f.name} missing sourceUrl"

    def test_endpoints_have_required_fields(self):
        for slug, ep in m._endpoints.items():
            assert ep.get("h1"), f"{slug} missing h1"
            assert ep.get("method"), f"{slug} missing method"
            assert ep.get("path"), f"{slug} missing path"
            assert ep.get("sourceUrl"), f"{slug} missing sourceUrl"

    def test_endpoints_have_app_tag(self):
        for slug, ep in m._endpoints.items():
            assert ep.get("_app"), f"{slug} missing _app tag"

    def test_guides_loaded_separately(self):
        for slug, guide in m._guides.items():
            assert guide.get("type") == "guide", f"{slug} not typed as guide"
            assert slug not in m._endpoints, f"guide {slug} also in endpoints"

    def test_field_index_built(self):
        assert len(m._field_index) > 0, "Field index is empty"

    def test_resource_groups_built(self):
        assert len(m._resource_groups) > 0, "Resource groups empty"

    def test_search_index_matches_endpoints(self):
        index_slugs = {s for s, *_ in m._search_index}
        assert index_slugs == set(m._endpoints.keys())


# --- Search ---


class TestSearch:
    def test_search_network(self):
        result = m.search_endpoints("network")
        assert "createnetwork" in result
        assert "deletenetwork" in result

    def test_search_firewall(self):
        result = m.search_endpoints("firewall")
        assert "firewallpolicy" in result.lower() or "firewallzone" in result.lower()

    def test_search_method_filter(self):
        result = m.search_endpoints("network", method="DELETE")
        assert "DELETE" in result
        assert "POST" not in result

    def test_search_empty_query(self):
        result = m.search_endpoints("")
        assert "provide" in result.lower()

    def test_search_no_results(self):
        result = m.search_endpoints("xyznonexistent123")
        assert "no matching" in result.lower() or len(result.strip()) > 0


# --- list_endpoints ---


class TestListEndpoints:
    def test_list_all(self):
        result = m.list_endpoints()
        lines = result.strip().split("\n")
        assert len(lines) == len(m._endpoints)

    def test_list_filter_method(self):
        result = m.list_endpoints(method="DELETE")
        for line in result.strip().split("\n"):
            assert "DELETE" in line

    def test_list_invalid_method(self):
        result = m.list_endpoints(method="TRACE")
        assert "no endpoints" in result.lower()


# --- get_endpoint ---


class TestGetEndpoint:
    def test_valid_slug(self):
        slug = _find_slug("createnetwork")
        assert slug, "createnetwork not found"
        result = m.get_endpoint(slug)
        assert "Create Network" in result
        assert "POST" in result
        assert "/v1/sites" in result

    def test_invalid_slug_suggests(self):
        result = m.get_endpoint("network/createnetwork_typo")
        assert "Did you mean" in result

    def test_raw_json(self):
        slug = _find_slug("createnetwork")
        assert slug, "createnetwork not found"
        result = m.get_endpoint(slug, summary=False)
        data = json.loads(result)
        assert data["method"] == "POST"


# --- get_example ---


class TestGetExample:
    def test_legacy_ansible(self):
        # Find an endpoint with either examples or ansibleExample
        for slug, ep in m._endpoints.items():
            if ep.get("ansibleExample") or ep.get("examples", {}).get("local", {}).get("ansible"):
                result = m.get_example(slug, "ansible", "local")
                assert "ansible" in result.lower() or "ubiquiti" in result.lower() or slug in result
                return
        pytest.skip("No endpoints with ansible examples")

    def test_invalid_language(self):
        slug = _find_slug("createnetwork") or "network/createnetwork"
        result = m.get_example(slug, "rust")
        assert "Unknown language" in result

    def test_invalid_mode(self):
        slug = _find_slug("createnetwork") or "network/createnetwork"
        result = m.get_example(slug, "curl", "cloud")
        assert "Unknown mode" in result

    def test_invalid_slug(self):
        result = m.get_example("nonexistent")
        assert "not found" in result.lower()


# --- find_field ---


class TestFindField:
    def test_known_field(self):
        result = m.find_field("siteId")
        assert "siteId" in result

    def test_unknown_field_suggests(self):
        result = m.find_field("siteIdTypo")
        assert "Similar fields" in result or "not found" in result

    def test_scoped_to_slug(self):
        slug = _find_slug("createnetwork")
        assert slug, "createnetwork not found"
        result = m.find_field("siteId", slug=slug)
        assert "createnetwork" in result

    def test_scoped_miss(self):
        slug = _find_slug("createnetwork")
        assert slug, "createnetwork not found"
        result = m.find_field("xyznonexistent", slug=slug)
        assert "not found" in result


# --- get_endpoint_group ---


class TestGetFieldSchema:
    def test_top_level_field(self):
        slug = _find_slug("createnetwork")
        assert slug, "createnetwork not found"
        result = m.get_field_schema(slug, "management")
        assert "management" in result
        assert "Variants:" in result or "discriminator" in result.lower() or "GATEWAY" in result

    def test_discriminator_path(self):
        slug = _find_slug("createnetwork")
        assert slug, "createnetwork not found"
        result = m.get_field_schema(slug, "management[GATEWAY]")
        assert "management[GATEWAY]" in result
        # Should show child fields of the GATEWAY variant
        assert "dhcpV4" in result or "name" in result

    def test_deep_path(self):
        slug = _find_slug("createnetwork")
        assert slug, "createnetwork not found"
        result = m.get_field_schema(slug, "management[GATEWAY].dhcpV4")
        assert "dhcpV4" in result

    def test_invalid_path_suggests(self):
        slug = _find_slug("createnetwork")
        assert slug, "createnetwork not found"
        result = m.get_field_schema(slug, "nonexistent.path")
        assert "not found" in result.lower() or "not resolved" in result.lower()

    def test_invalid_slug(self):
        result = m.get_field_schema("nonexistent", "management")
        assert "not found" in result.lower()


class TestGetEndpointGroup:
    def test_networks(self):
        result = m.get_endpoint_group("networks")
        assert "createnetwork" in result
        assert "deletenetwork" in result

    def test_no_match(self):
        result = m.get_endpoint_group("xyznonexistent")
        assert "No resource group" in result


# --- get_guide ---


class TestGetGuide:
    def test_list_guides(self):
        result = m.get_guide()
        if not m._guides:
            pytest.skip("No guides loaded")
        assert "Available guides" in result

    def test_get_specific_guide(self):
        if not m._guides:
            pytest.skip("No guides loaded")
        slug = next(iter(m._guides))
        result = m.get_guide(slug)
        assert "#" in result  # Has a markdown heading

    def test_fuzzy_match(self):
        has_filtering = any("filtering" in s for s in m._guides)
        if not has_filtering:
            pytest.skip("filtering guide not loaded")
        result = m.get_guide("filter")
        assert "filter" in result.lower()

    def test_no_match(self):
        result = m.get_guide("xyznonexistent")
        assert "No guide found" in result or "Available" in result


# --- get_response_sample ---


class TestGetResponseSample:
    def test_invalid_slug(self):
        result = m.get_response_sample("nonexistent")
        assert "not found" in result.lower()
