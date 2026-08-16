"""Reputation, review, notification and dashboard tests.

The point of most of these is negative: proving that reputation *cannot* be
built without real, settled trade behind it. A marketplace whose scores can be
manufactured is worse than one with no scores at all.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

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
from app.modules.reputation import service as reputation

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
        # Generous on purpose. The earlier value was 5 seconds, to "fail fast
        # when nothing is listening", but that is not what makes it fast:
        # a closed port on loopback refuses the connection in about two
        # seconds whatever the timeout, measured both ways. The timeout only
        # bites when a database *is* listening and slow, which on a loaded
        # machine turned into an error in one full run and a silently skipped
        # test in the next. A skipped test is the failure this project treats
        # as serious, so the setting that caused it is the one that was wrong.
        connect_args={"timeout": 30},
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


async def sign_in(client: AsyncClient) -> tuple[str, dict]:
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


async def build_provider(client: AsyncClient) -> tuple[str, str, str]:
    """A signed-in provider with a published agent and service."""
    token, _ = await sign_in(client)
    slug = f"agent-{uuid.uuid4().hex[:10]}"

    await client.post(
        "/api/v1/agents", json={"slug": slug, "name": "Provider"}, headers=auth(token)
    )
    wallets = (await client.get("/api/v1/auth/me/wallets", headers=auth(token))).json()
    await client.put(
        f"/api/v1/agents/{slug}/payout-wallet",
        json={"wallet_id": wallets[0]["id"]},
        headers=auth(token),
    )
    await client.post(f"/api/v1/agents/{slug}/publish", headers=auth(token))

    await client.post(
        f"/api/v1/agents/{slug}/services",
        json={"slug": "work", "title": "Some Real Work", "price": "100"},
        headers=auth(token),
    )
    await client.post(
        f"/api/v1/agents/{slug}/services/work/publish", headers=auth(token)
    )

    service = (
        await client.get(f"/api/v1/agents/{slug}/services/work")
    ).json()
    return token, slug, service["id"]


class TestReputationRequiresRealActivity:
    async def test_new_agent_has_no_score_and_says_why(
        self, client: AsyncClient
    ) -> None:
        """Unrated is not badly rated. The score is null, with an explanation."""
        _, slug, _ = await build_provider(client)

        report = (await client.get(f"/api/v1/agents/{slug}/reputation")).json()

        assert report["score"] is None
        assert report["completed_orders"] == 0
        assert report["average_rating"] is None
        assert Decimal(report["total_volume"]) == 0
        assert "not completed any settled orders" in report["note"]

    async def test_report_exposes_the_inputs_behind_the_score(
        self, client: AsyncClient
    ) -> None:
        """A provider is entitled to see why their score is what it is."""
        _, slug, _ = await build_provider(client)
        report = (await client.get(f"/api/v1/agents/{slug}/reputation")).json()

        for field in (
            "completed_orders", "cancelled_orders", "disputed_orders",
            "disputes_lost", "review_count", "total_volume",
            "algorithm_version",
        ):
            assert field in report

    async def test_placing_an_order_alone_earns_no_reputation(
        self, client: AsyncClient
    ) -> None:
        """An order that was never funded or settled must count for nothing."""
        _, slug, service_id = await build_provider(client)
        buyer_token, _ = await sign_in(client)

        created = await client.post(
            "/api/v1/orders", json={"service_id": service_id}, headers=auth(buyer_token)
        )
        assert created.status_code == 201

        report = (await client.get(f"/api/v1/agents/{slug}/reputation")).json()
        assert report["completed_orders"] == 0
        assert report["score"] is None


class TestReviewsRequireSettledOrders:
    async def test_cannot_review_an_unfunded_order(
        self, client: AsyncClient
    ) -> None:
        _, _, service_id = await build_provider(client)
        buyer_token, _ = await sign_in(client)

        order = (
            await client.post(
                "/api/v1/orders",
                json={"service_id": service_id},
                headers=auth(buyer_token),
            )
        ).json()

        response = await client.post(
            "/api/v1/reviews",
            json={"order_id": order["id"], "rating": 5},
            headers=auth(buyer_token),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "order_not_completed"

    async def test_cannot_review_an_order_you_did_not_place(
        self, client: AsyncClient
    ) -> None:
        _, _, service_id = await build_provider(client)
        buyer_token, _ = await sign_in(client)
        order = (
            await client.post(
                "/api/v1/orders",
                json={"service_id": service_id},
                headers=auth(buyer_token),
            )
        ).json()

        stranger_token, _ = await sign_in(client)
        response = await client.post(
            "/api/v1/reviews",
            json={"order_id": order["id"], "rating": 5},
            headers=auth(stranger_token),
        )
        # A stranger cannot even see the order exists.
        assert response.status_code == 404

    async def test_completed_order_without_settlement_cannot_be_reviewed(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """The strongest guarantee: marking an order complete in the database is
        not enough. Without an escrow that actually released, no review is
        possible, so reputation cannot be built on unpaid work."""
        _, _, service_id = await build_provider(client)
        buyer_token, _ = await sign_in(client)

        order = (
            await client.post(
                "/api/v1/orders",
                json={"service_id": service_id},
                headers=auth(buyer_token),
            )
        ).json()

        # Force the order to look complete while no escrow exists at all.
        await db.execute(
            sa.text(
                "UPDATE orders SET status = 'completed', funded_at = now(),"
                " completed_at = now() WHERE id = :oid"
            ),
            {"oid": uuid.UUID(order["id"])},
        )

        response = await client.post(
            "/api/v1/reviews",
            json={"order_id": order["id"], "rating": 5},
            headers=auth(buyer_token),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "order_not_settled"

    async def test_pending_reviews_lists_only_settled_orders(
        self, client: AsyncClient
    ) -> None:
        _, _, service_id = await build_provider(client)
        buyer_token, _ = await sign_in(client)
        await client.post(
            "/api/v1/orders", json={"service_id": service_id}, headers=auth(buyer_token)
        )

        pending = (
            await client.get("/api/v1/reviews/pending", headers=auth(buyer_token))
        ).json()
        assert pending == []

    @pytest.mark.parametrize("rating", [0, 6, -1, 100])
    async def test_ratings_outside_one_to_five_are_rejected(
        self, client: AsyncClient, rating: int
    ) -> None:
        buyer_token, _ = await sign_in(client)
        response = await client.post(
            "/api/v1/reviews",
            json={"order_id": str(uuid.uuid4()), "rating": rating},
            headers=auth(buyer_token),
        )
        assert response.status_code == 422


class TestScoreComputation:
    """The scoring function itself, over constructed inputs."""

    def _inputs(self, **overrides) -> reputation.ReputationInputs:
        base = {
            "completed_orders": 10,
            "cancelled_orders": 0,
            "disputed_orders": 0,
            "disputes_lost": 0,
            "review_count": 10,
            "rating_sum": 50,
            "total_volume": Decimal("1000"),
            "median_delivery_hours": Decimal("24"),
            "on_time_delivery_rate": Decimal("1"),
        }
        return reputation.ReputationInputs(**{**base, **overrides})

    async def test_no_score_below_the_history_threshold(self) -> None:
        """A number from one or two orders is noise presented as a fact."""
        assert reputation.compute_score(self._inputs(completed_orders=2)) is None

    async def test_perfect_history_scores_full_marks(self) -> None:
        assert reputation.compute_score(self._inputs()) == Decimal("100.00")

    async def test_poor_ratings_lower_the_score(self) -> None:
        good = reputation.compute_score(self._inputs())
        bad = reputation.compute_score(self._inputs(rating_sum=10))  # all 1-star
        assert bad < good

    async def test_cancellations_lower_reliability(self) -> None:
        clean = reputation.compute_score(self._inputs())
        messy = reputation.compute_score(self._inputs(cancelled_orders=10))
        assert messy < clean

    async def test_raising_a_dispute_is_not_itself_a_fault(self) -> None:
        """Only lost disputes count against a provider."""
        neutral = reputation.compute_score(
            self._inputs(disputed_orders=5, disputes_lost=0)
        )
        assert neutral == reputation.compute_score(self._inputs())

    async def test_lost_disputes_lower_the_score(self) -> None:
        won = reputation.compute_score(self._inputs(disputed_orders=4, disputes_lost=0))
        lost = reputation.compute_score(
            self._inputs(disputed_orders=4, disputes_lost=4)
        )
        assert lost < won

    async def test_settled_work_without_reviews_is_treated_as_neutral(self) -> None:
        """Not assumed good, not assumed bad."""
        score = reputation.compute_score(self._inputs(review_count=0, rating_sum=0))
        assert score is not None
        assert Decimal("50") < score < Decimal("90")

    async def test_score_never_leaves_the_zero_to_hundred_range(self) -> None:
        worst = reputation.compute_score(
            self._inputs(
                rating_sum=10, cancelled_orders=50, disputed_orders=10,
                disputes_lost=10,
            )
        )
        assert worst is not None
        assert Decimal("0") <= worst <= Decimal("100")


class TestNotifications:
    async def test_inbox_starts_empty(self, client: AsyncClient) -> None:
        token, _ = await sign_in(client)
        body = (
            await client.get("/api/v1/notifications", headers=auth(token))
        ).json()

        assert body["items"] == []
        assert body["total"] == 0
        assert body["unread"] == 0

    async def test_email_status_is_reported_honestly(
        self, client: AsyncClient
    ) -> None:
        """Nobody should have to guess why a message did not arrive."""
        body = (await client.get("/api/v1/notifications/email-status")).json()

        assert isinstance(body["enabled"], bool)
        if not body["enabled"]:
            assert body["reason"]

    async def test_email_is_disabled_by_default(self) -> None:
        """Running the suite must not put real messages in real inboxes."""
        from app.modules.notifications import service as notifications

        enabled, reason = notifications.email_sending_available()
        if settings.EMAIL_SENDING_ENABLED:
            pytest.skip("email sending is deliberately enabled in this environment")
        assert enabled is False
        assert reason

    async def test_security_notifications_cannot_be_disabled(
        self, client: AsyncClient
    ) -> None:
        """A user must always learn about a new sign-in or a payout change."""
        token, _ = await sign_in(client)

        response = await client.put(
            "/api/v1/notifications/preferences",
            json={"category": "security", "channel": "email", "enabled": False},
            headers=auth(token),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "category_not_suppressible"

    async def test_other_categories_can_be_disabled(
        self, client: AsyncClient
    ) -> None:
        token, _ = await sign_in(client)
        response = await client.put(
            "/api/v1/notifications/preferences",
            json={"category": "order", "channel": "email", "enabled": False},
            headers=auth(token),
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is False

    async def test_notifications_require_authentication(
        self, client: AsyncClient
    ) -> None:
        assert (await client.get("/api/v1/notifications")).status_code == 401


class TestDashboards:
    async def test_new_buyer_sees_honest_zeros(self, client: AsyncClient) -> None:
        token, _ = await sign_in(client)
        body = (await client.get("/api/v1/dashboard/buyer", headers=auth(token))).json()

        assert body["active_orders"] == 0
        assert body["completed_orders"] == 0
        assert body["total_spent"] == "0"
        assert body["recent_orders"] == []

    async def test_account_without_agents_sees_nulls_not_fake_totals(
        self, client: AsyncClient
    ) -> None:
        token, _ = await sign_in(client)
        body = (
            await client.get("/api/v1/dashboard/provider", headers=auth(token))
        ).json()

        assert body["agents"] == 0
        # Never earned anything is null, not a measured zero.
        assert body["total_earned"] is None
        assert body["average_rating"] is None

    async def test_provider_counts_reflect_real_records(
        self, client: AsyncClient
    ) -> None:
        token, _, _ = await build_provider(client)
        body = (
            await client.get("/api/v1/dashboard/provider", headers=auth(token))
        ).json()

        assert body["agents"] == 1
        assert body["published_agents"] == 1
        assert body["published_services"] == 1
        assert body["completed_orders"] == 0
        assert body["total_earned"] is None

    async def test_admin_dashboard_requires_an_admin(
        self, client: AsyncClient
    ) -> None:
        token, _ = await sign_in(client)
        response = await client.get("/api/v1/dashboard/admin", headers=auth(token))
        assert response.status_code == 403

    async def test_dashboards_require_authentication(
        self, client: AsyncClient
    ) -> None:
        for path in ("buyer", "provider", "admin"):
            assert (await client.get(f"/api/v1/dashboard/{path}")).status_code == 401


class TestReputationCannotBeSelfDealt:
    """The one property the whole product rests on.

    Agoreum's claim against the rest of the ecosystem is narrow and entirely
    structural: a score here cannot exist without a settled payment behind it,
    measured against ERC-8004 records where between 98.7% and 100% carry no
    proof of payment at all. That claim survives only if the payment was
    between two parties who are not the same interest. A settled payment from
    yourself to yourself is a real transaction and a fake reputation.

    Until these tests were written, one branch of `create_order` was the only
    thing in the entire system enforcing it, and nothing exercised that branch.
    Reputation itself did not re-establish the property, so any order arriving
    by another route counted in full: an admin action, a backfill, an import, a
    future endpoint, or simply the buyer joining the provider's organization
    after placing an order, which the creation check has no way to see because
    it has already run.
    """

    async def test_ordering_from_your_own_agent_is_refused(
        self, client: AsyncClient
    ) -> None:
        """The guard that had no test.

        Refused with a named code rather than a generic conflict, because the
        SDKs and the interface both need to explain this to somebody who is
        very likely not attacking anything and simply wants to test their own
        service.
        """
        token, _, service_id = await build_provider(client)

        resp = await client.post(
            "/api/v1/orders",
            json={"service_id": service_id, "quantity": 1},
            headers=auth(token),
        )

        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "self_dealing"

    async def test_a_settled_order_from_inside_the_org_earns_nothing(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """Defence in depth, written as the attack rather than as a unit test.

        The order is inserted directly, which is the whole point: it models
        every route that does not pass through `create_order`, and asserts the
        score does not move rather than asserting that some function was
        called.
        """
        token, slug, service_id = await build_provider(client)
        me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()

        agent = (
            await db.execute(
                sa.text("SELECT id, org_id FROM agents WHERE slug = :slug"),
                {"slug": slug},
            )
        ).one()

        # Three settled orders, which is MIN_ORDERS_FOR_SCORE, so a score would
        # be published if any of this counted.
        for i in range(reputation.MIN_ORDERS_FOR_SCORE):
            order_id = uuid.uuid4()
            await db.execute(
                sa.text(
                    "INSERT INTO orders (id, reference, buyer_id, provider_agent_id,"
                    " service_id, status, quantity, unit_price, subtotal,"
                    " platform_fee, total_amount, currency, platform_fee_bps,"
                    " created_at, updated_at, funded_at, delivered_at, completed_at)"
                    " VALUES (:id, :ref, :buyer, :agent, :service, 'completed', 1,"
                    " 100, 100, 2.5, 102.5, 'USDC', 250, now(), now(), now(), now(), now())"
                ),
                {
                    "id": order_id,
                    "ref": f"SELF-{i}-{uuid.uuid4().hex[:6]}",
                    "buyer": me["id"],
                    "agent": agent.id,
                    "service": service_id,
                },
            )
            await db.execute(
                sa.text(
                    "INSERT INTO escrows (id, order_id, status, chain_id,"
                " token_address, token_symbol, token_decimals, amount,"
                " released_amount, refunded_amount, fee_amount,"
                " buyer_address, provider_address,"
                " funded_at, released_at, created_at, updated_at)"
                " VALUES (:id, :order_id, 'released', 84532,"
                " '0x036cbd53842c5426634e7929541ec2318f3dcf7e', 'USDC', 6,"
                " 100, 97.5, 0, 2.5,"
                " '0x00000000000000000000000000000000000000b0',"
                " '0x00000000000000000000000000000000000000a1',"
                " now(), now(), now(), now())"
                ),
                {"id": uuid.uuid4(), "order_id": order_id},
            )
        await db.flush()

        inputs = await reputation.gather_inputs(db, agent_id=agent.id)

        assert inputs.completed_orders == 0, (
            "orders placed by a member of the agent's own organization counted "
            "toward its reputation, which is the wash trading this platform "
            "exists to be structurally free of"
        )
        assert inputs.total_volume == 0, (
            "self-dealt settlements counted as turnover, so an agent with no "
            "arm's length trade could still advertise volume"
        )
        assert not inputs.has_enough_history

    async def test_an_arms_length_order_still_counts(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """The control, and the half that makes the test above mean anything.

        An exclusion that also removed genuine trade would pass the assertion
        above perfectly while destroying the product, so the same construction
        is repeated with an unrelated buyer and must produce the opposite
        answer.
        """
        _, slug, service_id = await build_provider(client)
        buyer_token, _ = await sign_in(client)
        buyer = (await client.get("/api/v1/auth/me", headers=auth(buyer_token))).json()

        agent = (
            await db.execute(
                sa.text("SELECT id, org_id FROM agents WHERE slug = :slug"),
                {"slug": slug},
            )
        ).one()

        order_id = uuid.uuid4()
        await db.execute(
            sa.text(
                "INSERT INTO orders (id, reference, buyer_id, provider_agent_id,"
                " service_id, status, quantity, unit_price, subtotal,"
                " platform_fee, total_amount, currency, platform_fee_bps,"
                " created_at, updated_at, funded_at, delivered_at, completed_at)"
                " VALUES (:id, :ref, :buyer, :agent, :service, 'completed', 1,"
                " 100, 100, 2.5, 102.5, 'USDC', 250, now(), now(), now(), now(), now())"
            ),
            {
                "id": order_id,
                "ref": f"ARMS-{uuid.uuid4().hex[:6]}",
                "buyer": buyer["id"],
                "agent": agent.id,
                "service": service_id,
            },
        )
        await db.execute(
            sa.text(
                "INSERT INTO escrows (id, order_id, status, chain_id,"
                " token_address, token_symbol, token_decimals, amount,"
                " released_amount, refunded_amount, fee_amount,"
                " buyer_address, provider_address,"
                " funded_at, released_at, created_at, updated_at)"
                " VALUES (:id, :order_id, 'released', 84532,"
                " '0x036cbd53842c5426634e7929541ec2318f3dcf7e', 'USDC', 6,"
                " 100, 97.5, 0, 2.5,"
                " '0x00000000000000000000000000000000000000b0',"
                " '0x00000000000000000000000000000000000000a1',"
                " now(), now(), now(), now())"
            ),
            {"id": uuid.uuid4(), "order_id": order_id},
        )
        await db.flush()

        inputs = await reputation.gather_inputs(db, agent_id=agent.id)

        assert inputs.completed_orders == 1, (
            "a genuine order from an unrelated buyer was excluded, so the "
            "self-dealing filter is destroying real reputation"
        )
        assert inputs.total_volume == Decimal("97.5")
