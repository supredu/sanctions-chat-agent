import re

from agents import function_tool


EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
BTC_ADDRESS_RE = re.compile(r"^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}$")
TRON_ADDRESS_RE = re.compile(r"^T[A-Za-z1-9]{33}$")
SOLANA_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def classify_address(address: str) -> dict[str, str | bool | None]:
    normalized = address.strip()

    if EVM_ADDRESS_RE.match(normalized):
        return {
            "valid": True,
            "chain": "EVM-compatible",
            "address_type": "account_or_contract",
            "explorer_url": f"https://etherscan.io/address/{normalized}",
        }

    if BTC_ADDRESS_RE.match(normalized):
        return {
            "valid": True,
            "chain": "Bitcoin",
            "address_type": "wallet",
            "explorer_url": f"https://www.blockchain.com/explorer/addresses/btc/{normalized}",
        }

    if TRON_ADDRESS_RE.match(normalized):
        return {
            "valid": True,
            "chain": "TRON",
            "address_type": "wallet_or_contract",
            "explorer_url": f"https://tronscan.org/#/address/{normalized}",
        }

    if SOLANA_ADDRESS_RE.match(normalized):
        return {
            "valid": True,
            "chain": "Solana",
            "address_type": "account",
            "explorer_url": f"https://solscan.io/account/{normalized}",
        }

    return {
        "valid": False,
        "chain": None,
        "address_type": None,
        "explorer_url": None,
    }


@function_tool
def describe_blockchain_address(address: str) -> dict[str, str | bool | None]:
    """Classify a blockchain address and suggest a default explorer URL."""
    return classify_address(address)
