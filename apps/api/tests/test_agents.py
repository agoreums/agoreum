"""Agent registration, identity, and service publishing tests.

Runs against a real database and a real signed-in session, so authorisation is
exercised through the same path a client uses rather than by calling the service
layer directly.
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
    eng = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
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


async def sign_in(client: AsyncClient) -> tuple[str, dict]:
    """Create a fresh account and return (access_token, user)."""
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
    return body["tokens"]["access_token"], body["user"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def unique_slug(prefix: str = "agent") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def create_agent(client: AsyncClient, token: str, **overrides) -> dict:
    payload = {
        "slug": unique_slug(),
        "name": "Atlas Research",
        "tagline": "Structured research from public sources",
        **overrides,
    }
    response = await client.post("/api/v1/agents", json=payload, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


async def wallet_id_for(client: AsyncClient, token: str) -> str:
    wallets = (await client.get("/api/v1/auth/me/wallets", headers=auth(token))).json()
    return wallets[0]["id"]


async def publishable_agent(client: AsyncClient, token: str) -> dict:
    """An agent with a verified payout wallet, published and ready to trade."""
    agent = await create_agent(client, token)
    wid = await wallet_id_for(client, token)
    await client.put(
        f"/api/v1/agents/{agent['slug']}/payout-wallet",
        json={"wallet_id": wid},
        headers=auth(token),
    )
    published = await client.post(
        f"/api/v1/agents/{agent['slug']}/publish", headers=auth(token)
    )
    assert published.status_code == 200, published.text
    return published.json()


class TestAgentRegistration:
    async def test_registering_an_agent_starts_it_as_a_draft(
        self, client: AsyncClient
    ) -> None:
        """A new agent is never publicly listed until it is deliberately published."""
        token, user = await sign_in(client)
        agent = await create_agent(client, token)

        assert agent["status"] == "draft"
        assert agent["owner_id"] == user["id"]
        assert agent["verification_tier"] == "unverified"
        assert agent["published_at"] is None

    async def test_new_agent_has_no_fabricated_activity(
        self, client: AsyncClient
    ) -> None:
        """Counters start at zero and the rating is null, not a flattering default."""
        token, _ = await sign_in(client)
        agent = await create_agent(client, token)

        assert agent["completed_orders"] == 0
        assert agent["review_count"] == 0
        assert agent["average_rating"] is None

    async def test_registration_requires_authentication(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/agents", json={"slug": unique_slug(), "name": "Anon"}
        )
        assert response.status_code == 401

    async def test_duplicate_slug_is_rejected(self, client: AsyncClient) -> None:
        token, _ = await sign_in(client)
        agent = await create_agent(client, token)

        response = await client.post(
            "/api/v1/agents",
            json={"slug": agent["slug"], "name": "Impostor"},
            headers=auth(token),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "slug_taken"

    @pytest.mark.parametrize(
        "slug", ["admin", "agoreum", "api", "support", "official", "settings"]
    )
    async def test_reserved_slugs_are_refused(
        self, client: AsyncClient, slug: str
    ) -> None:
        """Names that would impersonate the platform or collide with routes."""
        token, _ = await sign_in(client)
        response = await client.post(
            "/api/v1/agents", json={"slug": slug, "name": "X"}, headers=auth(token)
        )
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "slug", ["UPPER", "has space", "-leading", "a", "sym$bol", "trailing-"]
    )
    async def test_malformed_slugs_are_refused(
        self, client: AsyncClient, slug: str
    ) -> None:
        token, _ = await sign_in(client)
        response = await client.post(
            "/api/v1/agents", json={"slug": slug, "name": "X"}, headers=auth(token)
        )
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "http://insecure.example",
        ],
    )
    async def test_non_https_urls_are_refused(
        self, client: AsyncClient, url: str
    ) -> None:
        """A javascript: or data: URL would become an XSS vector once rendered."""
        token, _ = await sign_in(client)
        response = await client.post(
            "/api/v1/agents",
            json={"slug": unique_slug(), "name": "X", "website_url": url},
            headers=auth(token),
        )
        assert response.status_code == 422


class TestOwnershipIsolation:
    async def test_another_user_cannot_update_your_agent(
        self, client: AsyncClient
    ) -> None:
        owner_token, _ = await sign_in(client)
        agent = await create_agent(client, owner_token)

        attacker_token, _ = await sign_in(client)
        response = await client.patch(
            f"/api/v1/agents/{agent['slug']}",
            json={"name": "Hijacked"},
            headers=auth(attacker_token),
        )
        # 404, not 403: a stranger learns nothing about what exists.
        assert response.status_code == 404

    async def test_another_user_cannot_publish_your_agent(
        self, client: AsyncClient
    ) -> None:
        owner_token, _ = await sign_in(client)
        agent = await create_agent(client, owner_token)

        attacker_token, _ = await sign_in(client)
        response = await client.post(
            f"/api/v1/agents/{agent['slug']}/publish", headers=auth(attacker_token)
        )
        assert response.status_code == 404

    async def test_draft_agents_are_invisible_to_strangers(
        self, client: AsyncClient
    ) -> None:
        owner_token, _ = await sign_in(client)
        agent = await create_agent(client, owner_token)

        anonymous = await client.get(f"/api/v1/agents/{agent['slug']}")
        assert anonymous.status_code == 404

        owner_view = await client.get(
            f"/api/v1/agents/{agent['slug']}", headers=auth(owner_token)
        )
        assert owner_view.status_code == 200

    async def test_mine_lists_only_your_own_agents(
        self, client: AsyncClient
    ) -> None:
        first_token, _ = await sign_in(client)
        mine = await create_agent(client, first_token)

        second_token, _ = await sign_in(client)
        await create_agent(client, second_token)

        listing = (
            await client.get("/api/v1/agents/mine", headers=auth(first_token))
        ).json()
        assert [a["slug"] for a in listing] == [mine["slug"]]


class TestPayoutAndPublishing:
    async def test_publishing_requires_a_payout_wallet(
        self, client: AsyncClient
    ) -> None:
        """An agent that cannot be paid must not be advertised as available."""
        token, _ = await sign_in(client)
        agent = await create_agent(client, token)

        response = await client.post(
            f"/api/v1/agents/{agent['slug']}/publish", headers=auth(token)
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "payout_wallet_required"

    async def test_publishing_succeeds_with_a_verified_wallet(
        self, client: AsyncClient
    ) -> None:
        token, _ = await sign_in(client)
        agent = await publishable_agent(client, token)

        assert agent["status"] == "active"
        assert agent["published_at"] is not None
        assert agent["payout_address"] is not None

    async def test_cannot_use_another_users_wallet_for_payout(
        self, client: AsyncClient
    ) -> None:
        """Payout redirection would be the most valuable attack on this system."""
        victim_token, _ = await sign_in(client)
        victim_wallet = await wallet_id_for(client, victim_token)

        attacker_token, _ = await sign_in(client)
        agent = await create_agent(client, attacker_token)

        response = await client.put(
            f"/api/v1/agents/{agent['slug']}/payout-wallet",
            json={"wallet_id": victim_wallet},
            headers=auth(attacker_token),
        )
        assert response.status_code == 404

    async def test_published_agent_is_publicly_visible(
        self, client: AsyncClient
    ) -> None:
        token, _ = await sign_in(client)
        agent = await publishable_agent(client, token)

        response = await client.get(f"/api/v1/agents/{agent['slug']}")
        assert response.status_code == 200
        assert response.json()["slug"] == agent["slug"]

    async def test_pausing_hides_an_agent_from_the_public(
        self, client: AsyncClient
    ) -> None:
        token, _ = await sign_in(client)
        agent = await publishable_agent(client, token)

        paused = await client.post(
            f"/api/v1/agents/{agent['slug']}/pause", headers=auth(token)
        )
        assert paused.json()["status"] == "paused"


class TestSlugAvailability:
    async def test_taken_slug_reports_unavailable(self, client: AsyncClient) -> None:
        token, _ = await sign_in(client)
        agent = await create_agent(client, token)

        response = await client.get(
            "/api/v1/agents/slug-available", params={"slug": agent["slug"]}
        )
        assert response.json()["available"] is False

    async def test_free_slug_reports_available(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/agents/slug-available", params={"slug": unique_slug("free")}
        )
        assert response.json()["available"] is True

    async def test_reserved_slug_reports_unavailable(
        self, client: AsyncClient
    ) -> None:
        response = await client.get(
            "/api/v1/agents/slug-available", params={"slug": "admin"}
        )
        assert response.json()["available"] is False


class TestDomainVerification:
    async def test_challenge_returns_actionable_instructions(
        self, client: AsyncClient
    ) -> None:
        token, _ = await sign_in(client)
        agent = await create_agent(client, token)

        response = await client.post(
            f"/api/v1/agents/{agent['slug']}/domain-challenges",
            json={"domain": "example.com", "method": "dns_txt"},
            headers=auth(token),
        )
        assert response.status_code == 201
        body = response.json()
        assert body["token"].startswith("agoreum-verification=")
        assert "TXT" in body["instructions"]
        assert body["verified_at"] is None

    @pytest.mark.parametrize(
        ("supplied", "expected"),
        [
            ("https://example.com/path", "example.com"),
            ("www.example.com", "example.com"),
            ("EXAMPLE.COM", "example.com"),
            ("http://example.com:8080", "example.com"),
        ],
    )
    async def test_domain_input_is_normalised(
        self, client: AsyncClient, supplied: str, expected: str
    ) -> None:
        token, _ = await sign_in(client)
        agent = await create_agent(client, token)

        response = await client.post(
            f"/api/v1/agents/{agent['slug']}/domain-challenges",
            json={"domain": supplied},
            headers=auth(token),
        )
        assert response.json()["domain"] == expected

    async def test_verification_fails_without_a_published_token(
        self, client: AsyncClient
    ) -> None:
        """A real DNS lookup runs; an unproven domain must not be granted."""
        token, _ = await sign_in(client)
        agent = await create_agent(client, token)

        challenge = (
            await client.post(
                f"/api/v1/agents/{agent['slug']}/domain-challenges",
                json={"domain": "example.com", "method": "dns_txt"},
                headers=auth(token),
            )
        ).json()

        response = await client.post(
            f"/api/v1/agents/{agent['slug']}/domain-challenges/"
            f"{challenge['id']}/verify",
            headers=auth(token),
        )
        assert response.status_code == 409

        after = (
            await client.get(
                f"/api/v1/agents/{agent['slug']}", headers=auth(token)
            )
        ).json()
        assert after["verification_tier"] == "unverified"
        assert after["verified_domain"] is None

    async def test_another_user_cannot_start_a_challenge_on_your_agent(
        self, client: AsyncClient
    ) -> None:
        owner_token, _ = await sign_in(client)
        agent = await create_agent(client, owner_token)

        attacker_token, _ = await sign_in(client)
        response = await client.post(
            f"/api/v1/agents/{agent['slug']}/domain-challenges",
            json={"domain": "attacker.example"},
            headers=auth(attacker_token),
        )
        assert response.status_code == 404


class TestServicePublishing:
    async def test_service_starts_as_a_draft(self, client: AsyncClient) -> None:
        token, _ = await sign_in(client)
        agent = await publishable_agent(client, token)

        response = await client.post(
            f"/api/v1/agents/{agent['slug']}/services",
            json={
                "slug": "summarize",
                "title": "Document Summarization",
                "pricing_model": "fixed",
                "price": "25.50",
            },
            headers=auth(token),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "draft"
        assert body["completed_order_count"] == 0
        assert body["average_rating"] is None

    async def test_publishing_a_service_makes_it_visible(
        self, client: AsyncClient
    ) -> None:
        token, _ = await sign_in(client)
        agent = await publishable_agent(client, token)

        await client.post(
            f"/api/v1/agents/{agent['slug']}/services",
            json={
                "slug": "summarize",
                "title": "Document Summarization",
                "price": "25.50",
            },
            headers=auth(token),
        )
        published = await client.post(
            f"/api/v1/agents/{agent['slug']}/services/summarize/publish",
            headers=auth(token),
        )
        assert published.status_code == 200
        assert published.json()["status"] == "published"

        anonymous = await client.get(
            f"/api/v1/agents/{agent['slug']}/services/summarize"
        )
        assert anonymous.status_code == 200

    async def test_draft_service_is_invisible_to_strangers(
        self, client: AsyncClient
    ) -> None:
        token, _ = await sign_in(client)
        agent = await publishable_agent(client, token)
        await client.post(
            f"/api/v1/agents/{agent['slug']}/services",
            json={"slug": "hidden", "title": "Hidden Service", "price": "10"},
            headers=auth(token),
        )

        response = await client.get(f"/api/v1/agents/{agent['slug']}/services/hidden")
        assert response.status_code == 404

    async def test_service_cannot_be_published_under_an_unpublished_agent(
        self, client: AsyncClient
    ) -> None:
        token, _ = await sign_in(client)
        agent = await create_agent(client, token)  # still a draft

        await client.post(
            f"/api/v1/agents/{agent['slug']}/services",
            json={"slug": "svc", "title": "Some Service", "price": "10"},
            headers=auth(token),
        )
        response = await client.post(
            f"/api/v1/agents/{agent['slug']}/services/svc/publish",
            headers=auth(token),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "agent_not_published"

    async def test_another_user_cannot_add_services_to_your_agent(
        self, client: AsyncClient
    ) -> None:
        owner_token, _ = await sign_in(client)
        agent = await publishable_agent(client, owner_token)

        attacker_token, _ = await sign_in(client)
        response = await client.post(
            f"/api/v1/agents/{agent['slug']}/services",
            json={"slug": "malicious", "title": "Malicious Service", "price": "1"},
            headers=auth(attacker_token),
        )
        assert response.status_code == 404


class TestServicePricingValidation:
    @pytest_asyncio.fixture
    async def agent_slug(self, client: AsyncClient) -> tuple[str, str]:
        token, _ = await sign_in(client)
        agent = await publishable_agent(client, token)
        return agent["slug"], token

    async def test_price_is_required_unless_negotiated(
        self, client: AsyncClient, agent_slug: tuple[str, str]
    ) -> None:
        slug, token = agent_slug
        response = await client.post(
            f"/api/v1/agents/{slug}/services",
            json={"slug": "no-price", "title": "No Price", "pricing_model": "fixed"},
            headers=auth(token),
        )
        assert response.status_code == 422

    async def test_negotiated_pricing_may_omit_a_price(
        self, client: AsyncClient, agent_slug: tuple[str, str]
    ) -> None:
        slug, token = agent_slug
        response = await client.post(
            f"/api/v1/agents/{slug}/services",
            json={
                "slug": "bespoke",
                "title": "Bespoke Engagement",
                "pricing_model": "negotiated",
            },
            headers=auth(token),
        )
        assert response.status_code == 201

    async def test_per_unit_pricing_requires_a_unit(
        self, client: AsyncClient, agent_slug: tuple[str, str]
    ) -> None:
        slug, token = agent_slug
        response = await client.post(
            f"/api/v1/agents/{slug}/services",
            json={
                "slug": "per-unit",
                "title": "Per Unit Work",
                "pricing_model": "per_unit",
                "price": "0.50",
            },
            headers=auth(token),
        )
        assert response.status_code == 422

    async def test_price_beyond_token_precision_is_refused(
        self, client: AsyncClient, agent_slug: tuple[str, str]
    ) -> None:
        """USDC has 6 decimals; more precision would be truncated on chain."""
        slug, token = agent_slug
        response = await client.post(
            f"/api/v1/agents/{slug}/services",
            json={
                "slug": "too-precise",
                "title": "Too Precise",
                "price": "1.0000001",
            },
            headers=auth(token),
        )
        assert response.status_code == 422

    async def test_negative_and_zero_prices_are_refused(
        self, client: AsyncClient, agent_slug: tuple[str, str]
    ) -> None:
        slug, token = agent_slug
        for bad in ["-5", "0"]:
            response = await client.post(
                f"/api/v1/agents/{slug}/services",
                json={"slug": f"bad{bad}", "title": "Bad Price", "price": bad},
                headers=auth(token),
            )
            assert response.status_code == 422, f"price {bad} was accepted"

    async def test_tags_are_normalised_and_deduplicated(
        self, client: AsyncClient, agent_slug: tuple[str, str]
    ) -> None:
        slug, token = agent_slug
        response = await client.post(
            f"/api/v1/agents/{slug}/services",
            json={
                "slug": "tagged",
                "title": "Tagged Service",
                "price": "10",
                "tags": ["NLP", "nlp", "  Research  ", ""],
            },
            headers=auth(token),
        )
        assert response.json()["tags"] == ["nlp", "research"]


class TestCategories:
    async def test_category_tree_is_returned(self, client: AsyncClient) -> None:
        """Seeded taxonomy, not fabricated marketplace content."""
        response = await client.get("/api/v1/categories")
        assert response.status_code == 200

        tree = response.json()
        assert tree, "no categories seeded"
        assert all(c["parent_id"] is None for c in tree)
        assert any(c["children"] for c in tree)
