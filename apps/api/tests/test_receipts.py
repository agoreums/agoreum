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
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from app.core.errors import ConflictError, NotFoundError
from app.db.enums import EscrowStatus, OrderStatus, TransactionType
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
    async def test_the_endpoint_refuses_an_order_nobody_can_see(
        self, client
    ) -> None:
        """Renamed on 2026-08-16, because it was named for a different check.

        It read `test_the_endpoint_refuses_an_order_that_has_not_settled`, and it
        passes a random uuid, so `require_visible_order` answers 404 and
        `build()` is never reached. It has never once exercised the settlement
        refusal its name claimed. That refusal is asserted properly in
        `TestBuildingAReceipt` below, against an escrow that exists and has not
        settled.

        The check itself is worth keeping under an honest name: a stranger must
        not be able to learn whether an order exists by asking for its receipt.
        """
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


@dataclass
class FakeOrder:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    reference: str = "AGO-000123"
    status: OrderStatus = OrderStatus.COMPLETED


@dataclass
class FakeEscrow:
    """Every field `build()` copies into the payload, with plausible values.

    Deliberately not a subset. A receipt that omits a field is a receipt a
    verifier cannot check, and the point of asserting against a full escrow is
    that dropping any one of these from the payload turns a test red.
    """

    order_id: uuid.UUID
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: EscrowStatus = EscrowStatus.RELEASED
    chain_id: int = 84532
    contract_address: str = "0x13c90ba1441bd02d55801cb2f8bda3515020a16d"
    onchain_escrow_id: str = "42"
    # noqa comments: S105 matches the substring "token" in these field names.
    # Both are ERC-20 facts about the settlement asset, USDC on Base Sepolia,
    # not credentials. Same false positive the TransactionType enum carries.
    token_address: str = "0x036cbd53842c5426634e7929541ec2318f3dcf7e"  # noqa: S105
    token_symbol: str = "USDC"  # noqa: S105
    amount: Decimal = Decimal("100.000000")
    released_amount: Decimal = Decimal("97.500000")
    refunded_amount: Decimal = Decimal("0")
    fee_amount: Decimal = Decimal("2.500000")
    buyer_address: str = "0x0000000000000000000000000000000000000b0b"
    provider_address: str = "0x00000000000000000000000000000000000a1ice"


@dataclass
class FakeTx:
    tx_type: TransactionType
    tx_hash: str = "0x" + "ab" * 32
    block_number: int = 45561900


class FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self) -> list:
        return list(self._rows)


class FakeSession:
    """Answers each query by the entity it selects.

    Dispatching on the entity rather than on call order is the point. A session
    that returned rows positionally would still pass if `build()` started asking
    for the wrong things in the right sequence, and the ordering of those three
    queries is not the property under test.
    """

    def __init__(self, *, order=None, escrow=None, transactions=()) -> None:
        self._rows = {
            "Order": [order] if order is not None else [],
            "Escrow": [escrow] if escrow is not None else [],
            "ChainTransaction": list(transactions),
        }
        self.queried: list[str] = []

    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"].__name__
        self.queried.append(entity)
        return FakeResult(self._rows.get(entity, []))


def _settled(**overrides):
    """An order, its settled escrow, and the transaction that settled it."""
    order = FakeOrder()
    escrow = FakeEscrow(order_id=order.id, **overrides)
    tx = FakeTx(tx_type=TransactionType.ESCROW_RELEASE)
    return order, escrow, tx


