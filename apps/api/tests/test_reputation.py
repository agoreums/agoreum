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

class TestReputationExclusionIsOneWay:
    """An operator can subtract standing and can never hand it back.

    The case this exists for is one the platform cannot detect. An order between
    two accounts sharing no organization, no wallet and nothing else visible is
    indistinguishable from arm's length trade however well the operator knows
    otherwise, which is exactly what the settlement exercise of 2026-08-16 left
    behind in production.

    The power to say "this does not count" is dangerous in one direction only. A
    flag that can be set and cleared is a way of handing out standing: exclude a
    rival's orders, or exclude your own through a bad month and restore them
    after. So the requirement was never "an exclusion flag", it was "an exclusion
    that cannot be reversed", and these assert the reversal is impossible rather
    than merely unimplemented.
    """

    async def _settled_order(self, db, client):
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
                "ref": f"EXCL-{uuid.uuid4().hex[:6]}",
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
        return agent.id, order_id

    async def _exclude(self, db, order_id, reason):
        await db.execute(
            sa.text(
                "UPDATE orders SET reputation_excluded_at = now(),"
                " reputation_exclusion_reason = :reason WHERE id = :id"
            ),
            {"id": order_id, "reason": reason},
        )
        await db.flush()

    async def test_an_excluded_order_stops_counting(self, client, db) -> None:
        agent_id, order_id = await self._settled_order(db, client)

        before = await reputation.gather_inputs(db, agent_id=agent_id)
        assert before.completed_orders == 1, "the fixture produced no countable order"
        assert before.total_volume == Decimal("97.5")

        await self._exclude(db, order_id, "settlement path verification")

        after = await reputation.gather_inputs(db, agent_id=agent_id)
        assert after.completed_orders == 0
        assert after.total_volume == 0

    async def test_the_database_refuses_to_lift_an_exclusion(self, client, db) -> None:
        """The assertion the whole design rests on.

        Enforced by a trigger rather than by the service layer, so it holds for a
        future endpoint, an admin script, a migration, a backfill, or somebody at
        a psql prompt. This writes raw SQL for exactly that reason: going through
        the service would only prove the service behaves, which is the weaker
        claim and the one that has failed repeatedly this month.
        """
        _, order_id = await self._settled_order(db, client)
        await self._exclude(db, order_id, "first decision")

        with pytest.raises(Exception) as caught:
            await db.execute(
                sa.text(
                    "UPDATE orders SET reputation_excluded_at = NULL,"
                    " reputation_exclusion_reason = NULL WHERE id = :id"
                ),
                {"id": order_id},
            )
            await db.flush()
        assert "cannot be lifted" in str(caught.value), (
            f"the database allowed an exclusion to be lifted: {caught.value}"
        )

    async def test_the_database_refuses_to_rewrite_the_decision(self, client, db) -> None:
        """A rewritable reason is a reversible decision wearing a different hat.

        Somebody able to change the stated reason afterwards can make a contested
        exclusion look routine, so the record has to be as fixed as the flag.
        """
        _, order_id = await self._settled_order(db, client)
        await self._exclude(db, order_id, "first decision")

        with pytest.raises(Exception) as caught:
            await db.execute(
                sa.text(
                    "UPDATE orders SET reputation_exclusion_reason = :reason"
                    " WHERE id = :id"
                ),
                {"id": order_id, "reason": "a better story"},
            )
            await db.flush()
        assert "reason cannot be rewritten" in str(caught.value), caught.value

    async def test_an_exclusion_cannot_improve_a_score(self, client, db) -> None:
        """The direction that would turn this into a laundering tool.

        Cancellations and disputes count whether an order is excluded or not. If
        excluding also erased those, an operator could clear a real dispute
        history by excluding the orders it came from, which is adding standing by
        subtraction.
        """
        _, slug, service_id = await build_provider(client)
        buyer_token, _ = await sign_in(client)
        buyer = (await client.get("/api/v1/auth/me", headers=auth(buyer_token))).json()
        agent = (
            await db.execute(
                sa.text("SELECT id FROM agents WHERE slug = :slug"), {"slug": slug}
            )
        ).one()

        await db.execute(
            sa.text(
                "INSERT INTO orders (id, reference, buyer_id, provider_agent_id,"
                " service_id, status, quantity, unit_price, subtotal,"
                " platform_fee, total_amount, currency, platform_fee_bps,"
                " created_at, updated_at, cancelled_at,"
                " reputation_excluded_at, reputation_exclusion_reason)"
                " VALUES (:id, :ref, :buyer, :agent, :service, 'cancelled', 1,"
                " 100, 100, 2.5, 102.5, 'USDC', 250, now(), now(), now(),"
                " now(), :reason)"
            ),
            {
                "id": uuid.uuid4(),
                "ref": f"EXCC-{uuid.uuid4().hex[:6]}",
                "buyer": buyer["id"],
                "agent": agent.id,
                "service": service_id,
                "reason": "excluded while cancelled",
            },
        )
        await db.flush()

        inputs = await reputation.gather_inputs(db, agent_id=agent.id)
        assert inputs.cancelled_orders == 1, (
            "excluding an order erased a cancellation, so the mechanism can "
            "improve a score rather than only reduce one"
        )

    async def test_the_endpoint_excludes_a_real_order_end_to_end(
        self, client, db
    ) -> None:
        """The only test here that reaches the whole handler.

        Added after mutation testing showed the gap. The admin surface tests
        drive this endpoint with a random uuid, which raises NotFoundError
        before the service does any work, so every line after the lookup was
        unexercised. Restoring the logging bug that took this endpoint down in
        production left that suite completely green.

        So this one builds a real settled order and excludes it through HTTP:
        the admin gate, the body validation, the lookup, the write, the logging
        call and the reputation read after it.
        """
        from eth_account import Account
        from eth_account.messages import encode_defunct

        agent_id, order_id = await self._settled_order(db, client)

        before = await reputation.gather_inputs(db, agent_id=agent_id)
        assert before.completed_orders == 1, "the fixture produced no countable order"

        admin = Account.create()
        settings.ESCROW_ADMIN_ADDRESS = admin.address.lower()
        challenge = (
            await client.post(
                "/api/v1/auth/nonce",
                json={"address": admin.address.lower(), "chain_id": settings.CHAIN_ID},
            )
        ).json()
        signed = admin.sign_message(encode_defunct(text=challenge["message"]))
        token = (
            await client.post(
                "/api/v1/auth/signin",
                json={
                    "message": challenge["message"],
                    "signature": signed.signature.hex(),
                    "nonce": challenge["nonce"],
                },
            )
        ).json()["tokens"]["access_token"]

        response = await client.post(
            f"/api/v1/admin/orders/{order_id}/exclude-from-reputation",
            json={"reason": "settlement path verification, both wallets held by one operator"},
            headers=auth(token),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["order_id"] == str(order_id)
        assert body["reputation_excluded_at"]

        after = await reputation.gather_inputs(db, agent_id=agent_id)
        assert after.completed_orders == 0
        assert after.total_volume == 0

        # Excluding twice is refused rather than silently accepted: two operators
        # disagreeing about the same order is worth surfacing, and the second
        # reason could not be recorded anyway.
        again = await client.post(
            f"/api/v1/admin/orders/{order_id}/exclude-from-reputation",
            json={"reason": "a second decision that must not overwrite the first"},
            headers=auth(token),
        )
        assert again.status_code == 409, again.text
        assert again.json()["error"]["code"] == "already_excluded"

    async def test_the_published_reputation_reflects_the_exclusion(
        self, client, db
    ) -> None:
        """What a visitor sees, which is not what the other tests checked.

        Every other test here asserts `gather_inputs`, the internal computation.
        The public endpoint does not call it. It serves a stored snapshot and
        computes one only when none exists, so an exclusion changed what a fresh
        computation would produce and changed nothing anybody could see.

        That is not hypothetical. The first use of this endpoint against
        production returned 200, wrote the timestamp, correctly refused a repeat,
        and left the agent's public page showing the excluded order. Four tests
        passed throughout, because all four asked the question the endpoint does
        not ask.
        """
        from eth_account import Account
        from eth_account.messages import encode_defunct

        agent_id, order_id = await self._settled_order(db, client)
        slug = (
            await db.execute(
                sa.text("SELECT slug FROM agents WHERE id = :id"), {"id": agent_id}
            )
        ).scalar_one()

        # Read it first, which is what creates the snapshot that then goes stale.
        before = (await client.get(f"/api/v1/agents/{slug}/reputation")).json()
        assert before["completed_orders"] == 1, before

        admin = Account.create()
        settings.ESCROW_ADMIN_ADDRESS = admin.address.lower()
        challenge = (
            await client.post(
                "/api/v1/auth/nonce",
                json={"address": admin.address.lower(), "chain_id": settings.CHAIN_ID},
            )
        ).json()
        signed = admin.sign_message(encode_defunct(text=challenge["message"]))
        token = (
            await client.post(
                "/api/v1/auth/signin",
                json={
                    "message": challenge["message"],
                    "signature": signed.signature.hex(),
                    "nonce": challenge["nonce"],
                },
            )
        ).json()["tokens"]["access_token"]

        excluded = await client.post(
            f"/api/v1/admin/orders/{order_id}/exclude-from-reputation",
            json={"reason": "one operator held both wallets, not arm's length"},
            headers=auth(token),
        )
        assert excluded.status_code == 200, excluded.text

        after = (await client.get(f"/api/v1/agents/{slug}/reputation")).json()
        assert after["completed_orders"] == 0, (
            "the exclusion was recorded and the published reputation still counts "
            f"the order: {after}. The endpoint serves a snapshot, so excluding "
            "without recomputing is a change nobody can see."
        )
        assert Decimal(after["total_volume"]) == 0, after

    async def test_a_settled_order_refreshes_the_published_score(
        self, client, db
    ) -> None:
        """Settlement must move the number, not only the underlying rows.

        The broader half of the same defect. Nothing recomputed a snapshot when
        an order settled; only review activity did. An agent could settle its
        second and tenth order while publishing the figures from its first, which
        inverts the single claim this platform makes.
        """
        agent_id, _ = await self._settled_order(db, client)
        slug = (
            await db.execute(
                sa.text("SELECT slug FROM agents WHERE id = :id"), {"id": agent_id}
            )
        ).scalar_one()

        first = (await client.get(f"/api/v1/agents/{slug}/reputation")).json()
        assert first["completed_orders"] == 1

        # A second settlement for the same agent, then the snapshot must follow.
        service_id = (
            await db.execute(
                sa.text("SELECT id FROM services WHERE agent_id = :a LIMIT 1"),
                {"a": agent_id},
            )
        ).scalar_one()
        buyer_token, _ = await sign_in(client)
        buyer = (await client.get("/api/v1/auth/me", headers=auth(buyer_token))).json()
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
                "ref": f"SND-{uuid.uuid4().hex[:6]}",
                "buyer": buyer["id"],
                "agent": agent_id,
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
        # Stands in for the indexer, which now recomputes on settlement.
        await reputation.recompute(db, agent_id=agent_id)

        second = (await client.get(f"/api/v1/agents/{slug}/reputation")).json()
        assert second["completed_orders"] == 2, (
            f"the published score did not follow a second settlement: {second}"
        )

    async def test_the_recompute_endpoint_repairs_a_stale_published_figure(
        self, client, db
    ) -> None:
        """The remedy that did not exist, written from the case that needed it.

        The exclusion of AGO-TMMR2TWH was recorded before recompute-on-exclusion
        shipped. The write was durable, a repeat was correctly refused, and the
        published figure stayed wrong with nothing able to correct it: the fix
        covered every future exclusion and could not reach the one already made.

        This reproduces that exactly. The order is excluded by writing the column
        directly, which is what "already excluded before the fix existed" looks
        like, so the snapshot is stale and no event will ever refresh it.
        """
        from eth_account import Account
        from eth_account.messages import encode_defunct

        agent_id, order_id = await self._settled_order(db, client)
        slug = (
            await db.execute(
                sa.text("SELECT slug FROM agents WHERE id = :id"), {"id": agent_id}
            )
        ).scalar_one()

        stale = (await client.get(f"/api/v1/agents/{slug}/reputation")).json()
        assert stale["completed_orders"] == 1

        # Excluded without going through the endpoint, so nothing recomputes.
        await self._exclude(db, order_id, "excluded before the recompute existed")

        still_stale = (await client.get(f"/api/v1/agents/{slug}/reputation")).json()
        assert still_stale["completed_orders"] == 1, (
            "the fixture did not reproduce a stale snapshot, so this test would "
            "pass without the endpoint doing anything"
        )

        admin = Account.create()
        settings.ESCROW_ADMIN_ADDRESS = admin.address.lower()
        challenge = (
            await client.post(
                "/api/v1/auth/nonce",
                json={"address": admin.address.lower(), "chain_id": settings.CHAIN_ID},
            )
        ).json()
        signed = admin.sign_message(encode_defunct(text=challenge["message"]))
        token = (
            await client.post(
                "/api/v1/auth/signin",
                json={
                    "message": challenge["message"],
                    "signature": signed.signature.hex(),
                    "nonce": challenge["nonce"],
                },
            )
        ).json()["tokens"]["access_token"]

        repaired = await client.post(
            f"/api/v1/admin/agents/{slug}/recompute-reputation", headers=auth(token)
        )
        assert repaired.status_code == 200, repaired.text
        assert repaired.json()["completed_orders"] == 0, repaired.text

        after = (await client.get(f"/api/v1/agents/{slug}/reputation")).json()
        assert after["completed_orders"] == 0, (
            f"the published figure is still stale after a recompute: {after}"
        )

    async def test_recompute_cannot_be_used_to_invent_standing(
        self, client, db
    ) -> None:
        """The property that makes an operator-triggered recompute safe.

        It derives every figure from orders and reviews and takes no argument
        that could carry a score, so running it on an agent with no settled trade
        cannot produce any. A repair tool that could author a number would be a
        far worse thing than the stale figure it exists to fix.
        """
        from eth_account import Account
        from eth_account.messages import encode_defunct

        _, slug, _ = await build_provider(client)

        admin = Account.create()
        settings.ESCROW_ADMIN_ADDRESS = admin.address.lower()
        challenge = (
            await client.post(
                "/api/v1/auth/nonce",
                json={"address": admin.address.lower(), "chain_id": settings.CHAIN_ID},
            )
        ).json()
        signed = admin.sign_message(encode_defunct(text=challenge["message"]))
        token = (
            await client.post(
                "/api/v1/auth/signin",
                json={
                    "message": challenge["message"],
                    "signature": signed.signature.hex(),
                    "nonce": challenge["nonce"],
                },
            )
        ).json()["tokens"]["access_token"]

        body = (
            await client.post(
                f"/api/v1/admin/agents/{slug}/recompute-reputation",
                headers=auth(token),
            )
        ).json()
        assert body["completed_orders"] == 0
        assert body["score"] is None
        assert Decimal(body["total_volume"]) == 0

    async def test_a_non_admin_cannot_recompute(self, client, db) -> None:
        _, slug, _ = await build_provider(client)
        buyer_token, _ = await sign_in(client)
        settings.ESCROW_ADMIN_ADDRESS = "0x000000000000000000000000000000000000adm1"

        refused = await client.post(
            f"/api/v1/admin/agents/{slug}/recompute-reputation",
            headers=auth(buyer_token),
        )
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["code"] == "not_admin"


class TestServiceCountersFollowTheSameRule:
    """The marketplace rating and the reputation must not disagree.

    `recompute` refreshes the cached counters on the agent row, and its docstring
    says that is so the fast read path and the authoritative computation cannot
    drift apart. That is true of the agent and was never true of the service.

    `Service.review_count` and `Service.rating_sum` are incremented directly when
    a review is written and decremented when one is withdrawn. Nothing ever
    reconciles them against the filtered computation, and `Service.average_rating`
    is derived from them and published in the marketplace listing, the service
    detail and the search results.

    So excluding an order from reputation removed its review from the agent's
    figures and left it in the rating a buyer actually browses. The reputation
    system disowned the review and the shop window kept showing it.
    """

    async def _reviewed_order(self, db, client):
        """A settled order with a published review, and its ids."""
        _, slug, service_id = await build_provider(client)
        buyer_token, _ = await sign_in(client)
        buyer = (await client.get("/api/v1/auth/me", headers=auth(buyer_token))).json()
        agent = (
            await db.execute(
                sa.text("SELECT id FROM agents WHERE slug = :slug"), {"slug": slug}
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
                "ref": f"REV-{uuid.uuid4().hex[:6]}",
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
        # completed_order_count carries the service's own constraint that a
        # review cannot outnumber completed orders, so it has to move too.
        await db.execute(
            sa.text(
                "UPDATE services SET order_count = order_count + 1,"
                " completed_order_count = completed_order_count + 1"
                " WHERE id = :id"
            ),
            {"id": service_id},
        )
        await db.flush()

        await db.execute(
            sa.text(
                "INSERT INTO reviews (id, order_id, author_id, subject_agent_id,"
                " service_id, rating, status, created_at, updated_at)"
                " VALUES (:id, :order_id, :author, :agent, :service, 5,"
                " 'published', now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "order_id": order_id,
                "author": buyer["id"],
                "agent": agent.id,
                "service": service_id,
            },
        )
        await db.execute(
            sa.text(
                "UPDATE services SET review_count = review_count + 1,"
                " rating_sum = rating_sum + 5 WHERE id = :id"
            ),
            {"id": service_id},
        )
        await db.flush()
        return agent.id, order_id, service_id, slug

    async def test_excluding_an_order_also_drops_its_review_from_the_shop_window(
        self, client, db
    ) -> None:
        agent_id, order_id, service_id, slug = await self._reviewed_order(db, client)
        await reputation.recompute(db, agent_id=agent_id)

        before = await reputation.gather_inputs(db, agent_id=agent_id)
        assert before.review_count == 1, "the fixture produced no counted review"

        counters = (
            await db.execute(
                sa.text(
                    "SELECT review_count, rating_sum FROM services WHERE id = :id"
                ),
                {"id": service_id},
            )
        ).one()
        assert counters.review_count == 1, "the fixture did not set the service counter"

        await db.execute(
            sa.text(
                "UPDATE orders SET reputation_excluded_at = now(),"
                " reputation_exclusion_reason = 'not an arm''s length trade'"
                " WHERE id = :id"
            ),
            {"id": order_id},
        )
        await db.flush()
        await reputation.recompute(db, agent_id=agent_id)

        after = await reputation.gather_inputs(db, agent_id=agent_id)
        assert after.review_count == 0, "reputation still counts the excluded review"

        counters = (
            await db.execute(
                sa.text(
                    "SELECT review_count, rating_sum FROM services WHERE id = :id"
                ),
                {"id": service_id},
            )
        ).one()
        assert counters.review_count == 0, (
            "reputation disowned the review and the marketplace still shows it. "
            f"service.review_count={counters.review_count}, so the rating a buyer "
            "browses disagrees with the reputation the same platform publishes."
        )
        assert counters.rating_sum == 0, counters.rating_sum

    async def test_a_genuine_review_still_counts_in_both_places(
        self, client, db
    ) -> None:
        """The control. Zeroing every service counter would pass the test above
        perfectly while deleting every real rating on the platform."""
        agent_id, _, service_id, _ = await self._reviewed_order(db, client)
        await reputation.recompute(db, agent_id=agent_id)

        inputs = await reputation.gather_inputs(db, agent_id=agent_id)
        counters = (
            await db.execute(
                sa.text("SELECT review_count, rating_sum FROM services WHERE id = :id"),
                {"id": service_id},
            )
        ).one()

        assert inputs.review_count == 1
        assert counters.review_count == 1, "a genuine review was dropped from the service"
        assert counters.rating_sum == 5
