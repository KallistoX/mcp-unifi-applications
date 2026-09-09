"""Tests for the UniFi Docs MCP Server."""

import json
import re
import sys
from pathlib import Path

import pytest

# Import from the source tree without requiring an install
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp_unifi_applications import server as m

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
        docs_dir = Path(__file__).parent.parent / "src" / "mcp_unifi_applications" / "docs"
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
        # Naming the bad filter beats "no endpoints found", which reads as a
        # claim about the corpus rather than about the argument.
        result = m.list_endpoints(method="TRACE")
        assert "unknown method" in result.lower()
        assert "TRACE" in result


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

    def test_header_names_the_resolved_mode(self):
        # mode defaults to None; the header must show what was actually resolved,
        # not the raw parameter.
        for slug, ep in m._endpoints.items():
            examples = ep.get("examples") or {}
            for resolved, langs in examples.items():
                if not langs:
                    continue
                lang = next(iter(langs))
                result = m.get_example(slug, lang, resolved)
                assert f"({resolved})" in result.splitlines()[0]
                assert "(None)" not in result
                return
        pytest.skip("corpus has no endpoints with examples")

    def test_default_mode_is_never_none_in_output(self):
        checked = 0
        for slug, ep in m._endpoints.items():
            if not (ep.get("examples") or {}):
                continue
            for lang in m.VALID_LANGUAGES:
                result = m.get_example(slug, lang)  # no mode argument
                assert "(None)" not in result, f"{slug} / {lang}: {result.splitlines()[0]}"
                checked += 1
            if checked >= 20:
                break
        assert checked > 0, "corpus has no endpoints with examples"

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


# --- Version metadata ---


class TestMeta:
    def test_meta_files_parse_and_match_dir(self):
        docs_dir = Path(__file__).parent.parent / "src" / "mcp_unifi_applications" / "docs"
        found = 0
        for app_dir in docs_dir.iterdir():
            if not app_dir.is_dir() or app_dir.name.startswith(("_", ".")) or app_dir.name == "tmp_pageClarification":
                continue
            meta_file = app_dir / "_meta.json"
            if not meta_file.exists():
                continue
            data = json.loads(meta_file.read_text())
            assert data["app"] == app_dir.name, f"{meta_file}: app mismatch"
            assert re.fullmatch(r"\d+(\.\d+)*", data["version"]), f"{meta_file}: bad version"
            assert data["pageCount"] > 0
            found += 1
        assert found > 0, "no _meta.json found in any app dir"

    def test_meta_loaded_for_every_app(self):
        # Derived from what actually loaded, so a newly added app dir is covered
        # without editing this list.
        assert m._loaded_apps, "no app dirs loaded"
        for app in m._loaded_apps:
            assert app in m._meta, f"{app} has no _meta loaded"

    def test_instructions_name_versions(self):
        for app, meta in m._meta.items():
            assert f"{app} v{meta['version']}" in m.mcp.instructions


# --- get_docs_info ---


class TestGetDocsInfo:
    def test_lists_every_loaded_app(self):
        out = m.get_docs_info()
        for app in m._loaded_apps:
            assert app in out

    def test_contains_versions_and_counts(self):
        out = m.get_docs_info()
        for meta in m._meta.values():
            assert f"API v{meta['version']}" in out
        assert "endpoints" in out
        assert "guides" in out


# --- Field index covers query parameters ---


class TestQueryParameterIndex:
    def test_query_parameters_indexed(self):
        checked = 0
        for slug, ep in m._endpoints.items():
            for f in ep.get("queryParameters") or []:
                assert f["name"].lower() in m._field_index, (
                    f"query param '{f['name']}' of {slug} missing from field index"
                )
                checked += 1
        assert checked > 0, "corpus unexpectedly has no queryParameters"


# --- list_endpoints cap ---


class TestListEndpointsCap:
    def test_caps_output_with_hint(self, monkeypatch):
        fake = [
            (f"network/fake{i}", f"Fake {i}", "GET", f"/v1/fake/{i}", "", "network")
            for i in range(300)
        ]
        monkeypatch.setattr(m, "_search_index", fake)
        out = m.list_endpoints()
        lines = out.split("\n")
        assert len(lines) == m.MAX_LIST_LINES + 1
        assert "truncated" in lines[-1]
        assert "app" in lines[-1] and "method" in lines[-1]

    def test_no_cap_below_limit(self, monkeypatch):
        fake = [
            (f"network/fake{i}", f"Fake {i}", "GET", f"/v1/fake/{i}", "", "network")
            for i in range(10)
        ]
        monkeypatch.setattr(m, "_search_index", fake)
        out = m.list_endpoints()
        assert "truncated" not in out
        assert len(out.split("\n")) == 10


# --- Release metadata ---


