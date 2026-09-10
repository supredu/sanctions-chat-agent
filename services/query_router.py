from typing import Any, Literal

from agents import function_tool

from tools.blockchain_lookup import classify_address
from tools.chain_neighbors import (
    BitraceMcpNeighborProvider,
    ChainNeighborProvider,
    configured_bitrace_neighbor_provider,
    get_one_hop_neighbors,
)
from tools.local_sanctions import lookup_local_sanctions, search_local_entities


QueryType = Literal["address", "entity"]


def infer_query_type(query: str) -> QueryType:
    address_profile = classify_address(query)
    if address_profile["valid"]:
        return "address"
    return "entity"


def lookup_local_query(
    query: str,
    entity_limit: int = 10,
    include_neighbors: bool = False,
    chain_id: str = "auto",
    neighbor_limit: int = 1000,
    neighbor_provider: ChainNeighborProvider | None = None,
) -> dict[str, Any]:
    query_type = infer_query_type(query)

    if query_type == "address":
        address_profile = classify_address(query)
        hits = lookup_local_sanctions(query)
        related_hits: list[dict[str, Any]] = []
        seen_related_hits: set[tuple[str, str | None, str | None, str]] = set()
        neighbor_lookup = {"status": "not_requested"}
        if include_neighbors:
            active_provider = neighbor_provider or configured_bitrace_neighbor_provider()
            for neighbor in get_one_hop_neighbors(
                query,
                chain_id=chain_id,
                limit=neighbor_limit,
                provider=active_provider,
            ):
                neighbor_hits = lookup_local_sanctions(neighbor.counterparty_address)
                for hit in neighbor_hits:
                    dedupe_key = (
                        neighbor.counterparty_address.lower(),
                        hit.get("entity_name"),
                        hit.get("authority"),
                        neighbor.direction,
                    )
                    if dedupe_key in seen_related_hits:
                        continue
                    seen_related_hits.add(dedupe_key)
                    related_hits.append(
                        {
                            "input_address": neighbor.input_address,
                            "related_address": neighbor.counterparty_address,
                            "relationship_depth": 1,
                            "relationship_type": neighbor.relationship_type,
                            "chain": neighbor.chain,
                            "tx_hash": neighbor.tx_hash,
                            "block_time": neighbor.block_time,
                            "direction": neighbor.direction,
                            "sanction_authority": hit.get("authority"),
                            "sanctioned_entity": hit.get("entity_name"),
                            "sanction_date": (hit.get("sanction_dates") or [None])[0],
                            "source_url": (hit.get("source_urls") or [None])[0],
                            "description": _related_hit_description(neighbor),
                            "sanction_hit": hit,
                        }
                    )
            if isinstance(active_provider, BitraceMcpNeighborProvider):
                neighbor_lookup = active_provider.last_meta.__dict__
            elif active_provider is None:
                neighbor_lookup = {
                    "status": "not_configured",
                    "message": "BITRACE_MCP_URL and BITRACE_API_TOKEN are not configured.",
                }
            if related_hits:
                neighbor_lookup = {
                    **neighbor_lookup,
                    "status": "related_hit",
                    "message": None,
                    "matched_sanctioned_address_count": len(
                        {hit["related_address"].lower() for hit in related_hits}
                    ),
                }
        return {
            "query": query,
            "query_type": query_type,
            "address_profile": {
                "address": query.strip(),
                "chain": address_profile["chain"],
                "address_type": address_profile["address_type"],
                "explorer_url": address_profile["explorer_url"],
            },
            "hit_count": len(hits),
            "hits": hits,
            "related_hit_count": len(related_hits),
            "related_hits": related_hits,
            "neighbor_lookup": neighbor_lookup,
        }

    hits = search_local_entities(query, limit=entity_limit)
    return {
        "query": query,
        "query_type": query_type,
        "address_profile": None,
        "hit_count": len(hits),
        "hits": hits,
        "related_hit_count": 0,
        "related_hits": [],
    }


@function_tool
def route_and_query_local_sources(query: str, entity_limit: int = 10) -> dict[str, Any]:
    """Infer whether the query is an address or entity name, then query local sanctions sources."""
    return lookup_local_query(query, entity_limit=entity_limit)


def _related_hit_description(neighbor: Any) -> str:
    if neighbor.direction == "inbound":
        return (
            f"{neighbor.input_address} received a one-hop transfer from sanctioned address "
            f"{neighbor.counterparty_address}."
        )
    if neighbor.direction == "outbound":
        return (
            f"{neighbor.input_address} sent a one-hop transfer to sanctioned address "
            f"{neighbor.counterparty_address}."
        )
    return (
        f"{neighbor.input_address} has a one-hop transfer relationship with sanctioned address "
        f"{neighbor.counterparty_address}."
    )
