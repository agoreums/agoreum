"""The published OpenAPI contract, and what it deliberately leaves out.

The schema used to be disabled in production to reduce surface area. That reason
does not survive contact with the facts: the repository is public, so every
router is readable by anyone, and the three official SDKs name the paths they
call. Withholding the document hid nothing from an attacker while costing every
integrator the ability to generate a client for a language we do not ship, import
the API into a tool, or check their code against the contract instead of against
our prose.

Publishing it does not mean publishing everything. Operator endpoints are not
part of the contract anyone should build against, and listing them invites use
that will break. So the document is scoped, and the scoping is asserted here
rather than trusted to whoever adds the next router.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.public_schema import EXCLUDED_TAGS, PUBLIC_TAGS


def _tags_in(document: dict) -> set[str]:
    return {
        tag
        for operations in document["paths"].values()
        for operation in operations.values()
        for tag in (operation.get("tags") or [])
    }


class TestTheContractIsPublished:
    async def test_the_schema_is_served(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/openapi.json")
        assert response.status_code == 200, response.text
        document = response.json()
        assert document["paths"], "an empty schema is not a published contract"

    async def test_it_is_a_document_a_generator_can_consume(
        self, client: AsyncClient
    ) -> None:
        """Shape, not just presence.

        A truncated or malformed document still returns 200 and still looks like
        a success to anyone checking the status code.
        """
        document = (await client.get("/api/v1/openapi.json")).json()

        assert document.get("openapi", "").startswith("3."), document.get("openapi")
        assert document["info"]["title"]
        assert document["info"]["version"]
        assert document.get("components", {}).get("schemas"), (
            "no component schemas, so nothing can be generated from this"
        )

    async def test_the_paths_the_sdks_call_are_in_it(self, client: AsyncClient) -> None:
        """The document has to cover what we already tell people to use."""
        document = (await client.get("/api/v1/openapi.json")).json()
        paths = set(document["paths"])

        for path in (
            "/api/v1/marketplace/services",
            "/api/v1/orders",
            "/api/v1/agents/mine",
            "/api/v1/me",
        ):
            assert path in paths, f"{path} is called by the SDKs and is undocumented"


class TestOperatorSurfaceIsNotAdvertised:
    async def test_no_excluded_tag_appears(self, client: AsyncClient) -> None:
        document = (await client.get("/api/v1/openapi.json")).json()
        leaked = _tags_in(document) & set(EXCLUDED_TAGS)
        assert not leaked, (
            f"operator endpoints are advertised as supported: {sorted(leaked)}. "
            "They change without notice, so documenting them invites use that breaks."
        )

    async def test_no_admin_path_appears(self, client: AsyncClient) -> None:
        """Belt and braces, by path rather than by tag.

        The tag check fails if somebody adds an admin route under a public tag,
        which is the likelier mistake than inventing a new operator tag.
        """
        document = (await client.get("/api/v1/openapi.json")).json()
        admin = [p for p in document["paths"] if "/admin" in p]
        assert not admin, f"admin paths in the published contract: {admin}"

    async def test_every_route_is_classified(self, client: AsyncClient) -> None:
        """A new tag must be a decision, not a default.

        With an allowlist, forgetting leaves an endpoint undocumented, which is
        visible and harms nobody. This makes the forgetting visible too.
        """
        from app.main import app

        def api_routes(router):
            found = []
            for route in getattr(router, "routes", []) or []:
                if type(route).__name__ == "_IncludedRouter":
                    found.extend(api_routes(route.original_router))
                elif hasattr(route, "dependant") and getattr(route, "methods", None):
                    found.append(route)
            return found

        known = PUBLIC_TAGS | set(EXCLUDED_TAGS)
        unclassified = {
            tag
            for route in api_routes(app)
            for tag in (getattr(route, "tags", []) or [])
            if tag not in known
        }
        assert not unclassified, (
            f"these tags are neither published nor excluded: {sorted(unclassified)}. "
            "Add each to PUBLIC_TAGS or to EXCLUDED_TAGS with a reason."
        )

    def test_the_two_sets_do_not_overlap(self) -> None:
        overlap = PUBLIC_TAGS & set(EXCLUDED_TAGS)
        assert not overlap, f"a tag is both published and excluded: {sorted(overlap)}"


@pytest.mark.parametrize("tag", sorted(PUBLIC_TAGS))
async def test_each_published_tag_actually_has_routes(
    client: AsyncClient, tag: str
) -> None:
    """Guards the guard.

    A tag listed as public but matching nothing means the allowlist has drifted
    from the application, and the exclusion tests above would still pass while
    the document quietly lost a section.
    """
    document = (await client.get("/api/v1/openapi.json")).json()
    assert tag in _tags_in(document), f"{tag} is published but no route carries it"
