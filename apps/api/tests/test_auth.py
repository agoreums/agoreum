"""Sign-In With Ethereum tests.

These use real ECDSA keypairs and real signatures produced by `eth-account`. No
signature verification is stubbed: a test that mocked the crypto would prove
nothing about whether sign-in actually works, and this is the endpoint that
decides who someone is.

The private keys below are generated per-run and exist only inside the test
process. They hold no funds and are never written anywhere.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import sqlalchemy as sa
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import security
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.modules.auth import service

pytestmark = pytest.mark.asyncio


class Wallet:
    """A throwaway keypair that can sign like a real wallet."""

    def __init__(self) -> None:
        self._account = Account.create()

    @property
    def address(self) -> str:
        return self._account.address.lower()

    @property
    def checksum_address(self) -> str:
        return self._account.address

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


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncClient:
    """An HTTP client whose requests share the test's rolled-back session."""

    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _challenge(client: AsyncClient, wallet: Wallet) -> tuple[str, str]:
    """Request a nonce and the server-built message for a wallet."""
    response = await client.post(
        "/api/v1/auth/nonce",
        json={"address": wallet.address, "chain_id": settings.CHAIN_ID},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["nonce"], body["message"]


async def _sign_in(client: AsyncClient, wallet: Wallet) -> dict:
    nonce, message = await _challenge(client, wallet)
    response = await client.post(
        "/api/v1/auth/signin",
        json={
            "message": message,
            "signature": wallet.sign(message),
            "nonce": nonce,
            "wallet_provider": "metamask",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestNonceIssuance:
    async def test_nonce_is_issued_with_a_message(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        nonce, message = await _challenge(client, wallet)

        assert len(nonce) >= 16
        assert settings.SIWE_DOMAIN in message
        assert wallet.checksum_address in message
        assert nonce in message

    async def test_message_carries_our_own_statement(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        """The user must only ever be asked to approve a statement we authored."""
        _, message = await _challenge(client, wallet)
        assert settings.SIWE_STATEMENT in message

    async def test_each_nonce_is_unique(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        first, _ = await _challenge(client, wallet)
        second, _ = await _challenge(client, wallet)
        assert first != second

    async def test_nonce_without_address_has_no_message(
        self, client: AsyncClient
    ) -> None:
        response = await client.post("/api/v1/auth/nonce", json={})
        assert response.status_code == 201
        assert response.json()["message"] is None

    async def test_malformed_address_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/auth/nonce", json={"address": "0xnope"})
        assert response.status_code == 422


class TestSignIn:
    async def test_valid_signature_creates_a_user_and_session(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)

        assert body["user"]["primary_address"] == wallet.address
        assert body["user"]["role"] == "user"
        assert body["tokens"]["access_token"]
        assert body["tokens"]["refresh_token"]
        assert body["tokens"]["token_type"] == "Bearer"  # noqa: S105

    async def test_signing_in_twice_reuses_the_same_account(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        first = await _sign_in(client, wallet)
        second = await _sign_in(client, wallet)
        assert first["user"]["id"] == second["user"]["id"]

    async def test_first_wallet_becomes_the_payout_target(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)
        token = body["tokens"]["access_token"]

        response = await client.get(
            "/api/v1/auth/me/wallets", headers={"Authorization": f"Bearer {token}"}
        )
        wallets = response.json()

        assert len(wallets) == 1
        assert wallets[0]["verification_status"] == "verified"
        assert wallets[0]["is_payout"] is True

    async def test_signature_from_a_different_wallet_is_rejected(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        """The core guarantee: only the holder of the key can sign in as it."""
        attacker = Wallet()
        nonce, message = await _challenge(client, wallet)

        response = await client.post(
            "/api/v1/auth/signin",
            json={
                "message": message,
                "signature": attacker.sign(message),
                "nonce": nonce,
            },
        )
        assert response.status_code == 401

    async def test_tampered_message_is_rejected(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        """Signing one message and submitting another must not authenticate."""
        nonce, message = await _challenge(client, wallet)
        signature = wallet.sign(message)
        tampered = message.replace(settings.SIWE_STATEMENT, "Transfer all my funds")

        response = await client.post(
            "/api/v1/auth/signin",
            json={"message": tampered, "signature": signature, "nonce": nonce},
        )
        assert response.status_code == 401

    async def test_garbage_signature_is_rejected(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        nonce, message = await _challenge(client, wallet)
        response = await client.post(
            "/api/v1/auth/signin",
            json={"message": message, "signature": "0x" + "11" * 65, "nonce": nonce},
        )
        assert response.status_code == 401

    async def test_unknown_nonce_is_rejected(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        _, message = await _challenge(client, wallet)
        response = await client.post(
            "/api/v1/auth/signin",
            json={
                "message": message,
                "signature": wallet.sign(message),
                "nonce": "never-issued-by-this-server",
            },
        )
        assert response.status_code == 401


class TestReplayProtection:
    async def test_a_nonce_cannot_be_used_twice(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        """A captured signature must be worthless on replay."""
        nonce, message = await _challenge(client, wallet)
        signature = wallet.sign(message)
        payload = {"message": message, "signature": signature, "nonce": nonce}

        first = await client.post("/api/v1/auth/signin", json=payload)
        assert first.status_code == 200

        replay = await client.post("/api/v1/auth/signin", json=payload)
        assert replay.status_code == 401

    async def test_a_failed_attempt_still_burns_the_nonce(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        """Otherwise an attacker could grind signatures against one nonce."""
        attacker = Wallet()
        nonce, message = await _challenge(client, wallet)

        failed = await client.post(
            "/api/v1/auth/signin",
            json={
                "message": message,
                "signature": attacker.sign(message),
                "nonce": nonce,
            },
        )
        assert failed.status_code == 401

        retry = await client.post(
            "/api/v1/auth/signin",
            json={
                "message": message,
                "signature": wallet.sign(message),
                "nonce": nonce,
            },
        )
        assert retry.status_code == 401

    async def test_expired_nonce_is_rejected(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        nonce, message = await _challenge(client, wallet)
        await db.execute(
            sa.text("UPDATE siwe_nonces SET expires_at = :past WHERE nonce = :n"),
            {"past": datetime.now(UTC) - timedelta(seconds=1), "n": nonce},
        )

        response = await client.post(
            "/api/v1/auth/signin",
            json={
                "message": message,
                "signature": wallet.sign(message),
                "nonce": nonce,
            },
        )
        assert response.status_code == 401

    async def test_nonce_bound_to_one_wallet_cannot_be_spent_by_another(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        other = Wallet()
        nonce, _ = await _challenge(client, wallet)

        # Build a valid message for the *other* wallet carrying the bound nonce.
        other_message = service.build_challenge(
            address=other.address, nonce=nonce, chain_id=settings.CHAIN_ID
        )
        response = await client.post(
            "/api/v1/auth/signin",
            json={
                "message": other_message,
                "signature": other.sign(other_message),
                "nonce": nonce,
            },
        )
        assert response.status_code == 401


class TestDomainBinding:
    async def test_message_for_another_domain_is_rejected(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        """A signature harvested by a phishing site must not work here."""
        nonce, message = await _challenge(client, wallet)
        phishing = message.replace(settings.SIWE_DOMAIN, "evil.example", 1)

        response = await client.post(
            "/api/v1/auth/signin",
            json={
                "message": phishing,
                "signature": wallet.sign(phishing),
                "nonce": nonce,
            },
        )
        assert response.status_code == 401


class TestAccessTokens:
    async def test_token_authenticates_the_correct_user(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)
        token = body["tokens"]["access_token"]

        response = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["primary_address"] == wallet.address

    async def test_request_without_a_token_is_rejected(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401

    async def test_forged_token_is_rejected(self, client: AsyncClient) -> None:
        """A token signed with the wrong key must not be accepted."""
        import jwt

        forged = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "typ": "access",
                "iss": settings.APP_URL,
                "jti": "x",
                "iat": int(datetime.now(UTC).timestamp()),
                "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            },
            "not-the-real-signing-key",
            algorithm="HS256",
        )
        response = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}
        )
        assert response.status_code == 401

    async def test_expired_token_is_rejected(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)
        user_id = uuid.UUID(body["user"]["id"])

        expired, _ = security.create_access_token(
            user_id=user_id,
            address=wallet.address,
            role="user",
            session_id=uuid.uuid4(),
            expires_in=timedelta(seconds=-1),
        )
        response = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "token_expired"

    async def test_algorithm_confusion_is_rejected(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        """An unsigned 'alg: none' token must never be honoured."""
        import jwt

        body = await _sign_in(client, wallet)
        unsigned = jwt.encode(
            {
                "sub": body["user"]["id"],
                "typ": "access",
                "iss": settings.APP_URL,
                "jti": "x",
                "iat": int(datetime.now(UTC).timestamp()),
                "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            },
            key="",
            algorithm="none",
        )
        response = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {unsigned}"}
        )
        assert response.status_code == 401


class TestRefreshRotation:
    async def test_refresh_returns_a_new_pair(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)
        original_refresh = body["tokens"]["refresh_token"]

        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": original_refresh}
        )
        assert response.status_code == 200
        rotated = response.json()
        assert rotated["refresh_token"] != original_refresh
        assert rotated["access_token"]

    async def test_rotated_token_still_authenticates(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": body["tokens"]["refresh_token"]},
        )
        new_access = response.json()["access_token"]

        me = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"}
        )
        assert me.status_code == 200
        assert me.json()["primary_address"] == wallet.address

    async def test_spent_refresh_token_is_rejected(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)
        spent = body["tokens"]["refresh_token"]

        await client.post("/api/v1/auth/refresh", json={"refresh_token": spent})
        replay = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": spent}
        )
        assert replay.status_code == 401

    async def test_reuse_of_a_spent_token_revokes_every_session(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """Reuse means the token leaked, so the whole family is burned down."""
        body = await _sign_in(client, wallet)
        user_id = uuid.UUID(body["user"]["id"])
        spent = body["tokens"]["refresh_token"]

        rotated = (
            await client.post("/api/v1/auth/refresh", json={"refresh_token": spent})
        ).json()["refresh_token"]

        # An attacker replays the stolen, already-spent token.
        await client.post("/api/v1/auth/refresh", json={"refresh_token": spent})

        # The legitimate holder's current token must now be dead too.
        after = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": rotated}
        )
        assert after.status_code == 401

        active = await service.list_active_sessions(db, user_id=user_id)
        assert active == []

    async def test_unknown_refresh_token_is_rejected(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"}
        )
        assert response.status_code == 401


class TestLogout:
    async def test_logout_revokes_the_session(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)
        access = body["tokens"]["access_token"]
        refresh = body["tokens"]["refresh_token"]

        response = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert response.status_code == 204

        after = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh}
        )
        assert after.status_code == 401

    async def test_logout_all_revokes_every_session(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        first = await _sign_in(client, wallet)
        await _sign_in(client, wallet)
        user_id = uuid.UUID(first["user"]["id"])

        assert len(await service.list_active_sessions(db, user_id=user_id)) == 2

        response = await client.post(
            "/api/v1/auth/logout",
            json={"all_sessions": True},
            headers={"Authorization": f"Bearer {first['tokens']['access_token']}"},
        )
        assert response.status_code == 204
        assert await service.list_active_sessions(db, user_id=user_id) == []

    async def test_logout_without_a_refresh_token_still_ends_the_session(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """An empty body must revoke the calling session, not quietly succeed.

        This returned 204 while revoking nothing, so a client holding only an
        access token was told it had signed out while the session stayed valid
        for its full lifetime. The access token is proof enough to end its own
        session, which is what LogoutRequest has always documented.
        """
        body = await _sign_in(client, wallet)
        access = body["tokens"]["access_token"]
        refresh = body["tokens"]["refresh_token"]
        user_id = uuid.UUID(body["user"]["id"])

        response = await client.post(
            "/api/v1/auth/logout",
            json={},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert response.status_code == 204

        assert await service.list_active_sessions(db, user_id=user_id) == []
        after = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh}
        )
        assert after.status_code == 401

    async def test_logout_cannot_end_another_users_session(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        """The empty-body path is scoped to the caller.

        revoke_session_by_id puts user_id in the predicate rather than trusting
        the session id alone, so one account can never end another's session.
        """
        victim = await _sign_in(client, wallet)
        victim_id = uuid.UUID(victim["user"]["id"])

        attacker = await _sign_in(client, Wallet())

        response = await client.post(
            "/api/v1/auth/logout",
            json={},
            headers={"Authorization": f"Bearer {attacker['tokens']['access_token']}"},
        )
        assert response.status_code == 204
        assert len(await service.list_active_sessions(db, user_id=victim_id)) == 1

    async def test_logout_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/auth/logout", json={})
        assert response.status_code == 401


class TestStoredCredentials:
    async def test_refresh_token_is_never_stored_in_the_clear(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)
        refresh = body["tokens"]["refresh_token"]

        rows = (
            await db.execute(sa.text("SELECT refresh_token_hash FROM sessions"))
        ).scalars().all()

        assert refresh not in rows
        assert security.hash_token(refresh) in rows

    async def test_session_records_the_proven_address(
        self, client: AsyncClient, db: AsyncSession, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)

        # Scoped to this test's own user: the database may hold rows from other
        # runs, and an unscoped query would assert against an unrelated session.
        address = (
            await db.execute(
                sa.text("SELECT address FROM sessions WHERE user_id = :uid"),
                {"uid": uuid.UUID(body["user"]["id"])},
            )
        ).scalar_one()
        assert address == wallet.address


class TestCapabilities:
    async def test_capabilities_are_reported_honestly(
        self, client: AsyncClient
    ) -> None:
        """Clients are told what this deployment can actually verify."""
        response = await client.get("/api/v1/auth/capabilities")
        assert response.status_code == 200

        body = response.json()
        assert body["siwe_domain"] == settings.SIWE_DOMAIN
        assert settings.CHAIN_ID in body["accepted_chain_ids"]
        assert isinstance(body["contract_wallets_supported"], bool)


class TestSessionBoundAccessTokens:
    """An access token is only as alive as the session that issued it.

    A JWT is otherwise valid until it expires. Without binding, a token stolen
    and then detected as stolen would keep working for the rest of its lifetime.
    """

    async def test_access_token_dies_with_its_session(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)
        access = body["tokens"]["access_token"]

        assert (
            await client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
            )
        ).status_code == 200

        await client.post(
            "/api/v1/auth/logout",
            json={"all_sessions": True},
            headers={"Authorization": f"Bearer {access}"},
        )

        after = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
        )
        assert after.status_code == 401
        assert after.json()["error"]["code"] == "session_revoked"

    async def test_access_token_dies_when_theft_is_detected(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        """Detected refresh-token theft must immediately cut off access."""
        body = await _sign_in(client, wallet)
        access = body["tokens"]["access_token"]
        spent = body["tokens"]["refresh_token"]

        await client.post("/api/v1/auth/refresh", json={"refresh_token": spent})
        # The attacker replays the stolen token, which trips reuse detection.
        await client.post("/api/v1/auth/refresh", json={"refresh_token": spent})

        after = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
        )
        assert after.status_code == 401

    async def test_token_without_a_session_claim_is_rejected(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        import jwt

        body = await _sign_in(client, wallet)
        no_sid = jwt.encode(
            {
                "sub": body["user"]["id"],
                "typ": "access",
                "iss": settings.APP_URL,
                "jti": "x",
                "iat": int(datetime.now(UTC).timestamp()),
                "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            },
            settings.JWT_SECRET.get_secret_value(),
            algorithm="HS256",
        )
        response = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {no_sid}"}
        )
        assert response.status_code == 401


class TestProfileUpdate:
    async def test_updates_own_profile_fields(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)
        token = body["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        tag = uuid.uuid4().hex[:8]
        response = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"display_name": "Ada", "username": f"ada-{tag}", "bio": "Builder"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["display_name"] == "Ada"
        assert data["username"] == f"ada-{tag}"

        again = await client.get("/api/v1/auth/me", headers=headers)
        assert again.json()["username"] == f"ada-{tag}"

    async def test_malformed_username_is_rejected(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)
        token = body["tokens"]["access_token"]
        response = await client.patch(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"username": "a"},  # too short
        )
        assert response.status_code == 422

    async def test_unsupported_locale_is_rejected(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)
        token = body["tokens"]["access_token"]
        response = await client.patch(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"preferred_locale": "tlh"},
        )
        assert response.status_code == 422


class TestSelfSuspend:
    async def test_suspend_revokes_sessions(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        body = await _sign_in(client, wallet)
        token = body["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        suspended = await client.post("/api/v1/auth/me/suspend", headers=headers)
        assert suspended.status_code == 204

        # The session was revoked, so the same token no longer authenticates.
        after = await client.get("/api/v1/auth/me", headers=headers)
        assert after.status_code == 401

    async def test_signing_in_again_restores_a_suspended_account(
        self, client: AsyncClient, wallet: Wallet
    ) -> None:
        first = await _sign_in(client, wallet)
        await client.post(
            "/api/v1/auth/me/suspend",
            headers={"Authorization": f"Bearer {first['tokens']['access_token']}"},
        )
        # Proving control of the wallet again restores the account and issues a
        # fresh session.
        restored = await _sign_in(client, wallet)
        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {restored['tokens']['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["status"] == "active"
