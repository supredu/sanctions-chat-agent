from services.query_router import lookup_local_query
from services.result_builder import build_sanction_result_from_local_payload


def test_builds_standard_result_for_direct_address_hit() -> None:
    payload = lookup_local_query("0xE950DC316b836e4EeFb8308bf32Bf7C72a1358FF")
    result = build_sanction_result_from_local_payload(payload)

    assert result.query_type == "address"
    assert result.finding.direct_sanction_hit is True
    assert result.finding.sanctioned_entity
    assert result.finding.sanction_date == "2024-03-27"


def test_builds_standard_result_for_entity_hit() -> None:
    payload = lookup_local_query("Gaza", entity_limit=3)
    result = build_sanction_result_from_local_payload(payload)

    assert result.query_type == "entity"
    assert result.finding.direct_sanction_hit is True
    assert "Gaza" in (result.finding.sanctioned_entity or "")
