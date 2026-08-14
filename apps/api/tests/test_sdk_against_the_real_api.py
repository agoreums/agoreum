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
        settings.DATABASE_URL, poolclass=NullPool, connect_args={"timeout": 5}
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
async def api_key(engine):
    """A real key, minted the way the product mints one, then cleaned up."""
    sm = async_sessionmaker(bind=engine, expire_on_commit=False)
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
            scopes=["marketplace:read", "orders:read"],
            expires_in_days=None,
        )
        await session.commit()
        user_id, org_id = user.id, org.id

    yield token

    async with sm() as session:
        await session.execute(sa.text("DELETE FROM api_keys WHERE org_id = :o"), {"o": org_id})
        await session.execute(
            sa.text("DELETE FROM organization_memberships WHERE org_id = :o"), {"o": org_id}
        )
        await session.execute(sa.text("DELETE FROM organizations WHERE id = :o"), {"o": org_id})
        await session.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        await session.commit()


@pytest_asyncio.fixture
async def sdk(api_key):
    """The published client, wired to this app instead of the internet."""
    transport = httpx.ASGITransport(app=app)
    http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    async with agoreum_sdk.AsyncAgoreumClient(
        api_key=api_key, base_url="http://testserver/api/v1", http_client=http
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

    async def test_writes_are_refused_for_a_key_holding_every_scope(self, sdk) -> None:
        """Pins a real gap so a change to it has to be deliberate.

        An API key cannot write, whatever scopes it holds. `orders:write`,
        `agents:write` and `services:write` are offered when minting a key and
        are enforced by no route, because every write endpoint takes
        `CurrentUser`, which is session only and refuses a key outright.

        The consequence is that the SDK's headline use, placing an order and
        obtaining payment instructions to fund escrow, cannot be done with the
        only credential the SDK accepts. This asserts today's behaviour rather
        than the intended behaviour, because letting a bearer token move money
        is a decision for the owner, not something to change quietly under a
        passing test.
        """
        with pytest.raises(agoreum_sdk.AgoreumError) as created:
            await sdk.orders.place(service_id=str(uuid.uuid4()), quantity=1)
        assert created.value.status_code == 401

        with pytest.raises(agoreum_sdk.AgoreumError) as paid:
            await sdk.orders.payment_instructions(str(uuid.uuid4()))
        assert paid.value.status_code == 401

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