class TestReleaseMetadata:
    """Guards the two release traps: a PyPI version cannot be re-uploaded, and the
    MCP registry proves package ownership by finding `mcp-name: <server>` in the
    README it reads back as the PyPI long_description."""

    @staticmethod
    def _root() -> Path:
        return Path(__file__).parent.parent

    def _server_json(self) -> dict:
        return json.loads((self._root() / "server.json").read_text())

    def _pyproject(self) -> dict:
        import tomllib

        return tomllib.loads((self._root() / "pyproject.toml").read_text())

    def test_readme_carries_the_registry_ownership_token(self):
        name = self._server_json()["name"]
        readme = (self._root() / "README.md").read_text()
        assert f"mcp-name: {name}" in readme, (
            f"README.md must contain 'mcp-name: {name}' — the registry reads it back "
            "as the PyPI long_description to prove package ownership"
        )

    def test_versions_agree(self):
        server = self._server_json()
        project_version = self._pyproject()["project"]["version"]
        assert server["version"] == project_version, "server.json and pyproject.toml versions differ"
        for pkg in server.get("packages") or []:
            assert pkg["version"] == project_version, (
                f"server.json packages[{pkg['identifier']}].version != pyproject version"
            )

    def test_readme_is_the_packaged_long_description(self):
        # The token only reaches PyPI if the README is what gets packaged.
        assert self._pyproject()["project"]["readme"] == "README.md"


# --- Output that would mislead a model reading it ---


class TestHonestOutput:
    """One test per finding from the 0.2.0 package acceptance review."""

    def test_unqualified_slug_resolves_when_unambiguous(self):
        # The tool descriptions document 'createnetwork'; it used to be rejected.
        assert m.get_endpoint("createnetwork").startswith("# Create Network")

    def test_ambiguous_bare_slug_lists_the_candidates(self):
        out = m.get_endpoint("connectorget")
        assert "ambiguous" in out.lower()
        assert out.count("/connectorget") >= 2

    def test_find_field_rejects_an_unknown_endpoint(self):
        out = m.find_field("vlanId", slug="bogus/slug")
        assert "not found" in out.lower()
        # Must be about the endpoint, not about the field being absent from it.
        assert "bogus/slug" in out
        assert "field 'vlanId' not found" not in out.lower()

    def test_find_field_names_the_section(self):
        for line in m.find_field("vlanId").splitlines():
            if line.startswith("["):
                assert line.rstrip().endswith(")"), line

    def test_find_field_reports_truncation(self):
        out = m.find_field("id")
        lines = out.splitlines()
        if len(lines) > m.MAX_FIELD_HITS:
            last = lines[-1]
            assert "truncated" in last
            assert "occurrences" in last and "endpoints" in last
        else:  # pragma: no cover - corpus dependent
            pytest.skip("corpus has fewer hits than the cap")

    def test_guide_resolves_by_slug_within_an_app(self):
        for slug, g in m._guides.items():
            app, bare = slug.split("/", 1)
            if sum(1 for s in m._guides if s.split("/", 1)[1] == bare) > 1:
                out = m.get_guide(topic=bare, app=app)
                assert "No guide found" not in out, slug
                assert g.get("h1") is None or g["h1"] in out
                return
        pytest.skip("no guide slug is shared across apps")

    def test_ambiguous_guide_asks_instead_of_guessing(self):
        out = m.get_guide(topic="gettingstarted")
        if "several applications" in out:
            assert "app=" in out
        else:  # pragma: no cover - corpus dependent
            assert out.startswith("#")

    def test_guide_rejects_an_unknown_app(self):
        out = m.get_guide(app="bogusapp")
        assert "unknown app" in out.lower()
        # "No guide pages loaded" would claim the server has none at all.
        assert "no guide pages loaded" not in out.lower()

    def test_search_rejects_an_unknown_app(self):
        out = m.search_endpoints("camera", app="protekt")
        assert "unknown app" in out.lower()

    def test_search_returns_nothing_for_nonsense(self):
        for q in ("zzzzznotathing", "<script>alert(1)</script>", "asdfghjkl"):
            assert m.search_endpoints(q) == "No matching endpoints found.", q

    def test_suggestions_are_withheld_when_nothing_is_close(self):
        out = m.get_endpoint("totallybogusslug")
        assert "not found" in out.lower()
        assert "did you mean" not in out.lower()

    def test_suggestions_still_offered_for_a_real_typo(self):
        out = m.get_endpoint("network/createnetwrk")
        assert "did you mean" in out.lower()
        assert "network/createnetwork" in out

    def test_empty_field_path_does_not_raise(self):
        out = m.get_field_schema("network/createnetwork", "")
        assert "provide a field path" in out.lower()

    def test_empty_resource_group_asks_for_a_value(self):
        out = m.get_endpoint_group("")
        assert "provide a resource" in out.lower()

    def test_mode_whitespace_is_tolerated_consistently(self):
        blank = m.get_example("network/createnetwork", "curl", "")
        padded = m.get_example("network/createnetwork", "curl", "remote ")
        assert "(local)" in blank.splitlines()[0]
        assert "(remote)" in padded.splitlines()[0]

    def test_server_reports_the_package_version(self):
        import tomllib

        pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
        assert m.mcp.version == pyproject["project"]["version"]
