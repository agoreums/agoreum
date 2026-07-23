"""Read-only JSON-RPC client for Base.

This module never signs anything. It has no access to a private key and no code
path that could acquire one: the platform is non-custodial, so every transaction
that moves value is signed in the user's own wallet. What happens here is
strictly observation — reading blocks, receipts and logs to learn what the chain
has already accepted.

All calls go through a single client so retry behaviour, timeouts and error
translation are defined once rather than per caller.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import ServiceUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.5

# JSON-RPC error codes that will never succeed on retry.
_PERMANENT_RPC_ERRORS = frozenset({-32600, -32601, -32602, -32000})


class ChainUnavailableError(ServiceUnavailableError):
    """The chain could not be reached or answered with an error."""

    code = "chain_unavailable"
    message = "The blockchain node is unavailable."


@dataclass(frozen=True)
class TransactionReceipt:
    """A mined transaction, as the chain reports it."""

    tx_hash: str
    block_number: int
    block_hash: str
    status: int  # 1 = succeeded, 0 = reverted by the EVM
    gas_used: int
    effective_gas_price: int
    logs: list[dict[str, Any]]

    @property
    def succeeded(self) -> bool:
        return self.status == 1

    @property
    def reverted(self) -> bool:
        return self.status == 0


@dataclass(frozen=True)
class BlockRef:
    number: int
    hash: str
    parent_hash: str
    timestamp: int


def _to_int(value: str | int | None) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    return int(value, 16) if value.startswith("0x") else int(value)


class ChainClient:
    """Async JSON-RPC client bound to the configured network."""

    def __init__(
        self,
        rpc_url: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        chain_id: int | None = None,
    ) -> None:
        self._rpc_url = rpc_url if rpc_url is not None else settings.rpc_url
        self._timeout = timeout
        self._expected_chain_id = chain_id if chain_id is not None else settings.CHAIN_ID
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0

    @property
    def configured(self) -> bool:
        """Whether an endpoint is available at all.

        Callers check this rather than discovering the absence as a failure
        mid-operation.
        """
        return bool(self._rpc_url)

    async def __aenter__(self) -> ChainClient:
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _call(self, method: str, params: list[Any] | None = None) -> Any:
        if not self._rpc_url:
            raise ChainUnavailableError(
                "No RPC endpoint is configured for this network.",
                code="rpc_not_configured",
            )

        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or [],
        }

        try:
            last_error: Exception | None = None
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    response = await client.post(self._rpc_url, json=payload)
                    response.raise_for_status()
                    body = response.json()
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    # Transient by nature: a dropped connection says nothing
                    # about whether the request was valid.
                    last_error = exc
                    logger.warning(
                        "rpc_transport_error",
                        extra={"method": method, "attempt": attempt},
                    )
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    # 429 and 5xx are worth retrying; 4xx will not improve.
                    if exc.response.status_code < 500 and exc.response.status_code != 429:
                        raise ChainUnavailableError(
                            "The blockchain node rejected the request."
                        ) from exc
                    logger.warning(
                        "rpc_http_error",
                        extra={
                            "method": method,
                            "status": exc.response.status_code,
                            "attempt": attempt,
                        },
                    )
                else:
                    if "error" in body:
                        error = body["error"]
                        rpc_code = error.get("code")
                        if rpc_code in _PERMANENT_RPC_ERRORS:
                            logger.warning(
                                "rpc_permanent_error",
                                extra={"method": method, "rpc_code": rpc_code},
                            )
                            raise ChainUnavailableError(
                                "The blockchain node reported an error.",
                                details={"rpc_code": rpc_code},
                            )
                        last_error = RuntimeError(str(error))
                        logger.warning(
                            "rpc_error", extra={"method": method, "rpc_code": rpc_code}
                        )
                    else:
                        return body.get("result")

                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)

            raise ChainUnavailableError(
                "The blockchain node did not respond successfully."
            ) from last_error
        finally:
            if owns_client:
                await client.aclose()

    # ------------------------------------------------------------------ Reads

    async def chain_id(self) -> int:
        return _to_int(await self._call("eth_chainId"))

    async def block_number(self) -> int:
        return _to_int(await self._call("eth_blockNumber"))

    async def verify_network(self) -> None:
        """Confirm the endpoint really serves the chain we think it does.

        A misconfigured endpoint pointing at the wrong network would let the
        platform record settlement that never happened on the chain it claims.
        """
        actual = await self.chain_id()
        if actual != self._expected_chain_id:
            raise ChainUnavailableError(
                f"RPC endpoint serves chain {actual}, expected "
                f"{self._expected_chain_id}.",
                code="chain_id_mismatch",
            )

    async def get_block(self, block: int | str = "latest") -> BlockRef | None:
        tag = hex(block) if isinstance(block, int) else block
        raw = await self._call("eth_getBlockByNumber", [tag, False])
        if raw is None:
            return None
        return BlockRef(
            number=_to_int(raw["number"]),
            hash=raw["hash"],
            parent_hash=raw["parentHash"],
            timestamp=_to_int(raw["timestamp"]),
        )

    async def get_receipt(self, tx_hash: str) -> TransactionReceipt | None:
        """Fetch a receipt, or None when the transaction is not yet mined.

        None means "unknown", never "failed". A pending transaction and a
        rejected one are different facts and must not collapse into one.
        """
        raw = await self._call("eth_getTransactionReceipt", [tx_hash])
        if raw is None:
            return None
        return TransactionReceipt(
            tx_hash=raw["transactionHash"],
            block_number=_to_int(raw["blockNumber"]),
            block_hash=raw["blockHash"],
            status=_to_int(raw.get("status")),
            gas_used=_to_int(raw.get("gasUsed")),
            effective_gas_price=_to_int(raw.get("effectiveGasPrice")),
            logs=raw.get("logs", []),
        )

    async def transaction_exists(self, tx_hash: str) -> bool:
        return await self._call("eth_getTransactionByHash", [tx_hash]) is not None

    async def confirmations_for(self, receipt: TransactionReceipt) -> int:
        """How many blocks deep a receipt is, including its own block."""
        head = await self.block_number()
        if receipt.block_number > head:
            return 0
        return head - receipt.block_number + 1

    async def is_canonical(self, receipt: TransactionReceipt) -> bool:
        """Whether the block holding this receipt is still on the canonical chain.

        A receipt can exist and later be orphaned by a reorganisation. Comparing
        the recorded block hash against the current block at that height is what
        distinguishes a settled transaction from one that has been undone.
        """
        block = await self.get_block(receipt.block_number)
        if block is None:
            return False
        return block.hash.lower() == receipt.block_hash.lower()

    async def get_logs(
        self,
        *,
        address: str,
        from_block: int,
        to_block: int | str = "latest",
        topics: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        params = {
            "address": address,
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block) if isinstance(to_block, int) else to_block,
        }
        if topics:
            params["topics"] = topics
        return await self._call("eth_getLogs", [params]) or []

    async def call(self, *, to: str, data: str, block: str = "latest") -> str:
        """Execute a read-only contract call."""
        return await self._call("eth_call", [{"to": to, "data": data}, block])


async def health_check() -> dict[str, Any]:
    """Report real connectivity to the configured chain.

    Used by the readiness probe. Reports failure honestly rather than omitting
    the component when it cannot be reached.
    """
    if not settings.rpc_url:
        return {"status": "not_configured", "chain_id": settings.CHAIN_ID}

    async with ChainClient() as client:
        try:
            chain_id = await client.chain_id()
            head = await client.block_number()
        except Exception as exc:
            return {
                "status": "down",
                "chain_id": settings.CHAIN_ID,
                "error": type(exc).__name__,
            }

    return {
        "status": "ok" if chain_id == settings.CHAIN_ID else "wrong_network",
        "chain_id": chain_id,
        "expected_chain_id": settings.CHAIN_ID,
        "head_block": head,
        "network": settings.chain_name,
    }
