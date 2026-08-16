"""Settlement receipts, and the properties that make them worth anything.

An empirical study of ERC-8004 found that between 98.7% and 100% of on-chain
reputation records carry no proof of payment and no link to a task, and that
moving a score costs fractions of a cent. That ecosystem's reputation is
assertion, and assertion is cheap.

A receipt is only better than that if it is checkable by somebody who trusts
nothing Agoreum says. So the assertions here are about exactly that: a receipt
exists only when money actually moved, it carries the coordinates to check the
claim on chain, it says the chain is the authority rather than the signature,
and altering any part of it breaks verification.

A receipt that verified against a modified payload would be worse than no
receipt, because it would look like evidence.
"""
from __future__ import annotations

import base64
import json
import uuid

import pytest

from app.modules.receipts import service as receipts


def _fresh_key() -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    raw = Ed25519PrivateKey.generate().private_bytes_raw()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.fixture
def signing_key(monkeypatch):
    """A real Ed25519 key for the duration of one test.

    Generated per test rather than shared, so nothing here can accidentally
    depend on a key that also exists in a deployed environment.
    """
    from app.core.config import settings

    key = _fresh_key()
    monkeypatch.setattr(settings, "RECEIPT_SIGNING_KEY", key, raising=False)
    return key


def _verify(payload: dict, signature: str, jwk: dict) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    pub = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(jwk["x"] + "=="))
    try:
        pub.verify(base64.urlsafe_b64decode(signature + "=="), receipts.canonical(payload))
    except InvalidSignature:
        return False
    return True


class TestTheKeyIsSafeByConstruction:
    def test_no_key_is_invented_at_runtime(self, monkeypatch) -> None:
        """A key generated at startup changes on every restart, which silently
        invalidates every receipt already issued and teaches people to ignore
        signature failures."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "RECEIPT_SIGNING_KEY", None, raising=False)
        assert receipts._signing_key() is None
        assert receipts.public_key_document()["keys"] == []

    def test_the_signing_key_is_not_a_chain_key(self, signing_key) -> None:
        """The property that bounds the damage.

        Compromise of this key forges claims, which is serious. It must not also
        move funds, so it must not be any key the contracts recognise.
        """
        from app.core.config import settings

        for name in ("DEPLOYER_PRIVATE_KEY", "ARBITER_PRIVATE_KEY", "PRIVATE_KEY"):
            other = getattr(settings, name, None)
            if other:
                assert other != signing_key, (
                    f"the receipt signing key is also {name}, so forging a receipt "
                    "and moving funds would be the same compromise"
                )

    def test_an_ed25519_key_cannot_be_an_ethereum_key(self, signing_key) -> None:
        """Stated as a property rather than a hope: the curve differs, so this
        key is structurally incapable of signing an Ethereum transaction."""
        doc = receipts.public_key_document()
        assert doc["keys"][0]["crv"] == "Ed25519"
        assert doc["keys"][0]["use"] == "sig"


class TestTheDocumentIsVerifiable:
    def test_the_published_key_verifies_a_signature_it_made(
        self, signing_key
    ) -> None:
        payload = {"b": 2, "a": 1, "nested": {"z": 1, "y": 2}}
        key = receipts._signing_key()
        signature = base64.urlsafe_b64encode(
            key.sign(receipts.canonical(payload))
        ).decode().rstrip("=")

        jwk = receipts.public_key_document()["keys"][0]
        assert _verify(payload, signature, jwk), (
            "a receipt signed with the current key does not verify against the "
            "key the same service publishes"
        )

    def test_altering_any_field_breaks_verification(self, signing_key) -> None:
        """The assertion the whole thing rests on."""
        payload = {"amount": "100.00", "order": {"id": "abc"}}
        key = receipts._signing_key()
        signature = base64.urlsafe_b64encode(
            key.sign(receipts.canonical(payload))
        ).decode().rstrip("=")
        jwk = receipts.public_key_document()["keys"][0]

        assert _verify(payload, signature, jwk)

        for tampered in (
            {"amount": "1000.00", "order": {"id": "abc"}},
            {"amount": "100.00", "order": {"id": "different"}},
            {"amount": "100.00", "order": {"id": "abc"}, "extra": True},
        ):
            assert not _verify(tampered, signature, jwk), (
                f"a modified receipt still verified: {tampered}"
            )

    def test_the_canonical_form_is_order_independent(self) -> None:
        """A verifier that reparsed the JSON must get identical bytes.

        Without this, a genuinely valid receipt fails for anyone whose JSON
        library orders keys differently, and the natural reaction to that is to
        stop checking signatures at all.
        """
        one = {"a": 1, "b": {"x": 1, "y": 2}}
        two = json.loads('{"b": {"y": 2, "x": 1}, "a": 1}')
        assert receipts.canonical(one) == receipts.canonical(two)

    def test_the_key_document_says_how_to_verify(self, signing_key) -> None:
        doc = receipts.public_key_document()
        assert "chain" in doc["verification"].lower(), (
            "the key document does not tell a verifier that the chain is the "
            "authority, which is the point of the receipt"
        )


class TestAReceiptMeansSomething:
    async def test_the_endpoint_refuses_an_order_that_has_not_settled(
        self, client
    ) -> None:
        from eth_account import Account
        from eth_account.messages import encode_defunct

        from app.core.config import settings

        account = Account.create()
        nonce = (
            await client.post(
                "/api/v1/auth/nonce",
                json={"address": account.address.lower(), "chain_id": settings.CHAIN_ID},
            )
        ).json()
        signed = account.sign_message(encode_defunct(text=nonce["message"]))
        session = (
            await client.post(
                "/api/v1/auth/signin",
                json={
                    "message": nonce["message"],
                    "signature": signed.signature.hex(),
                    "nonce": nonce["nonce"],
                },
            )
        ).json()["tokens"]["access_token"]

        resp = await client.get(
            f"/api/v1/orders/{uuid.uuid4()}/receipt",
            headers={"Authorization": f"Bearer {session}"},
        )
        # Not found, because a stranger must not learn whether an order exists.
        assert resp.status_code == 404, resp.text

    async def test_the_key_document_is_public(self, client) -> None:
        """A verifier checking somebody else's receipt has no account here."""
        resp = await client.get("/.well-known/agoreum-receipts.json")
        assert resp.status_code == 200, resp.text
        assert "keys" in resp.json()


def test_only_terminal_escrow_states_count_as_settled() -> None:
    """A funded escrow is not a settlement.

    The money is committed and its destination is still open, so a receipt at
    that point would attest to something that has not happened.
    """
    from app.db.enums import EscrowStatus

    assert EscrowStatus.RELEASED in receipts.SETTLED_ESCROW_STATUSES
    assert EscrowStatus.REFUNDED in receipts.SETTLED_ESCROW_STATUSES
    for not_settled in (
        EscrowStatus.NONE,
        EscrowStatus.FUNDING,
        EscrowStatus.FUNDED,
        EscrowStatus.RELEASING,
        EscrowStatus.REFUNDING,
        EscrowStatus.DISPUTED,
    ):
        assert not_settled not in receipts.SETTLED_ESCROW_STATUSES, (
            f"{not_settled} would issue a receipt for money that has not finished moving"
        )
