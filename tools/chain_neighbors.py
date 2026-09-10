import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4


_ADDRESS_IN_PAIR_LINE_RE = re.compile(r"地址:([A-Za-z0-9x]+)")


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


@dataclass(frozen=True)
class ChainNeighborLookupMeta:
    status: str
    message: str | None = None
    chain: str | None = None
    sampled_transaction_count: int = 0
    unique_counterparty_count: int = 0
    truncated: bool = False
    raw: dict[str, Any] | None = None


class ChainNeighborProvider(Protocol):
    def get_one_hop_neighbors(
        self,
        address: str,
        chain_id: str = "auto",
        limit: int = 1000,
    ) -> list[ChainNeighbor]:
        """Return one-hop counterparties for normal, token, and internal transfers."""


class NotConfiguredChainNeighborProvider:
    def get_one_hop_neighbors(
        self,
        address: str,
        chain_id: str = "auto",
        limit: int = 1000,
    ) -> list[ChainNeighbor]:
        return []


class BitraceMcpNeighborProvider:
    def __init__(
        self,
        endpoint: str | None = None,
        api_token: str | None = None,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> None:
        try:
            from config import load_dotenv

            load_dotenv()
        except Exception:
            pass
        self.endpoint = endpoint or os.environ.get("BITRACE_MCP_URL")
        self.api_token = api_token or os.environ.get("BITRACE_API_TOKEN")
        self.session_id = session_id or os.environ.get("BITRACE_MCP_SESSION_ID") or str(uuid4())
        self.timeout = timeout or float(os.environ.get("BITRACE_MCP_TIMEOUT_SECONDS", "8"))
        self.last_meta = ChainNeighborLookupMeta(status="not_started")

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.api_token)

    def get_one_hop_neighbors(
        self,
        address: str,
        chain_id: str = "auto",
        limit: int = 1000,
    ) -> list[ChainNeighbor]:
        if not self.configured:
            self.last_meta = ChainNeighborLookupMeta(
                status="not_configured",
                message="BITRACE_MCP_URL and BITRACE_API_TOKEN are required.",
            )
            return []

        try:
            chains = self._resolve_chain_candidates(address, chain_id)
            neighbors: list[ChainNeighbor] = []
            total_transactions = 0
            tools_used: set[str] = set()
            errors: list[str] = []
            for chain in chains:
                chain_neighbors: list[ChainNeighbor] = []
                for direction in ("OUT", "IN"):
                    try:
                        payload = self._call_tool(
                            "getTxs",
                            {
                                "chain": chain,
                                "address": address,
                                "direction": direction,
                                "pageNumber": 1,
                                "pageSize": min(max(limit, 1), 1000),
                                "sort": "desc",
                                "sortBy": "txTime",
                            },
                        )
                        transactions = self._extract_transactions(payload)
                        total_transactions += len(transactions)
                        chain_neighbors.extend(
                            self._neighbors_from_transactions(address, chain, transactions, limit, direction)
                        )
                        tools_used.add("getTxs")
                    except Exception as exc:
                        errors.append(f"{chain}:{direction}:{exc}")
                if not chain_neighbors:
                    try:
                        pair_payload = self._call_tool(
                            "getPairs",
                            {
                                "chain": chain,
                                "address": address,
                                "reason": ["inValue", "outValue", "inCount", "outCount"],
                                "locale": "ZH_CN",
                            },
                        )
                        chain_neighbors = self._neighbors_from_pairs_text(address, chain, pair_payload, limit)
                        tools_used.add("getPairs")
                    except Exception as exc:
                        errors.append(f"{chain}:getPairs:{exc}")
                neighbors.extend(chain_neighbors)
                if len(neighbors) >= limit:
                    neighbors = neighbors[:limit]
                    break
            self.last_meta = ChainNeighborLookupMeta(
                status="partial_error" if errors else "ok",
                chain=",".join(chains),
                sampled_transaction_count=total_transactions,
                unique_counterparty_count=len(neighbors),
                truncated=total_transactions >= min(max(limit, 1), 1000),
                raw={"tools": sorted(tools_used), "queried_chains": chains},
                message="; ".join(errors[:3]) if errors else None,
            )
            return neighbors
        except Exception as exc:
            self.last_meta = ChainNeighborLookupMeta(status="error", message=str(exc))
            return []

    def _resolve_chain(self, address: str, chain_id: str) -> str:
        normalized_chain = _normalize_chain(chain_id)
        if normalized_chain:
            return normalized_chain

        judged = self._call_tool("judge", {"value": address, "locale": "ZH_CN"})
        judged_chain = _find_chain_value(judged)
        return _normalize_chain(judged_chain) or "eth"

    def _resolve_chain_candidates(self, address: str, chain_id: str) -> list[str]:
        normalized_chain = _normalize_chain(chain_id)
        if normalized_chain:
            return [normalized_chain]

        configured_chains = [
            chain.strip()
            for chain in os.environ.get("BITRACE_ONE_HOP_CHAINS", "").split(",")
            if chain.strip()
        ]
        if configured_chains:
            return [chain for chain in (_normalize_chain(item) for item in configured_chains) if chain]

        first_chain = self._resolve_chain(address, chain_id)
        chains = [first_chain]

        deduped: list[str] = []
        for chain in chains:
            if chain not in deduped:
                deduped.append(chain)
        return deduped

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        request_body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint or "",
            data=request_body,
            method="POST",
            headers={
                "API-TOKEN": self.api_token or "",
                "Mcp-Session-Id": self.session_id,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return _decode_mcp_response(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Bitrace MCP HTTP {exc.code}: {body[:500]}") from exc

    def _extract_transactions(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        result = payload.get("result", payload)
        candidates: list[Any] = [result]
        if isinstance(result, dict):
            candidates.extend(result.get(key) for key in ("data", "items", "list", "records", "txs", "transactions"))
            content = result.get("content")
            if isinstance(content, list):
                candidates.extend(item.get("text") for item in content if isinstance(item, dict))
        for candidate in candidates:
            parsed = _maybe_json(candidate)
            txs = _find_transaction_list(parsed)
            if txs is not None:
                return txs
            text = _extract_text_content(parsed)
            text_txs = _parse_get_txs_text(text)
            if text_txs:
                return text_txs
        return []

    def _neighbors_from_transactions(
        self,
        input_address: str,
        chain: str,
        transactions: list[dict[str, Any]],
        limit: int,
        requested_direction: str = "ALL",
    ) -> list[ChainNeighbor]:
        input_norm = input_address.casefold()
        seen: set[tuple[str, str]] = set()
        neighbors: list[ChainNeighbor] = []
        for tx in transactions:
            from_address = _first_string(tx, "from", "fromAddress", "from_address", "sender")
            to_address = _first_string(tx, "to", "toAddress", "to_address", "receiver")
            pair_address = _first_string(tx, "pair", "pairAddress", "counterparty", "counterpartyAddress")
            direction = _direction_from_transaction(input_norm, from_address, to_address, requested_direction)
            if pair_address:
                counterparty = pair_address
                direction = _normalize_direction(_first_string(tx, "direction")) or direction
            elif direction == "outbound":
                counterparty = to_address
            elif direction == "inbound":
                counterparty = from_address
            else:
                counterparty = to_address
                if counterparty and counterparty.casefold() == input_norm:
                    counterparty = from_address
            if not counterparty or counterparty.casefold() == input_norm:
                continue
            counterparty_key = (counterparty.casefold(), direction)
            if counterparty_key in seen:
                continue
            seen.add(counterparty_key)
            neighbors.append(
                ChainNeighbor(
                    input_address=input_address,
                    counterparty_address=counterparty,
                    chain=chain,
                    relationship_type="transfer",
                    direction=direction,
                    tx_hash=_first_string(tx, "hash", "txHash", "tx_hash") or "",
                    block_time=_first_string(tx, "time", "txTime", "blockTime", "timestamp"),
                    token_symbol=_first_string(tx, "symbol", "tokenSymbol", "token_symbol"),
                    raw=tx,
                )
            )
            if len(neighbors) >= limit:
                break
        return neighbors

    def _neighbors_from_pairs_text(
        self,
        input_address: str,
        chain: str,
        payload: dict[str, Any],
        limit: int,
    ) -> list[ChainNeighbor]:
        text = _extract_text_content(payload)
        if not text:
            return []

        seen: set[tuple[str, str]] = set()
        neighbors: list[ChainNeighbor] = []
        for line in text.splitlines():
            match = _ADDRESS_IN_PAIR_LINE_RE.search(line)
            if not match:
                continue
            counterparty = match.group(1)
            if counterparty.casefold() == input_address.casefold():
                continue
            inbound_value = _amount_from_pair_line(line, "转入")
            outbound_value = _amount_from_pair_line(line, "转出")
            directions = []
            if outbound_value > 0:
                directions.append("outbound")
            if inbound_value > 0:
                directions.append("inbound")
            for direction in directions:
                if (counterparty.casefold(), direction) in seen:
                    continue
                seen.add((counterparty.casefold(), direction))
                neighbors.append(
                    ChainNeighbor(
                        input_address=input_address,
                        counterparty_address=counterparty,
                        chain=chain,
                        relationship_type="transfer",
                        direction=direction,
                        tx_hash="",
                        raw={"pair_summary": line},
                    )
                )
                if len(neighbors) >= limit:
                    break
            if len(neighbors) >= limit:
                break
        return neighbors


def _direction_from_transaction(
    input_norm: str,
    from_address: str | None,
    to_address: str | None,
    requested_direction: str,
) -> str:
    if from_address and from_address.casefold() == input_norm:
        return "outbound"
    if to_address and to_address.casefold() == input_norm:
        return "inbound"
    if requested_direction == "IN":
        return "inbound"
    if requested_direction == "OUT":
        return "outbound"
    return "unknown"


def _normalize_direction(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().casefold()
    if normalized in {"in", "inbound"}:
        return "inbound"
    if normalized in {"out", "outbound"}:
        return "outbound"
    return None


def _parse_get_txs_text(text: str) -> list[dict[str, Any]]:
    if not text:
        return []

    transactions: list[dict[str, Any]] = []
    text = text.replace("\\n", "\n")
    for line in text.splitlines():
        line = line.strip().strip('"')
        if not line or "hash:" not in line:
            continue

        tx: dict[str, Any] = {}
        for part in line.split(";"):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            tx[key.strip()] = value.strip()
        if tx:
            transactions.append(tx)

    return transactions


def _amount_from_pair_line(line: str, label: str) -> float:
    match = re.search(rf"{label}:([0-9.]+)", line)
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def configured_bitrace_neighbor_provider() -> BitraceMcpNeighborProvider | None:
    provider = BitraceMcpNeighborProvider()
    return provider if provider.configured else None


def get_one_hop_neighbors(
    address: str,
    chain_id: str = "auto",
    limit: int = 1000,
    provider: ChainNeighborProvider | None = None,
) -> list[ChainNeighbor]:
    active_provider = provider or NotConfiguredChainNeighborProvider()
    return active_provider.get_one_hop_neighbors(address, chain_id=chain_id, limit=limit)


def _decode_mcp_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{"):
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed

    data_lines = []
    for line in stripped.splitlines():
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    for data_line in reversed(data_lines):
        if data_line:
            parsed = json.loads(data_line)
            if isinstance(parsed, dict):
                return parsed
    raise RuntimeError("Unable to decode Bitrace MCP response.")


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def _find_transaction_list(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, list):
        txs = [item for item in value if isinstance(item, dict)]
        if txs and any(("hash" in item or "txHash" in item or "from" in item or "to" in item) for item in txs):
            return txs
    if isinstance(value, dict):
        for key in ("data", "items", "list", "records", "txs", "transactions", "rows"):
            found = _find_transaction_list(value.get(key))
            if found is not None:
                return found
    return None


def _find_chain_value(value: Any) -> str | None:
    value = _maybe_json(value)
    if isinstance(value, dict):
        for key in ("chain", "chainName", "network"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
        for child in value.values():
            found = _find_chain_value(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_chain_value(child)
            if found:
                return found
    if isinstance(value, str):
        for chain in ("tron", "eth", "btc", "bsc", "arbitrum", "avalanche", "base", "optimism", "polygon"):
            if chain in value.casefold():
                return chain
    return None


def _extract_text_content(value: Any) -> str:
    value = _maybe_json(value)
    if isinstance(value, str):
        maybe_unquoted = _maybe_json(value)
        return maybe_unquoted if isinstance(maybe_unquoted, str) else _extract_text_content(maybe_unquoted)
    if isinstance(value, list):
        return "\n".join(part for part in (_extract_text_content(item) for item in value) if part)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return _extract_text_content(value["text"])
        if "content" in value:
            return _extract_text_content(value["content"])
        if "result" in value:
            return _extract_text_content(value["result"])
    return ""


def _normalize_chain(chain_id: str | None) -> str | None:
    if not chain_id:
        return None
    value = chain_id.strip().casefold()
    mapping = {
        "1": "eth",
        "ethereum": "eth",
        "evm-compatible": "eth",
        "evm": "eth",
        "bitcoin": "btc",
        "btc": "btc",
        "tron": "tron",
        "trx": "tron",
        "bsc": "bsc",
        "bnb": "bsc",
        "binance smart chain": "bsc",
        "arbitrum": "arbitrum",
        "avalanche": "avalanche",
        "avax": "avalanche",
        "base": "base",
        "optimism": "optimism",
        "polygon": "polygon",
        "matic": "polygon",
    }
    return mapping.get(value)


def _first_string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return str(value)
    return None
