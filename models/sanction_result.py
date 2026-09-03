from typing import Literal

from pydantic import BaseModel, Field


class AddressProfile(BaseModel):
    address: str
    chain: str | None = None
    address_type: str | None = None
    explorer_url: str | None = None


class SourceEvidence(BaseModel):
    source_title: str | None = None
    source_url: str | None = None
    publication_date: str | None = None
    publisher: str | None = None
    source_description: str | None = None
    source_type: Literal[
        "government",
        "official_list",
        "blockchain_analytics",
        "news",
        "unknown",
    ] = "unknown"


class RelatedSanctionHit(BaseModel):
    input_address: str
    related_address: str
    relationship_depth: int = 1
    relationship_type: str | None = None
    tx_hash: str | None = None
    block_time: str | None = None
    direction: str | None = None
    sanction_authority: str | None = None
    sanctioned_entity: str | None = None
    sanction_date: str | None = None
    source_url: str | None = None
    description: str


class SanctionFinding(BaseModel):
    sanctioned: bool = False
    direct_sanction_hit: bool = False
    related_sanction_hit: bool = False
    sanction_authority: str | None = Field(
        default=None,
        description="Examples: OFAC, UK OFSI, EU, UN, Chainalysis, TRM, Elliptic.",
    )
    sanctioned_entity: str | None = None
    sanction_date: str | None = None
    sanction_reason: str | None = None
    list_name: str | None = None
    program: str | None = None


class SanctionResult(BaseModel):
    query: str | None = None
    query_type: Literal["address", "entity", "unknown"] = "unknown"
    address_profile: AddressProfile
    finding: SanctionFinding
    related_hits: list[RelatedSanctionHit] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    summary: str
    gaps: list[str] = Field(default_factory=list)
