from models import AddressProfile, SanctionFinding, SanctionResult
from sanction_agents.sanction_agent import extract_json_object


def test_sanction_result_serializes() -> None:
    result = SanctionResult(
        address_profile=AddressProfile(address="0x0000000000000000000000000000000000000000"),
        finding=SanctionFinding(),
        summary="No live source lookup has been performed yet.",
    )

    payload = result.model_dump()

    assert payload["address_profile"]["address"].startswith("0x")
    assert payload["finding"]["sanctioned"] is False


def test_extract_json_from_markdown_fence() -> None:
    raw = """Here is the result:

```json
{"summary": "ok"}
```
"""

    assert extract_json_object(raw) == '{"summary": "ok"}'
