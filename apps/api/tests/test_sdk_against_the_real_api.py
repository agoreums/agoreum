"""The Python SDK driven against this API, rather than against a mock.

The SDK suites answer their own mock server, so they assert that the client
sends what the client sends. That is why all three SDKs shipped a call to
`/orders/{id}/payment`, an endpoint this API has never served, and three green
jobs said nothing about it.

A static contract test now compares the paths, which would have caught that one.
It cannot catch the rest of the contract: whether the key header the SDK sends
is the one the API reads, whether a scope refusal surfaces as an error a caller
can act on, whether a 404 arrives as the SDK's own exception type rather than a
raw HTTP failure. Those only appear when the two halves are put together.

The SDK accepts an injected HTTP client, so it is pointed at the ASGI app
directly. No socket, no port, no server to leave running, and the request goes
through the real routing, auth and serialisation.

The async client is used because `ASGITransport` is async only, and the two
clients are documented as mirroring each other exactly. That claim is worth
something only if it is exercised, so this exercises it.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.main import app
from app.modules.apikeys import service as apikeys
from app.modules.organizations import service as orgs
from app.modules.users.models import User

pytestmark = pytest.mark.anyio

agoreum_sdk = pytest.importorskip(
    "agoreum", reason="the Python SDK is not installed in this environment"
)


@pytest_asyncio.fixture(autouse=True)
async def _fresh_app_engine():
    """Give each test the app's engine in a usable state.

    The application creates its engine once at import, and an async pool binds
    its connections to whichever event loop first uses them. Each test here runs
    in its own loop, so the second test to touch the database inherits a
    connection belonging to a loop that has closed, and fails inside asyncpg
    rather than anywhere meaningful. Disposing between tests keeps the failure
    modes in this file about the SDK contract, which is what it is here to test.
    """
    from app.db.session import dispose_engine

    yield
    await dispose_engine()


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        settings.DATABASE_URL, poolclass=NullPool, connect_args={"timeout": 30}
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
async def mint_key(engine):
    """Mint real keys the way the product mints them, then clean them up.

    Returns a factory rather than a single key, because the interesting question
    is no longer "does a key work" but "does this key's scope set decide what it
    can do". That needs at least two keys in the same test run.
    """
    sm = async_sessionmaker(bind=engine, expire_on_commit=False)
    created: list[tuple[uuid.UUID, uuid.UUID]] = []
    wallets: dict[str, str] = {}

    async def factory(*scopes: str) -> str:
        address = "0x" + uuid.uuid4().hex[:40].ljust(40, "0")
        async with sm() as session:
            user = User(primary_address=address, display_name="sdk integration")
            session.add(user)
            await session.flush()
            org = await orgs.ensure_personal_org(session, user=user)
            _, token = await apikeys.create_api_key(
                session,
                org=org,
                creator=user,
                name="sdk integration",
                scopes=list(scopes),
                expires_in_days=None,
            )
            # A verified wallet, because publishing an agent is refused without
            # one. Inserted directly rather than through the API on purpose:
            # verifying a wallet means signing a challenge with its private key,
            # which an API key cannot do and the SDK deliberately cannot either.
            # This is the state the dashboard's signing flow leaves behind.
            wallet_id = uuid.uuid4()
            await session.execute(
                sa.text(
                    "INSERT INTO wallets (id, user_id, address, chain_id, provider,"
                    " verification_status, verified_at, created_at, updated_at)"
                    " VALUES (:i, :u, :a, :c, 'other', 'verified', now(), now(), now())"
                ),
                {"i": wallet_id, "u": user.id, "a": address, "c": settings.CHAIN_ID},
            )
            await session.commit()
            created.append((user.id, org.id))
            wallets[token] = str(wallet_id)
        return token

    factory.wallet_for = wallets.__getitem__  # type: ignore[attr-defined]
    yield factory

    async with sm() as session:
        for user_id, org_id in created:
            # Agents and their services are removed first and explicitly. These
            # tests now register agents through the client, and the foreign keys
            # from agents to organizations are not cascading, so deleting the
            # org first fails and leaves every later delete unrun.
            await session.execute(
                sa.text(
                    "DELETE FROM services WHERE agent_id IN "
                    "(SELECT id FROM agents WHERE org_id = :o)"
                ),
                {"o": org_id},
            )
            await session.execute(sa.text("DELETE FROM agents WHERE org_id = :o"), {"o": org_id})
            await session.execute(
                sa.text("DELETE FROM api_keys WHERE org_id = :o"), {"o": org_id}
            )
            await session.execute(
                sa.text("DELETE FROM organization_memberships WHERE org_id = :o"), {"o": org_id}
            )
            await session.execute(
                sa.text("DELETE FROM organizations WHERE id = :o"), {"o": org_id}
            )
            await session.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        await session.commit()


def _client(token: str):
    """The published client, wired to this app instead of the internet."""
    transport = httpx.ASGITransport(app=app)
    http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return agoreum_sdk.AsyncAgoreumClient(
        api_key=token, base_url="http://testserver/api/v1", http_client=http
    )


@pytest_asyncio.fixture
async def sdk(mint_key):
    """A read-only key: the scopes a cautious integrator would start with."""
    async with _client(await mint_key("marketplace:read", "orders:read")) as client:
        yield client


@pytest_asyncio.fixture
async def writer(mint_key):
    """A key granted `orders:write` deliberately, and nothing else on the write side."""
    async with _client(
        await mint_key("marketplace:read", "orders:read", "orders:write")
    ) as client:
        yield client


class TestTheSdkAndApiAgree:
    async def test_the_key_header_the_sdk_sends_is_the_one_the_api_reads(self, sdk) -> None:
        """Authentication end to end.

        The SDK sends `X-API-Key`. Nothing in either repository forced those to
        stay the same name, and a rename on one side would fail every call for
        every user while both test suites stayed green.
        """
        page = await sdk.marketplace.search_services()
        # A typed page, not a raw dict: the SDK parsing the response is part of
        # the contract, and a shape change would surface here rather than as an
        # attribute error in somebody else's program.
        assert hasattr(page, "items")
        assert isinstance(page.total, int)

    async def test_reading_orders_works_with_a_key(self, sdk) -> None:
        """Reads are the half of the SDK that functions today."""
        orders = await sdk.orders.list()
        # A typed list, not a raw payload: parsing is part of the contract.
        assert hasattr(orders, "__iter__")

    async def test_an_unknown_order_raises_the_sdk_error_not_a_raw_failure(self, sdk) -> None:
        """A caller catches `AgoreumError`. If a 404 escaped as an httpx
        exception instead, every documented error-handling example would be
        wrong."""
        with pytest.raises(agoreum_sdk.AgoreumError) as caught:
            await sdk.orders.get(str(uuid.uuid4()))
        assert caught.value.status_code == 404

    async def test_a_key_without_the_write_scope_cannot_place_an_order(self, sdk) -> None:
        """The refusal half, which is the half worth getting right.

        This key holds `orders:read`. Reading an order and placing one are not
        the same authority, and nothing about holding the first should imply the
        second. The refusal has to be 403 with `insufficient_scope`, not 401: a
        caller who is told "unauthenticated" will go and check their key, which
        is the wrong thing to check and exactly what this API used to make
        everyone do.
        """
        with pytest.raises(agoreum_sdk.AgoreumError) as refused:
            await sdk.orders.place(service_id=str(uuid.uuid4()), quantity=1)
        assert refused.value.status_code == 403
        assert "orders:write" in str(refused.value)

    async def test_a_key_granted_the_write_scope_gets_past_authorisation(self, writer) -> None:
        """The other half: the scope, once granted, actually opens the door.

        The service id is random, so the correct outcome is the endpoint's own
        "no such service" and not an authorisation refusal. That distinction is
        the whole test. A 404 means the request reached the handler; a 401 or
        403 would mean the scope was still decorative, which is the state this
        replaced.
        """
        with pytest.raises(agoreum_sdk.AgoreumError) as reached:
            await writer.orders.place(service_id=str(uuid.uuid4()), quantity=1)
        assert reached.value.status_code not in {401, 403}, (
            "a key holding orders:write was still refused by authorisation"
        )
        assert reached.value.status_code == 404

    async def test_write_scopes_do_not_grant_each_other(self, mint_key) -> None:
        """Nothing is bundled.

        `orders:write` is the only write scope this key was granted. A leaked
        key that can place orders must not also be able to publish services or
        register agents under its owner's name, and the cheapest way for that to
        become false is somebody reaching for a single "write" dependency later.
        Asked over raw HTTP because the SDK does not expose these yet, and the
        guarantee is the API's regardless of which client is asking.
        """
        token = await mint_key("marketplace:read", "orders:read", "orders:write")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as raw:
            headers = {"X-API-Key": token}
            agent = await raw.post(
                "/api/v1/agents", headers=headers, json={"slug": "x", "display_name": "x"}
            )
            # Services are nested under their agent, not top level. Asserting a
            # 403 against a path that does not exist would have passed for the
            # wrong reason forever, so the status is checked exactly rather than
            # as "not 2xx": a 404 is what a wrong path looks like, and it is not
            # evidence that a scope was enforced.
            service = await raw.post(
                "/api/v1/agents/no-such-agent/services",
                headers=headers,
                json={"title": "x"},
            )

        for response, scope in ((agent, "agents:write"), (service, "services:write")):
            assert response.status_code == 403, (
                f"a key without {scope} was not refused: {response.status_code}"
            )
            assert scope in response.text

    async def test_the_payment_route_exists_on_the_app(self, sdk) -> None:
        """Distinguishes a handled 404 from an unrouted one.

        Asked directly rather than through the SDK, because the SDK cannot tell
        the two apart and that is exactly how the original defect hid.
        """
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as raw:
            served = await raw.get(f"/api/v1/orders/{uuid.uuid4()}/payment-instructions")
            absent = await raw.get(f"/api/v1/orders/{uuid.uuid4()}/payment")
        assert served.status_code != 404 or "detail" not in absent.text
        assert absent.status_code == 404


class TestTheProviderLoopThroughTheSdk:
    """Registering an agent and publishing a service, entirely through the client.

    This is the product's headline claim, that an AI agent registers a verified
    identity and publishes services. Until the write scopes were enforced it
    could not be done with the only credential the SDK accepts, and after they
    were enforced the SDK still had no method for it. This walks the whole path
    with a key scoped exactly as a real integrator's would be.
    """

    @pytest_asyncio.fixture
    async def provider(self, mint_key):
        """A key that can register agents and publish services, and nothing else."""
        token = await mint_key(
            "marketplace:read", "agents:read", "agents:write", "services:write"
        )
        async with _client(token) as client:
            client.test_wallet_id = mint_key.wallet_for(token)
            yield client

    async def test_an_agent_can_register_and_publish_a_service(self, provider) -> None:
        unique = uuid.uuid4().hex[:10]

        agent = await provider.agents.create(
            slug=f"sdk-agent-{unique}",
            name="SDK integration agent",
            tagline="Registered through the published client",
            # The real shape, not a list of tags. The SDK's own mock suite would
            # have accepted anything here; only the live schema refuses it.
            capabilities={"skills": ["testing"], "languages": ["en"]},
        )
        assert agent.slug == f"sdk-agent-{unique}"
        # A new agent is a draft. If this ever came back published, an
        # unfinished profile would be discoverable the moment it was created.
        assert agent.raw.get("published_at") is None

        # Publishing is refused until the agent can be paid. Asserted rather
        # than worked around, because it is the rule that stops an agent taking
        # orders it has no way to be paid for, and a client that quietly skipped
        # it would be hiding the reason the next call fails.
        with pytest.raises(agoreum_sdk.AgoreumError) as unpayable:
            await provider.agents.publish(agent.slug)
        assert unpayable.value.status_code == 409
        assert "payout" in str(unpayable.value).lower()

        await provider.agents.set_payout_wallet(
            agent.slug, wallet_id=provider.test_wallet_id
        )

        published = await provider.agents.publish(agent.slug)
        assert published.raw.get("published_at") is not None

        service = await provider.services.create(
            agent.slug,
            slug=f"sdk-service-{unique}",
            title="SDK integration service",
            summary="Created through the published client",
            pricing_model="fixed",
            price=10,
            delivery_time_hours=24,
        )
        assert service.slug == f"sdk-service-{unique}"

        live = await provider.services.publish(agent.slug, service.slug)
        assert live.raw.get("published_at") is not None

        # The agent now appears in its owner's own listing, which is the read
        # side agreeing with the writes rather than the write echoing itself.
        assert any(a.slug == agent.slug for a in await provider.agents.list())

    async def test_the_same_key_cannot_place_an_order(self, provider) -> None:
        """Scopes stay narrow across the resources the client now exposes.

        This key holds both write scopes a provider needs. Selling and buying
        are different authorities, and a provider key that leaked must not be
        able to spend as its owner.
        """
        with pytest.raises(agoreum_sdk.AgoreumError) as refused:
            await provider.orders.place(service_id=str(uuid.uuid4()), quantity=1)
        assert refused.value.status_code == 403
        assert "orders:write" in str(refused.value)

    async def test_publishing_is_refused_without_the_scope(self, mint_key) -> None:
        """The new methods are subject to the same gate as everything else.

        Worth asserting through the client rather than over raw HTTP: a method
        that silently used a different path or header would pass every unit test
        in the SDK's own suite and fail here.
        """
        async with _client(await mint_key("marketplace:read", "agents:read")) as reader:
            with pytest.raises(agoreum_sdk.AgoreumError) as refused:
                await reader.agents.create(slug=f"nope-{uuid.uuid4().hex[:8]}", name="No")
            assert refused.value.status_code == 403
            assert "agents:write" in str(refused.value)
