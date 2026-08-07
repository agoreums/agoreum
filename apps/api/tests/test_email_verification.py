"""Email verification: proving control of an address before anything is sent to it.

These lean on the security properties rather than the happy path, because the
happy path is the easy half. Until an address is proven it is only a string
somebody typed, and the failure this prevents is one account setting a stranger's
address and having the platform mail them.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import sqlalchemy as sa
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import security
from app.core.config import settings
from app.modules.auth import service
from app.modules.users.models import EmailVerificationToken, User

pytestmark = pytest.mark.asyncio


# The suite has no shared helper module: each test file stands alone, since
# `tests/` is not a package. These mirror the equivalents in test_auth.py rather
# than importing across files, which would not resolve.
class Wallet:
    """A throwaway keypair that can sign like a real wallet."""

    def __init__(self) -> None:
        self._account = Account.create()

    @property
    def address(self) -> str:
        return self._account.address.lower()

    def sign(self, message: str) -> str:
        signed = self._account.sign_message(encode_defunct(text=message))
        return signed.signature.hex()


@pytest.fixture
def wallet() -> Wallet:
    return Wallet()


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
    """A session rolled back after every test, so nothing persists between them."""
    connection = await engine.connect()
    transaction = await connection.begin()
    session = async_sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


async def _sign_in(client: AsyncClient, wallet: Wallet) -> dict:
    response = await client.post(
        "/api/v1/auth/nonce",
        json={"address": wallet.address, "chain_id": settings.CHAIN_ID},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    nonce, message = body["nonce"], body["message"]

    response = await client.post(
        "/api/v1/auth/signin",
        json={
            "message": message,
            "signature": wallet.sign(message),
            "nonce": nonce,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _signed_in_with_email(
    client: AsyncClient, db: AsyncSession, wallet: Wallet, email: str
) -> tuple[str, User]:
    """Sign in and put an address on the profile. Returns the access token and user."""
    body = await _sign_in(client, wallet)
    access = body["tokens"]["access_token"]
    resp = await client.patch(
        "/api/v1/auth/me",
        json={"email": email},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["email_verified_at"] is None, "a new address starts unproven"

    user = (
        await db.execute(sa.select(User).where(User.id == uuid.UUID(body["user"]["id"])))
    ).scalar_one()
    return access, user


class TestIssuing:
    async def test_requesting_verification_stores_only_a_hash(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """A leaked backup must not hand out working verification links."""
        access, user = await _signed_in_with_email(client, db, wallet, "a@example.com")

        resp = await client.post(
            "/api/v1/auth/me/email/verify",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200
        # Delivery is not wired yet, and the endpoint says so rather than
        # claiming a message went out.
        assert resp.json()["sent"] is False

        rows = (
            await db.execute(
                sa.select(EmailVerificationToken).where(
                    EmailVerificationToken.user_id == user.id
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert len(rows[0].token_hash) == 64, "expected a hex sha256"
        assert rows[0].email == "a@example.com"
        assert rows[0].consumed_at is None

    async def test_requesting_again_invalidates_the_previous_token(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """Asking for a fresh link must retire the old one.

        Someone requests a second link precisely when they suspect the first went
        astray, which is the worst moment for the first to keep working.
        """
        access, user = await _signed_in_with_email(client, db, wallet, "b@example.com")
        headers = {"Authorization": f"Bearer {access}"}

        await client.post("/api/v1/auth/me/email/verify", headers=headers)
        first = (
            await db.execute(
                sa.select(EmailVerificationToken).where(
                    EmailVerificationToken.user_id == user.id
                )
            )
        ).scalars().all()[0]

        await client.post("/api/v1/auth/me/email/verify", headers=headers)
        await db.refresh(first)
        assert first.consumed_at is not None, "the earlier token should be spent"

    async def test_verification_requires_an_email_on_the_profile(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        # `db` is unused here, but taking it means this skips alongside the rest
        # when no database is reachable rather than failing on the app's own
        # connection. A test that goes red for environmental reasons is noise,
        # and noise is how a real failure gets waved through.
        body = await _sign_in(client, wallet)
        resp = await client.post(
            "/api/v1/auth/me/email/verify",
            headers={"Authorization": f"Bearer {body['tokens']['access_token']}"},
        )
        assert resp.status_code == 409

    async def test_verification_requires_authentication(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        assert (await client.post("/api/v1/auth/me/email/verify")).status_code == 401


class TestConfirming:
    async def test_a_valid_token_proves_the_address(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        _access, user = await _signed_in_with_email(client, db, wallet, "c@example.com")
        raw, _row = await service.issue_email_verification(db, user=user)
        await db.commit()

        resp = await client.post("/api/v1/auth/me/email/confirm", json={"token": raw})
        assert resp.status_code == 200, resp.text
        assert resp.json()["email_verified_at"] is not None

        await db.refresh(user)
        assert user.email_verified_at is not None

    async def test_a_token_cannot_be_used_twice(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        _access, user = await _signed_in_with_email(client, db, wallet, "d@example.com")
        raw, _row = await service.issue_email_verification(db, user=user)
        await db.commit()

        assert (
            await client.post("/api/v1/auth/me/email/confirm", json={"token": raw})
        ).status_code == 200
        second = await client.post(
            "/api/v1/auth/me/email/confirm", json={"token": raw}
        )
        assert second.status_code == 401, "a spent token must not verify again"

    async def test_an_expired_token_is_refused(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        _access, user = await _signed_in_with_email(client, db, wallet, "e@example.com")
        raw, row = await service.issue_email_verification(db, user=user)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()

        resp = await client.post("/api/v1/auth/me/email/confirm", json={"token": raw})
        assert resp.status_code == 401
        await db.refresh(user)
        assert user.email_verified_at is None

    async def test_an_unknown_token_is_refused(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/me/email/confirm", json={"token": "not-a-real-token"}
        )
        assert resp.status_code == 401

    async def test_a_token_cannot_verify_an_address_it_was_not_sent_to(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """The property that makes this verification rather than a formality.

        A token proves control of the address it was mailed to. If the profile
        address changes in between, confirming must not silently bless the new
        one, or a user could point the profile at a stranger and then confirm with
        a link they legitimately received at their own address.
        """
        access, user = await _signed_in_with_email(client, db, wallet, "mine@example.com")
        raw, _row = await service.issue_email_verification(db, user=user)
        await db.commit()

        resp = await client.patch(
            "/api/v1/auth/me",
            json={"email": "someone-else@example.com"},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200

        confirm = await client.post(
            "/api/v1/auth/me/email/confirm", json={"token": raw}
        )
        assert confirm.status_code == 409, "must refuse an address nobody proved"

        await db.refresh(user)
        assert user.email_verified_at is None
        assert user.email == "someone-else@example.com"

    async def test_the_spent_token_is_burned_even_when_the_address_moved(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """A refused token must not be replayable once the address moves back."""
        access, user = await _signed_in_with_email(client, db, wallet, "orig@example.com")
        raw, _row = await service.issue_email_verification(db, user=user)
        await db.commit()
        headers = {"Authorization": f"Bearer {access}"}

        await client.patch(
            "/api/v1/auth/me", json={"email": "moved@example.com"}, headers=headers
        )
        assert (
            await client.post("/api/v1/auth/me/email/confirm", json={"token": raw})
        ).status_code == 409

        # Move it back and try the same link again.
        await client.patch(
            "/api/v1/auth/me", json={"email": "orig@example.com"}, headers=headers
        )
        again = await client.post(
            "/api/v1/auth/me/email/confirm", json={"token": raw}
        )
        assert again.status_code == 401, "the token was already spent"

        await db.refresh(user)
        assert user.email_verified_at is None


class TestStoredForm:
    async def test_the_raw_token_is_never_stored(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        _access, user = await _signed_in_with_email(client, db, wallet, "f@example.com")
        raw, _row = await service.issue_email_verification(db, user=user)
        await db.commit()

        stored = (
            await db.execute(
                sa.select(EmailVerificationToken.token_hash).where(
                    EmailVerificationToken.user_id == user.id
                )
            )
        ).scalars().all()
        assert raw not in stored
        assert security.hash_token(raw) in stored

    async def test_changing_the_email_clears_prior_verification(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        access, user = await _signed_in_with_email(client, db, wallet, "g@example.com")
        raw, _row = await service.issue_email_verification(db, user=user)
        await db.commit()
        await client.post("/api/v1/auth/me/email/confirm", json={"token": raw})
        await db.refresh(user)
        assert user.email_verified_at is not None

        resp = await client.patch(
            "/api/v1/auth/me",
            json={"email": "h@example.com"},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200
        assert resp.json()["email_verified_at"] is None
