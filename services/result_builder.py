from typing import Any

from models import AddressProfile, RelatedSanctionHit, SanctionFinding, SanctionResult, SourceEvidence
from tools.blockchain_lookup import classify_address


def _join(values: list[str] | None) -> str | None:
    if not values:
        return None
    return "; ".join(value for value in values if value)


def _first(values: list[str] | None) -> str | None:
    return values[0] if values else None


def _source_type(source: str | None) -> str:
    if source in {"OFAC Advanced XML", "UK Sanctions List XML"}:
        return "official_list"
    if source and source.startswith("FollowTheMoney"):
        return "blockchain_analytics"
    return "unknown"


def _evidence_from_hit(hit: dict[str, Any]) -> SourceEvidence:
    source_urls = hit.get("source_urls") or []
    return SourceEvidence(
        source_title=hit.get("source") or hit.get("list_name"),
        source_url=_first(source_urls),
        publication_date=hit.get("publication_date"),
        publisher=hit.get("authority"),
        source_description=hit.get("source_description"),
        source_type=_source_type(hit.get("source")),
    )


def _best_direct_hit(hits: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not hits:
        return None

    official_hits = [hit for hit in hits if hit.get("source") in {"OFAC Advanced XML", "UK Sanctions List XML"}]
    dated_hits = [hit for hit in official_hits if hit.get("sanction_dates")]
    return (dated_hits or official_hits or hits)[0]


def build_sanction_result_from_local_payload(payload: dict[str, Any]) -> SanctionResult:
    query = payload.get("query") or ""
    query_type = payload.get("query_type") or "unknown"
    hits = payload.get("hits") or []
    best_hit = _best_direct_hit(hits)

    address_profile_payload = payload.get("address_profile")
    if address_profile_payload:
        address_profile = AddressProfile(**address_profile_payload)
    else:
        address_profile = AddressProfile(address=query, chain=None, address_type="entity_name")

    finding = SanctionFinding(
        sanctioned=bool(best_hit),
        direct_sanction_hit=bool(best_hit),
        related_sanction_hit=bool(payload.get("related_hits")),
        sanction_authority=best_hit.get("authority") if best_hit else None,
        sanctioned_entity=(best_hit.get("entity_name") or best_hit.get("name")) if best_hit else None,
        sanction_date=_first(best_hit.get("sanction_dates")) if best_hit else None,
        sanction_reason=_join(best_hit.get("reason") or best_hit.get("reasons")) if best_hit else None,
        list_name=best_hit.get("list_name") if best_hit else None,
        program=_join(best_hit.get("program") or best_hit.get("programs")) if best_hit else None,
    )

    evidence = [_evidence_from_hit(hit) for hit in hits]
    related_hits = [
        RelatedSanctionHit(**related_hit)
        for related_hit in payload.get("related_hits", [])
    ]

    if best_hit:
        summary = (
            f"Local sources found a direct sanctions match for {query}: "
            f"{finding.sanctioned_entity or 'unknown entity'} via "
            f"{finding.sanction_authority or 'unknown authority'}."
        )
        confidence = "high" if best_hit.get("source") in {"OFAC Advanced XML", "UK Sanctions List XML"} else "medium"
        gaps = ["Live web publication pages have not been checked yet."]
    elif related_hits:
        summary = f"Local sources did not directly match {query}, but one-hop related sanctions hits were found."
        confidence = "medium"
        gaps = ["One-hop relationship data depends on the configured chain-neighbor API provider."]
    else:
        summary = f"No direct local sanctions match was found for {query}."
        confidence = "unknown"
        gaps = [
            "Only local source files were checked.",
            "Live web search and official publication pages have not been checked yet.",
        ]

    return SanctionResult(
        query=query,
        query_type=query_type,
        address_profile=address_profile,
        finding=finding,
        related_hits=related_hits,
        evidence=evidence,
        confidence=confidence,
        summary=summary,
        gaps=gaps,
    )


def build_address_profile(query: str) -> AddressProfile:
    profile = classify_address(query)
    return AddressProfile(
        address=query.strip(),
        chain=profile["chain"] if profile["valid"] else None,
        address_type=profile["address_type"] if profile["valid"] else None,
        explorer_url=profile["explorer_url"] if profile["valid"] else None,
    )
