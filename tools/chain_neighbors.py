from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ChainNeighbor:
    input_address: str
    counterparty_address: str
    chain: str
    relationship_type: str
    direction: str
    tx_hash: str
    block_time: str | None = None
    token_symbol: str | None = None
    raw: dict[str, Any] | None = None


class ChainNeighborProvider(Protocol):
    def get_one_hop_neighbors(
        self,
        address: str,
        chain_id: str = "1",
        limit: int = 1000,
    ) -> list[ChainNeighbor]:
        """Return one-hop counterparties for normal, token, and internal transfers."""


class NotConfiguredChainNeighborProvider:
    def get_one_hop_neighbors(
        self,
        address: str,
        chain_id: str = "1",
        limit: int = 1000,
    ) -> list[ChainNeighbor]:
        return []


def get_one_hop_neighbors(
    address: str,
    chain_id: str = "1",
    limit: int = 1000,
    provider: ChainNeighborProvider | None = None,
) -> list[ChainNeighbor]:
    active_provider = provider or NotConfiguredChainNeighborProvider()
    return active_provider.get_one_hop_neighbors(address, chain_id=chain_id, limit=limit)