class TestBuildingAReceipt:
    """The path that had no test at all.

    Everything above asserted properties of the key and of the signing
    primitives, and the one test naming a settlement refusal was passing a
    random uuid and getting a 404 from the visibility check instead. So on the
    day signing went live in production, the function that actually issues a
    receipt had never been called by anything, in either direction.

    That is the same asymmetry found in the subscriptions contract a day
    earlier, where `pause` was tested five ways and `unpause` was never called
    once. Somebody proves the refusal and not the thing being refused.
    """

    async def test_a_settled_escrow_produces_a_signed_receipt(
        self, signing_key
    ) -> None:
        order, escrow, tx = _settled()
        db = FakeSession(order=order, escrow=escrow, transactions=[tx])

        receipt = (await receipts.build(db, order_id=order.id)).as_dict()

        assert receipt["signature"] is not None, (
            "a settled order produced an unsigned receipt while a key is "
            "configured, which is the exact state production was in before "
            "RECEIPT_SIGNING_KEY was set"
        )
        assert receipt["algorithm"] == "ed25519"
        assert receipt["key_id"] == receipts.key_id()

    async def test_the_receipt_carries_what_a_verifier_needs(
        self, signing_key
    ) -> None:
        """The coordinates are the whole product.

        Our signature only says we made a claim. Without the transaction hash,
        the chain id and the contract, a reader cannot go and find out whether
        the claim is true, and the receipt degrades to exactly the unbacked
        assertion the ERC-8004 records already are.
        """
        order, escrow, tx = _settled()
        db = FakeSession(order=order, escrow=escrow, transactions=[tx])

        payload = (await receipts.build(db, order_id=order.id)).payload
        settlement = payload["settlement"]

        assert settlement["transaction_hash"] == tx.tx_hash
        assert settlement["block_number"] == tx.block_number
        assert settlement["chain_id"] == escrow.chain_id
        assert settlement["escrow_contract"] == escrow.contract_address
        assert settlement["onchain_escrow_id"] == escrow.onchain_escrow_id
        assert settlement["buyer_address"] == escrow.buyer_address
        assert settlement["provider_address"] == escrow.provider_address
        assert settlement["amount"] == str(escrow.amount)
        assert settlement["released_amount"] == str(escrow.released_amount)
        assert settlement["fee_amount"] == str(escrow.fee_amount)
        assert payload["order"]["reference"] == order.reference
        assert payload["verify"]["authority"] == "chain"

    async def test_the_signature_covers_the_settlement_figures(
        self, signing_key
    ) -> None:
        """Signing the wrong bytes is indistinguishable from signing the right
        ones until somebody changes a number and the signature still verifies.

        Asserted against the amount specifically, because that is the field an
        attacker would want to move and the one a reader is most likely to act
        on.
        """
        order, escrow, tx = _settled()
        db = FakeSession(order=order, escrow=escrow, transactions=[tx])

        built = await receipts.build(db, order_id=order.id)
        jwk = receipts.public_key_document()["keys"][0]

        assert _verify(built.payload, built.signature, jwk)

        tampered = json.loads(json.dumps(built.payload))
        tampered["settlement"]["released_amount"] = "97000.000000"
        assert not _verify(tampered, built.signature, jwk), (
            "the released amount was changed and the signature still verified, "
            "so the signature does not cover the figures it appears to attest"
        )

    async def test_a_refund_is_a_settlement_too(self, signing_key) -> None:
        """A refunded escrow finished moving money, so it is attestable.

        Worth its own test rather than trusting the frozenset, because a refund
        is the case where the *provider* wants evidence and the release path is
        the one everybody writes first.
        """
        order = FakeOrder()
        escrow = FakeEscrow(
            order_id=order.id,
            status=EscrowStatus.REFUNDED,
            released_amount=Decimal("0"),
            refunded_amount=Decimal("100.000000"),
        )
        tx = FakeTx(tx_type=TransactionType.ESCROW_REFUND)
        db = FakeSession(order=order, escrow=escrow, transactions=[tx])

        payload = (await receipts.build(db, order_id=order.id)).payload
        assert payload["settlement"]["status"] == EscrowStatus.REFUNDED.value
        assert payload["settlement"]["transaction_hash"] == tx.tx_hash

    async def test_an_escrow_that_is_only_funded_is_refused(
        self, signing_key
    ) -> None:
        """The refusal the test above was named for and never performed.

        A funded escrow has committed the money and left its destination open.
        A receipt at that point would attest to something that has not happened,
        and its presence is meant to mean that it has.
        """
        order = FakeOrder(status=OrderStatus.IN_PROGRESS)
        escrow = FakeEscrow(order_id=order.id, status=EscrowStatus.FUNDED)
        db = FakeSession(order=order, escrow=escrow, transactions=[])

        with pytest.raises(ConflictError) as caught:
            await receipts.build(db, order_id=order.id)
        assert caught.value.code == "not_settled"

    async def test_an_order_with_no_escrow_at_all_is_refused(
        self, signing_key
    ) -> None:
        order = FakeOrder()
        db = FakeSession(order=order, escrow=None, transactions=[])

        with pytest.raises(ConflictError) as caught:
            await receipts.build(db, order_id=order.id)
        assert caught.value.code == "not_settled"

    async def test_an_unknown_order_is_not_found(self, signing_key) -> None:
        db = FakeSession(order=None)
        with pytest.raises(NotFoundError):
            await receipts.build(db, order_id=uuid.uuid4())

    async def test_the_receipt_points_at_the_settling_transaction(
        self, signing_key
    ) -> None:
        """An escrow accumulates transactions, and only one of them ended it.

        Pointing at the approval or the funding would send a verifier to a
        transaction that proves the money moved *in*, which is not what the
        receipt claims. The rows are ordered here with the settling transaction
        last so a naive "first row" implementation fails.
        """
        order, escrow, settling = _settled()
        db = FakeSession(
            order=order,
            escrow=escrow,
            transactions=[
                FakeTx(tx_type=TransactionType.TOKEN_APPROVAL, tx_hash="0x" + "11" * 32),
                FakeTx(tx_type=TransactionType.ESCROW_FUND, tx_hash="0x" + "22" * 32),
                FakeTx(tx_type=TransactionType.PLATFORM_FEE, tx_hash="0x" + "33" * 32),
                settling,
            ],
        )

        payload = (await receipts.build(db, order_id=order.id)).payload
        assert payload["settlement"]["transaction_hash"] == settling.tx_hash

    async def test_a_settled_escrow_with_no_recorded_transaction_still_issues(
        self, signing_key
    ) -> None:
        """Degrades rather than refuses, and the absence is visible.

        The escrow status is written from a confirmed chain event, so a settled
        escrow with no matching row is an indexing gap on our side rather than
        evidence that nothing happened. Refusing would withhold a receipt the
        chain would support; issuing a null hash says plainly that we cannot
        name the transaction.
        """
        order, escrow, _ = _settled()
        db = FakeSession(order=order, escrow=escrow, transactions=[])

        payload = (await receipts.build(db, order_id=order.id)).payload
        assert payload["settlement"]["transaction_hash"] is None
        assert payload["settlement"]["block_number"] is None

    async def test_the_receipt_says_which_network_and_whether_it_is_real(
        self, signing_key
    ) -> None:
        """Whoever reads this may be software, with no page around it to explain.

        The same reason the MCP tools state the network in the result itself: a
        receipt for test money that does not say so is a receipt that will
        eventually be quoted as if it were real.
        """
        order, escrow, tx = _settled()
        db = FakeSession(order=order, escrow=escrow, transactions=[tx])
        settlement = (await receipts.build(db, order_id=order.id)).payload["settlement"]
        assert settlement["network"] == "base-sepolia"
        assert settlement["is_testnet"] is True

        order2 = FakeOrder()
        escrow2 = FakeEscrow(order_id=order2.id, chain_id=8453)
        db2 = FakeSession(order=order2, escrow=escrow2, transactions=[tx])
        settlement2 = (
            await receipts.build(db2, order_id=order2.id)
        ).payload["settlement"]
        assert settlement2["network"] == "base"
        assert settlement2["is_testnet"] is False

    async def test_without_a_key_the_receipt_is_unsigned_rather_than_faked(
        self, monkeypatch
    ) -> None:
        """The documented degradation, asserted rather than trusted.

        This is exactly the state production was in until the signing key was
        added, and the reason it went unnoticed is that everything else about
        the response looks correct. The coordinates must survive, so the receipt
        stays useful, and the signature must be absent rather than empty string
        or a placeholder, so the absence is legible to a verifier.
        """
        from app.core.config import settings

        monkeypatch.setattr(settings, "RECEIPT_SIGNING_KEY", None, raising=False)
        order, escrow, tx = _settled()
        db = FakeSession(order=order, escrow=escrow, transactions=[tx])

        receipt = (await receipts.build(db, order_id=order.id)).as_dict()
        assert receipt["signature"] is None
        assert receipt["key_id"] is None
        assert receipt["algorithm"] is None
        assert receipt["receipt"]["settlement"]["transaction_hash"] == tx.tx_hash


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
