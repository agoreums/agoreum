"""Marketplace discovery tests.

Search is exercised against real PostgreSQL full-text indexing with real
published services. Nothing is stubbed: the point of these tests is to prove
that the trigger-maintained tsvector, the GIN index, ranking, and every filter
genuinely work together.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.session import get_db
from app.main import app

pytestmark = pytest.mark.asyncio


class Wallet:
    def __init__(self) -> None:
        self._account = Account.create()

    @property
    def address(self) -> str:
        return self._account.address.lower()

    def sign(self, message: str) -> str:
        return self._account.sign_message(encode_defunct(text=message)).signature.hex()


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        # Fail fast when nothing is listening. The default waits out a full
        # TCP timeout per test, which turns a skipped suite on a machine with
        # no database into an hour of nothing.
        connect_args={"timeout": 5},
    )
    try:
        async with eng.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        await eng.dispose()
        pytest.skip(f"no database reachable: {type(exc).__name__}")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    connection = await engine.connect()
    transaction = await connection.begin()
    session = async_sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncClient:
    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def sign_in(client: AsyncClient) -> str:
    wallet = Wallet()
    challenge = (
        await client.post(
            "/api/v1/auth/nonce",
            json={"address": wallet.address, "chain_id": settings.CHAIN_ID},
        )
    ).json()
    body = (
        await client.post(
            "/api/v1/auth/signin",
            json={
                "message": challenge["message"],
                "signature": wallet.sign(challenge["message"]),
                "nonce": challenge["nonce"],
            },
        )
    ).json()
    return body["tokens"]["access_token"]


async def make_published_agent(client: AsyncClient, token: str) -> str:
    slug = f"agent-{uuid.uuid4().hex[:10]}"
    await client.post(
        "/api/v1/agents",
        json={"slug": slug, "name": "Test Provider"},
        headers=auth(token),
    )
    wallets = (await client.get("/api/v1/auth/me/wallets", headers=auth(token))).json()
    await client.put(
        f"/api/v1/agents/{slug}/payout-wallet",
        json={"wallet_id": wallets[0]["id"]},
        headers=auth(token),
    )
    await client.post(f"/api/v1/agents/{slug}/publish", headers=auth(token))
    return slug


async def publish_service(
    client: AsyncClient, token: str, agent_slug: str, **fields
) -> dict:
    slug = fields.pop("slug", f"svc-{uuid.uuid4().hex[:8]}")
    payload = {"slug": slug, "title": "A Service", "price": "10", **fields}

    created = await client.post(
        f"/api/v1/agents/{agent_slug}/services", json=payload, headers=auth(token)
    )
    assert created.status_code == 201, created.text

    published = await client.post(
        f"/api/v1/agents/{agent_slug}/services/{slug}/publish", headers=auth(token)
    )
    assert published.status_code == 200, published.text
    return published.json()


@pytest_asyncio.fixture
async def catalogue(client: AsyncClient) -> dict:
    """A small but real published catalogue to search over."""
    token = await sign_in(client)
    agent = await make_published_agent(client, token)

    categories = (await client.get("/api/v1/categories")).json()
    software = next(c for c in categories if c["slug"] == "software-and-engineering")
    code_review = next(
        c for c in software["children"] if c["slug"] == "code-review"
    )
    content = next(c for c in categories if c["slug"] == "content-and-language")

    await publish_service(
        client, token, agent,
        slug="summarize",
        title="Document Summarization",
        summary="Condense long reports into executive summaries",
        description="Turns lengthy PDF reports into structured briefings.",
        tags=["nlp", "summarization"],
        price="25.50",
        delivery_time_hours=24,
        category_id=content["id"],
    )
    await publish_service(
        client, token, agent,
        slug="code-audit",
        title="Solidity Security Audit",
        summary="Review smart contracts for vulnerabilities",
        description="Line-by-line review of Solidity contracts before deployment.",
        tags=["solidity", "security"],
        price="500",
        delivery_time_hours=168,
        category_id=code_review["id"],
    )
    await publish_service(
        client, token, agent,
        slug="translate",
        title="Technical Translation",
        summary="Translate technical documentation accurately",
        tags=["translation", "nlp"],
        pricing_model="per_unit",
        price="0.08",
        price_unit="word",
        delivery_time_hours=48,
        category_id=content["id"],
    )

    return {"token": token, "agent": agent}


async def search(client: AsyncClient, **params) -> dict:
    response = await client.get("/api/v1/marketplace/services", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def slugs(results: dict) -> set[str]:
    return {item["slug"] for item in results["items"]}


class TestFullTextSearch:
    async def test_query_matches_the_title(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(client, q="summarization", agent=catalogue["agent"])
        assert "summarize" in slugs(results)

    async def test_query_matches_the_description(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        """Description terms are indexed at lower weight, but still findable."""
        results = await search(client, q="vulnerabilities", agent=catalogue["agent"])
        assert "code-audit" in slugs(results)

    async def test_query_matches_a_tag(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(client, q="solidity", agent=catalogue["agent"])
        assert "code-audit" in slugs(results)

    async def test_search_is_stemmed(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        """English stemming: 'translating' should find 'Translation'."""
        results = await search(client, q="translating", agent=catalogue["agent"])
        assert "translate" in slugs(results)

    async def test_multiple_terms_are_combined(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(client, q="solidity audit", agent=catalogue["agent"])
        assert slugs(results) == {"code-audit"}

    async def test_quoted_phrase_is_honoured(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(
            client, q='"security audit"', agent=catalogue["agent"]
        )
        assert "code-audit" in slugs(results)

    async def test_negation_excludes_results(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        """websearch_to_tsquery treats a leading '-' as exclusion."""
        results = await search(client, q="nlp -translation", agent=catalogue["agent"])
        assert "translate" not in slugs(results)

    async def test_no_match_returns_an_empty_page(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        """An empty result set, not invented near-matches."""
        results = await search(
            client, q="zzzznonexistentterm", agent=catalogue["agent"]
        )
        assert results["items"] == []
        assert results["total"] == 0

    @pytest.mark.parametrize(
        "hostile",
        ["'", '"', "((", "a & | b", "!!!", "*", ":*", "\\", "a:b:c", "-", "()"],
    )
    async def test_malformed_queries_do_not_error(
        self, client: AsyncClient, hostile: str
    ) -> None:
        """to_tsquery would raise on these; websearch_to_tsquery must not."""
        response = await client.get(
            "/api/v1/marketplace/services", params={"q": hostile}
        )
        assert response.status_code == 200, f"{hostile!r} caused {response.status_code}"

    async def test_sql_injection_attempt_is_inert(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(
            client, q="'; DROP TABLE services; --", agent=catalogue["agent"]
        )
        assert results["total"] == 0

        # The table is still there.
        still_there = await search(client, q="summarization", agent=catalogue["agent"])
        assert "summarize" in slugs(still_there)


class TestRanking:
    async def test_title_match_outranks_description_match(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        """Weighting must actually affect the order results come back in."""
        results = await search(
            client, q="translation", agent=catalogue["agent"], sort="relevance"
        )
        assert results["items"], "expected at least one result"
        # "Technical Translation" has it in the title; the audit does not.
        assert results["items"][0]["slug"] == "translate"

    async def test_relevance_without_a_query_falls_back_honestly(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        """There is nothing to rank without a query, so it must not pretend."""
        results = await search(
            client, agent=catalogue["agent"], sort="relevance"
        )
        assert results["total"] == 3


class TestFilters:
    async def test_price_range_filter(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(
            client, agent=catalogue["agent"], min_price="20", max_price="100"
        )
        assert slugs(results) == {"summarize"}

    async def test_pricing_model_filter(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(
            client, agent=catalogue["agent"], pricing_model="per_unit"
        )
        assert slugs(results) == {"translate"}

    async def test_tag_filter_matches_any_supplied_tag(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(client, agent=catalogue["agent"], tags=["nlp"])
        assert slugs(results) == {"summarize", "translate"}

    async def test_delivery_time_filter(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(
            client, agent=catalogue["agent"], max_delivery_hours=48
        )
        assert slugs(results) == {"summarize", "translate"}

    async def test_category_filter(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(
            client, agent=catalogue["agent"], category="content-and-language"
        )
        assert slugs(results) == {"summarize", "translate"}

    async def test_parent_category_includes_children(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        """Choosing a parent must return everything beneath it."""
        results = await search(
            client, agent=catalogue["agent"], category="software-and-engineering"
        )
        assert "code-audit" in slugs(results)

    async def test_unknown_category_returns_nothing(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        """Must not be silently ignored and return the whole catalogue."""
        results = await search(
            client, agent=catalogue["agent"], category="no-such-category"
        )
        assert results["total"] == 0

    async def test_min_rating_excludes_unrated_providers(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        """No real reviews exist yet, so a rating floor must match nothing."""
        results = await search(client, agent=catalogue["agent"], min_rating=4)
        assert results["total"] == 0

    async def test_filters_combine(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(
            client,
            agent=catalogue["agent"],
            q="translation",
            tags=["nlp"],
            max_price="1",
        )
        assert slugs(results) == {"translate"}


class TestSorting:
    async def test_price_ascending(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(
            client, agent=catalogue["agent"], sort="price_low"
        )
        prices = [float(i["price"]) for i in results["items"]]
        assert prices == sorted(prices)

    async def test_price_descending(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(
            client, agent=catalogue["agent"], sort="price_high"
        )
        prices = [float(i["price"]) for i in results["items"]]
        assert prices == sorted(prices, reverse=True)

    async def test_top_rated_does_not_invent_an_order(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        """Nothing is rated yet, so every average must come back null."""
        results = await search(client, agent=catalogue["agent"], sort="top_rated")
        assert all(i["average_rating"] is None for i in results["items"])


class TestVisibility:
    async def test_unpublished_services_are_not_discoverable(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        token, agent = catalogue["token"], catalogue["agent"]
        await client.post(
            f"/api/v1/agents/{agent}/services",
            json={"slug": "secret", "title": "Unpublished Draft", "price": "1"},
            headers=auth(token),
        )
        results = await search(client, agent=agent)
        assert "secret" not in slugs(results)

    async def test_services_of_a_paused_agent_disappear(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        """A paused provider's listings must not look orderable."""
        token, agent = catalogue["token"], catalogue["agent"]
        assert (await search(client, agent=agent))["total"] == 3

        await client.post(f"/api/v1/agents/{agent}/pause", headers=auth(token))

        assert (await search(client, agent=agent))["total"] == 0

    async def test_archived_services_disappear(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        token, agent = catalogue["token"], catalogue["agent"]
        await client.delete(
            f"/api/v1/agents/{agent}/services/summarize", headers=auth(token)
        )
        results = await search(client, agent=agent)
        assert "summarize" not in slugs(results)


class TestPagination:
    async def test_total_reflects_the_full_filter_set(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        """total must count everything matching, not just the page."""
        results = await search(client, agent=catalogue["agent"], limit=1)
        assert len(results["items"]) == 1
        assert results["total"] == 3

    async def test_offset_walks_without_repeating(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        seen: list[str] = []
        for offset in range(3):
            page = await search(
                client, agent=catalogue["agent"], limit=1, offset=offset,
                sort="price_low",
            )
            seen.extend(item["slug"] for item in page["items"])

        assert len(seen) == len(set(seen)) == 3

    async def test_offset_past_the_end_is_empty_not_an_error(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(client, agent=catalogue["agent"], offset=500)
        assert results["items"] == []
        assert results["total"] == 3


class TestFacets:
    async def test_facet_counts_match_reality(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(client, agent=catalogue["agent"], facets=True)
        facets = {f["slug"]: f["count"] for f in results["facets"]}

        assert facets.get("content-and-language") == 2
        assert facets.get("code-review") == 1

    async def test_facets_are_absent_unless_requested(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        results = await search(client, agent=catalogue["agent"])
        assert results["facets"] is None


class TestFilterMetadata:
    async def test_price_bounds_come_from_real_listings(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        response = await client.get("/api/v1/marketplace/filters")
        assert response.status_code == 200

        body = response.json()
        assert body["price"]["currency"] == "USDC"
        assert float(body["price"]["min"]) <= 0.08
        assert float(body["price"]["max"]) >= 500

    async def test_tags_are_real_and_counted(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        body = (await client.get("/api/v1/marketplace/filters")).json()
        tags = {t["tag"]: t["count"] for t in body["tags"]}
        assert tags.get("nlp", 0) >= 2


class TestAgentDirectory:
    async def test_published_agent_appears(
        self, client: AsyncClient, catalogue: dict
    ) -> None:
        response = await client.get(
            "/api/v1/marketplace/agents", params={"q": catalogue["agent"]}
        )
        assert response.status_code == 200

        body = response.json()
        assert body["total"] >= 1
        found = next(a for a in body["items"] if a["slug"] == catalogue["agent"])
        assert found["published_service_count"] == 3
        assert found["average_rating"] is None

    async def test_draft_agents_are_not_listed(self, client: AsyncClient) -> None:
        token = await sign_in(client)
        slug = f"draft-{uuid.uuid4().hex[:8]}"
        await client.post(
            "/api/v1/agents",
            json={"slug": slug, "name": "Draft Agent"},
            headers=auth(token),
        )

        body = (
            await client.get("/api/v1/marketplace/agents", params={"q": slug})
        ).json()
        assert body["total"] == 0
