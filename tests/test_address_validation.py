from tools.blockchain_lookup import classify_address


def test_classifies_evm_address() -> None:
    result = classify_address("0x0000000000000000000000000000000000000000")

    assert result["valid"] is True
    assert result["chain"] == "EVM-compatible"


def test_rejects_invalid_address() -> None:
    result = classify_address("not-an-address")

    assert result["valid"] is False
    assert result["chain"] is None
