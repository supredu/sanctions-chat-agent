import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from agents import function_tool


SOURCE_DIR = Path("source_files")
SQLITE_INDEX = Path("data/sanctions_index.sqlite")
OFAC_ADVANCED_XML = SOURCE_DIR / "sdn_advanced.xml"
OFAC_ADVANCED_NS = {
    "ofac": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ADVANCED_XML"
}


@dataclass
class LocalSanctionHit:
    address: str
    currency: str | None
    source: str
    source_file: str
    entity_name: str | None = None
    entity_id: str | None = None
    authority: str | None = None
    authority_id: str | None = None
    list_name: str | None = None
    program: list[str] = field(default_factory=list)
    reason: list[str] = field(default_factory=list)
    sanction_dates: list[str] = field(default_factory=list)
    publication_date: str | None = None
    source_urls: list[str] = field(default_factory=list)
    source_description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "currency": self.currency,
            "source": self.source,
            "source_file": self.source_file,
            "entity_name": self.entity_name,
            "entity_id": self.entity_id,
            "authority": self.authority,
            "authority_id": self.authority_id,
            "list_name": self.list_name,
            "program": self.program,
            "reason": self.reason,
            "sanction_dates": self.sanction_dates,
            "publication_date": self.publication_date,
            "source_urls": self.source_urls,
            "source_description": self.source_description,
            "metadata": self.metadata,
        }


@dataclass
class LocalEntityRecord:
    entity_id: str
    name: str
    source: str
    source_file: str
    authority: str | None = None
    authority_id: str | None = None
    list_name: str | None = None
    aliases: list[str] = field(default_factory=list)
    programs: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    sanction_dates: list[str] = field(default_factory=list)
    publication_date: str | None = None
    source_urls: list[str] = field(default_factory=list)
    addresses: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "source": self.source,
            "source_file": self.source_file,
            "authority": self.authority,
            "authority_id": self.authority_id,
            "list_name": self.list_name,
            "aliases": self.aliases,
            "programs": self.programs,
            "reasons": self.reasons,
            "sanction_dates": self.sanction_dates,
            "publication_date": self.publication_date,
            "source_urls": self.source_urls,
            "addresses": self.addresses,
            "metadata": self.metadata,
        }


def normalize_address(address: str) -> str:
    clean = address.strip()
    if clean.startswith("0x") or clean.startswith("0X"):
        return clean.lower()
    return clean


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", name.casefold())).strip()


def fuzzy_score_name(query: str, candidate: str, aliases: list[str] | None = None) -> int:
    normalized_query = normalize_name(query)
    best = 0

    for raw_candidate in [candidate, *(aliases or [])]:
        normalized_candidate = normalize_name(raw_candidate)
        if not normalized_query or not normalized_candidate:
            continue
        candidate_tokens = normalized_candidate.split()
        if normalized_query == normalized_candidate:
            best = max(best, 100)
        elif normalized_query in candidate_tokens:
            best = max(best, 95)
        elif normalized_candidate.startswith(normalized_query):
            best = max(best, 90)
        elif normalized_query in normalized_candidate:
            best = max(best, 80)
        elif all(token in normalized_candidate for token in normalized_query.split()):
            best = max(best, 65)

    return best


def _first(values: list[str] | None) -> str | None:
    return values[0] if values else None


def _values(properties: dict[str, Any], key: str) -> list[str]:
    value = properties.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _date_from_node(node: ET.Element | None) -> str | None:
    if node is None:
        return None

    year = node.findtext("ofac:Year", namespaces=OFAC_ADVANCED_NS)
    month = node.findtext("ofac:Month", namespaces=OFAC_ADVANCED_NS)
    day = node.findtext("ofac:Day", namespaces=OFAC_ADVANCED_NS)
    if not year or not month or not day:
        return None

    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _primary_identity_name(identity: ET.Element) -> str | None:
    primary_alias = identity.find("ofac:Alias[@Primary='true']", OFAC_ADVANCED_NS)
    alias = primary_alias if primary_alias is not None else identity.find("ofac:Alias", OFAC_ADVANCED_NS)
    if alias is None:
        return None

    parts = [
        value.text.strip()
        for value in alias.findall(".//ofac:NamePartValue", OFAC_ADVANCED_NS)
        if value.text and value.text.strip()
    ]
    return " ".join(parts) if parts else None


def _identity_names(identity: ET.Element) -> tuple[str | None, list[str]]:
    names: list[tuple[bool, str]] = []
    for alias in identity.findall("ofac:Alias", OFAC_ADVANCED_NS):
        parts = [
            value.text.strip()
            for value in alias.findall(".//ofac:NamePartValue", OFAC_ADVANCED_NS)
            if value.text and value.text.strip()
        ]
        if parts:
            names.append((alias.attrib.get("Primary") == "true", " ".join(parts)))

    primary = next((name for is_primary, name in names if is_primary), None)
    if primary is None and names:
        primary = names[0][1]
    aliases = sorted({name for _, name in names if name != primary})
    return primary, aliases


def _reference_values(root: ET.Element, tag_name: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for node in root.findall(f".//ofac:{tag_name}", OFAC_ADVANCED_NS):
        node_id = node.attrib.get("ID")
        label = (
            node.text
            or node.attrib.get("Description")
            or node.attrib.get("LegalBasisShortRef")
            or ""
        ).strip()
        if node_id:
            values[node_id] = label
    return values


def load_ofac_advanced_xml_hits(path: Path = OFAC_ADVANCED_XML) -> list[LocalSanctionHit]:
    if not path.exists():
        return []

    root = ET.parse(path).getroot()
    publication_date = _date_from_node(root.find("ofac:DateOfIssue", OFAC_ADVANCED_NS))

    feature_types = _reference_values(root, "FeatureType")
    list_names = _reference_values(root, "List")
    legal_basis_names = _reference_values(root, "LegalBasis")
    crypto_feature_types = {
        feature_type_id: label.replace("Digital Currency Address - ", "")
        for feature_type_id, label in feature_types.items()
        if label.startswith("Digital Currency Address - ")
    }

    identity_to_profile: dict[str, str] = {}
    identity_to_name: dict[str, str | None] = {}
    for profile in root.findall(".//ofac:Profile", OFAC_ADVANCED_NS):
        profile_id = profile.attrib.get("ID")
        for identity in profile.findall("ofac:Identity", OFAC_ADVANCED_NS):
            identity_id = identity.attrib.get("ID")
            if not identity_id or not profile_id:
                continue
            identity_to_profile[identity_id] = profile_id
            identity_to_name[identity_id] = _primary_identity_name(identity)

    entries_by_profile: dict[str, list[dict[str, Any]]] = {}
    for entry in root.findall(".//ofac:SanctionsEntry", OFAC_ADVANCED_NS):
        profile_id = entry.attrib.get("ProfileID")
        if not profile_id:
            continue

        dates: list[str] = []
        legal_basis: list[str] = []
        programs: list[str] = []

        for event in entry.findall("ofac:EntryEvent", OFAC_ADVANCED_NS):
            date = _date_from_node(event.find("ofac:Date", OFAC_ADVANCED_NS))
            if date:
                dates.append(date)
            legal_basis_id = event.attrib.get("LegalBasisID")
            if legal_basis_id:
                legal_basis.append(legal_basis_names.get(legal_basis_id, legal_basis_id))

        for measure in entry.findall("ofac:SanctionsMeasure", OFAC_ADVANCED_NS):
            comment = measure.findtext("ofac:Comment", namespaces=OFAC_ADVANCED_NS)
            if comment and comment.strip():
                programs.append(comment.strip())

        entries_by_profile.setdefault(profile_id, []).append(
            {
                "entry_id": entry.attrib.get("ID"),
                "list_name": list_names.get(entry.attrib.get("ListID", ""), entry.attrib.get("ListID")),
                "dates": sorted(set(dates)),
                "legal_basis": sorted(set(legal_basis)),
                "programs": sorted(set(programs)),
            }
        )

    hits: list[LocalSanctionHit] = []
    for feature in root.findall(".//ofac:Feature", OFAC_ADVANCED_NS):
        feature_type_id = feature.attrib.get("FeatureTypeID")
        if feature_type_id not in crypto_feature_types:
            continue

        address = feature.findtext(".//ofac:VersionDetail", namespaces=OFAC_ADVANCED_NS)
        if not address:
            continue

        identity_ref = feature.find("ofac:IdentityReference", OFAC_ADVANCED_NS)
        identity_id = identity_ref.attrib.get("IdentityID") if identity_ref is not None else None
        profile_id = identity_to_profile.get(identity_id or "")
        entries = entries_by_profile.get(profile_id or "", [])

        if not entries:
            hits.append(
                LocalSanctionHit(
                    address=address.strip(),
                    currency=crypto_feature_types[feature_type_id],
                    source="OFAC Advanced XML",
                    source_file=str(path),
                    entity_name=identity_to_name.get(identity_id or ""),
                    entity_id=identity_id,
                    authority="Office of Foreign Assets Control",
                    publication_date=publication_date,
                    source_description="OFAC Advanced XML local source file.",
                )
            )
            continue

        for entry in entries:
            hits.append(
                LocalSanctionHit(
                    address=address.strip(),
                    currency=crypto_feature_types[feature_type_id],
                    source="OFAC Advanced XML",
                    source_file=str(path),
                    entity_name=identity_to_name.get(identity_id or ""),
                    entity_id=identity_id,
                    authority="Office of Foreign Assets Control",
                    authority_id=entry.get("entry_id"),
                    list_name=entry.get("list_name"),
                    program=entry.get("programs", []),
                    reason=entry.get("legal_basis", []),
                    sanction_dates=entry.get("dates", []),
                    publication_date=publication_date,
                    source_urls=["https://sanctionssearch.ofac.treas.gov/"],
                    source_description="OFAC Advanced XML local source file.",
                    metadata={"profile_id": profile_id, "feature_id": feature.attrib.get("ID")},
                )
            )

    return hits


def load_ofac_advanced_xml_entities(path: Path = OFAC_ADVANCED_XML) -> list[LocalEntityRecord]:
    if not path.exists():
        return []

    root = ET.parse(path).getroot()
    publication_date = _date_from_node(root.find("ofac:DateOfIssue", OFAC_ADVANCED_NS))

    feature_types = _reference_values(root, "FeatureType")
    list_names = _reference_values(root, "List")
    legal_basis_names = _reference_values(root, "LegalBasis")
    crypto_feature_types = {
        feature_type_id: label.replace("Digital Currency Address - ", "")
        for feature_type_id, label in feature_types.items()
        if label.startswith("Digital Currency Address - ")
    }

    identity_to_profile: dict[str, str] = {}
    identity_to_name: dict[str, str | None] = {}
    identity_to_aliases: dict[str, list[str]] = {}
    addresses_by_identity: dict[str, list[dict[str, Any]]] = {}

    for profile in root.findall(".//ofac:Profile", OFAC_ADVANCED_NS):
        profile_id = profile.attrib.get("ID")
        for identity in profile.findall("ofac:Identity", OFAC_ADVANCED_NS):
            identity_id = identity.attrib.get("ID")
            if not identity_id or not profile_id:
                continue
            name, aliases = _identity_names(identity)
            identity_to_profile[identity_id] = profile_id
            identity_to_name[identity_id] = name
            identity_to_aliases[identity_id] = aliases

        for feature in profile.findall("ofac:Feature", OFAC_ADVANCED_NS):
            feature_type_id = feature.attrib.get("FeatureTypeID")
            if feature_type_id not in crypto_feature_types:
                continue
            address = feature.findtext(".//ofac:VersionDetail", namespaces=OFAC_ADVANCED_NS)
            identity_ref = feature.find("ofac:IdentityReference", OFAC_ADVANCED_NS)
            identity_id = identity_ref.attrib.get("IdentityID") if identity_ref is not None else None
            if address and identity_id:
                addresses_by_identity.setdefault(identity_id, []).append(
                    {
                        "address": address.strip(),
                        "currency": crypto_feature_types[feature_type_id],
                        "source": "OFAC Advanced XML",
                    }
                )

    entries_by_profile: dict[str, list[dict[str, Any]]] = {}
    for entry in root.findall(".//ofac:SanctionsEntry", OFAC_ADVANCED_NS):
        profile_id = entry.attrib.get("ProfileID")
        if not profile_id:
            continue

        dates: list[str] = []
        legal_basis: list[str] = []
        programs: list[str] = []

        for event in entry.findall("ofac:EntryEvent", OFAC_ADVANCED_NS):
            date = _date_from_node(event.find("ofac:Date", OFAC_ADVANCED_NS))
            if date:
                dates.append(date)
            legal_basis_id = event.attrib.get("LegalBasisID")
            if legal_basis_id:
                legal_basis.append(legal_basis_names.get(legal_basis_id, legal_basis_id))

        for measure in entry.findall("ofac:SanctionsMeasure", OFAC_ADVANCED_NS):
            comment = measure.findtext("ofac:Comment", namespaces=OFAC_ADVANCED_NS)
            if comment and comment.strip():
                programs.append(comment.strip())

        entries_by_profile.setdefault(profile_id, []).append(
            {
                "entry_id": entry.attrib.get("ID"),
                "list_name": list_names.get(entry.attrib.get("ListID", ""), entry.attrib.get("ListID")),
                "dates": sorted(set(dates)),
                "legal_basis": sorted(set(legal_basis)),
                "programs": sorted(set(programs)),
            }
        )

    records: list[LocalEntityRecord] = []
    for identity_id, name in identity_to_name.items():
        if not name:
            continue

        profile_id = identity_to_profile.get(identity_id)
        entries = entries_by_profile.get(profile_id or "", [{}])
        for entry in entries:
            records.append(
                LocalEntityRecord(
                    entity_id=identity_id,
                    name=name,
                    source="OFAC Advanced XML",
                    source_file=str(path),
                    authority="Office of Foreign Assets Control",
                    authority_id=entry.get("entry_id"),
                    list_name=entry.get("list_name"),
                    aliases=identity_to_aliases.get(identity_id, []),
                    programs=entry.get("programs", []),
                    reasons=entry.get("legal_basis", []),
                    sanction_dates=entry.get("dates", []),
                    publication_date=publication_date,
                    source_urls=["https://sanctionssearch.ofac.treas.gov/"],
                    addresses=addresses_by_identity.get(identity_id, []),
                    metadata={"profile_id": profile_id},
                )
            )

    return records


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not path.exists():
        return items

    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def load_ftm_jsonl_hits(path: Path) -> list[LocalSanctionHit]:
    items = iter_jsonl(path)
    if not items:
        return []

    entities = {item["id"]: item for item in items if "id" in item}
    wallets = [item for item in items if item.get("schema") == "CryptoWallet"]
    sanctions = [item for item in items if item.get("schema") == "Sanction"]

    sanctions_by_entity: dict[str, list[dict[str, Any]]] = {}
    for sanction in sanctions:
        for entity_id in _values(sanction.get("properties") or {}, "entity"):
            sanctions_by_entity.setdefault(entity_id, []).append(sanction)

    hits: list[LocalSanctionHit] = []
    for wallet in wallets:
        wallet_props = wallet.get("properties") or {}
        public_keys = _values(wallet_props, "publicKey") or [wallet.get("caption", "")]
        currencies = _values(wallet_props, "currency")
        holder_ids = _values(wallet_props, "holder")
        sanction_records = list(sanctions_by_entity.get(wallet.get("id", ""), []))

        for holder_id in holder_ids:
            sanction_records.extend(sanctions_by_entity.get(holder_id, []))

        if not sanction_records:
            sanction_records = [{}]

        for public_key in public_keys:
            if not public_key or public_key == "Cryptocurrency wallet":
                continue

            for sanction in sanction_records:
                sanction_props = sanction.get("properties") or {}
                linked_entity_id = _first(_values(sanction_props, "entity"))
                holder_id = _first(holder_ids)
                entity_id = holder_id or linked_entity_id or wallet.get("id")
                entity = entities.get(entity_id or "", {})
                entity_props = entity.get("properties") or {}
                source_urls = _values(sanction_props, "sourceUrl") or _values(entity_props, "sourceUrl")

                hits.append(
                    LocalSanctionHit(
                        address=public_key.strip(),
                        currency=_first(currencies),
                        source=f"FollowTheMoney JSONL: {','.join(wallet.get('datasets', []))}",
                        source_file=str(path),
                        entity_name=entity.get("caption") or _first(_values(entity_props, "name")),
                        entity_id=entity_id,
                        authority=_first(_values(sanction_props, "authority")),
                        authority_id=_first(_values(sanction_props, "authorityId")),
                        list_name=_first(wallet.get("datasets", [])),
                        program=_values(sanction_props, "program") or _values(sanction_props, "programId"),
                        reason=_values(sanction_props, "reason"),
                        sanction_dates=[],
                        publication_date=None,
                        source_urls=source_urls,
                        source_description=(
                            "FollowTheMoney JSONL entity export. "
                            "It can include third-party normalized sanctions and crypto wallet data. "
                            "Dates from this source are treated as third-party metadata, not official "
                            "sanction or publication dates."
                        ),
                        metadata={
                            "wallet_id": wallet.get("id"),
                            "wallet_caption": wallet.get("caption"),
                            "wallet_topics": _values(wallet_props, "topics"),
                            "account_id": _first(_values(wallet_props, "accountId")),
                            "managing_exchange": _first(_values(wallet_props, "managingExchange")),
                            "sanction_id": sanction.get("id"),
                            "third_party_first_seen": wallet.get("first_seen"),
                            "third_party_last_seen": wallet.get("last_seen"),
                            "third_party_last_change": wallet.get("last_change"),
                            "third_party_sanction_start_date": _values(sanction_props, "startDate"),
                            "third_party_sanction_end_date": _values(sanction_props, "endDate"),
                            "third_party_sanction_modified_at": _values(sanction_props, "modifiedAt"),
                        },
                    )
                )

    return hits


def load_ftm_jsonl_entities(path: Path) -> list[LocalEntityRecord]:
    items = iter_jsonl(path)
    if not items:
        return []

    entities = {item["id"]: item for item in items if "id" in item}
    wallets = [item for item in items if item.get("schema") == "CryptoWallet"]
    sanctions = [item for item in items if item.get("schema") == "Sanction"]

    sanctions_by_entity: dict[str, list[dict[str, Any]]] = {}
    for sanction in sanctions:
        for entity_id in _values(sanction.get("properties") or {}, "entity"):
            sanctions_by_entity.setdefault(entity_id, []).append(sanction)

    addresses_by_entity: dict[str, list[dict[str, Any]]] = {}
    for wallet in wallets:
        wallet_props = wallet.get("properties") or {}
        public_keys = _values(wallet_props, "publicKey") or [wallet.get("caption", "")]
        holders = _values(wallet_props, "holder") or [wallet.get("id", "")]
        currency = _first(_values(wallet_props, "currency"))
        for holder_id in holders:
            for public_key in public_keys:
                if public_key and public_key != "Cryptocurrency wallet":
                    addresses_by_entity.setdefault(holder_id, []).append(
                        {
                            "address": public_key,
                            "currency": currency,
                            "source": f"FollowTheMoney JSONL: {','.join(wallet.get('datasets', []))}",
                        }
                    )

    records: list[LocalEntityRecord] = []
    skipped_schemas = {"Address", "CryptoWallet", "Identification", "Passport", "Sanction"}
    for entity_id, entity in entities.items():
        if entity.get("schema") in skipped_schemas:
            continue

        entity_props = entity.get("properties") or {}
        name = entity.get("caption") or _first(_values(entity_props, "name"))
        if not name:
            continue

        related_sanctions = sanctions_by_entity.get(entity_id, [{}])
        for sanction in related_sanctions:
            sanction_props = sanction.get("properties") or {}
            records.append(
                LocalEntityRecord(
                    entity_id=entity_id,
                    name=name,
                    source=f"FollowTheMoney JSONL: {','.join(entity.get('datasets', []))}",
                    source_file=str(path),
                    authority=_first(_values(sanction_props, "authority")),
                    authority_id=_first(_values(sanction_props, "authorityId")),
                    list_name=_first(entity.get("datasets", [])),
                    aliases=_values(entity_props, "alias") + _values(entity_props, "weakAlias"),
                    programs=_values(sanction_props, "program") or _values(sanction_props, "programId"),
                    reasons=_values(sanction_props, "reason"),
                    sanction_dates=[],
                    publication_date=None,
                    source_urls=_values(sanction_props, "sourceUrl") or _values(entity_props, "sourceUrl"),
                    addresses=addresses_by_entity.get(entity_id, []),
                    metadata={
                        "schema": entity.get("schema"),
                        "third_party_first_seen": entity.get("first_seen"),
                        "third_party_last_seen": entity.get("last_seen"),
                        "third_party_last_change": entity.get("last_change"),
                        "third_party_sanction_start_date": _values(sanction_props, "startDate"),
                        "third_party_sanction_modified_at": _values(sanction_props, "modifiedAt"),
                    },
                )
            )

    return records


def ftm_jsonl_files() -> list[Path]:
    return sorted(SOURCE_DIR.glob("entities.ftm.*.json"))


def sqlite_index_exists(path: Path = SQLITE_INDEX) -> bool:
    return path.exists()


def lookup_sqlite_sanctions(address: str, path: Path = SQLITE_INDEX) -> list[dict[str, Any]]:
    if not sqlite_index_exists(path):
        return []

    normalized_address = normalize_address(address)
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM address_hits WHERE normalized_address = ?",
            (normalized_address,),
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def search_sqlite_entities(query: str, limit: int = 10, path: Path = SQLITE_INDEX) -> list[dict[str, Any]]:
    if not sqlite_index_exists(path):
        return []

    normalized_query = normalize_name(query)
    if not normalized_query:
        return []

    tokens = normalized_query.split()
    params: list[str | int] = []
    clauses = []
    for token in tokens:
        like_token = f"%{token}%"
        clauses.append("(normalized_name LIKE ? OR normalized_aliases LIKE ?)")
        params.extend([like_token, like_token])

    where_clause = " AND ".join(clauses)
    params.append(max(limit * 50, 200))
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            f"""
            SELECT payload_json
            FROM entity_records
            WHERE {where_clause}
            LIMIT ?
            """,
            params,
        ).fetchall()

    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        record = json.loads(row[0])
        score = fuzzy_score_name(query, record["name"], record.get("aliases", []))
        if score <= 0:
            continue
        if record.get("source") == "OFAC Advanced XML":
            score += 5
        if record.get("sanction_dates"):
            score += 3
        if record.get("addresses"):
            score += 8
        scored.append((score, record))

    scored.sort(key=lambda item: (-item[0], item[1].get("name") or ""))
    return [{"score": score, **record} for score, record in scored[:limit]]


@lru_cache(maxsize=1)
def load_local_sanctions_index() -> dict[str, list[dict[str, Any]]]:
    hits: list[LocalSanctionHit] = []
    hits.extend(load_ofac_advanced_xml_hits())
    for path in ftm_jsonl_files():
        hits.extend(load_ftm_jsonl_hits(path))

    index: dict[str, list[dict[str, Any]]] = {}
    for hit in hits:
        index.setdefault(normalize_address(hit.address), []).append(hit.to_dict())
    return index


def lookup_local_sanctions(address: str) -> list[dict[str, Any]]:
    if sqlite_index_exists():
        return lookup_sqlite_sanctions(address)
    return load_local_sanctions_index().get(normalize_address(address), [])


@lru_cache(maxsize=1)
def load_local_entity_records() -> list[dict[str, Any]]:
    records: list[LocalEntityRecord] = []
    records.extend(load_ofac_advanced_xml_entities())
    for path in ftm_jsonl_files():
        records.extend(load_ftm_jsonl_entities(path))
    return [record.to_dict() for record in records]


def search_local_entities(query: str, limit: int = 10) -> list[dict[str, Any]]:
    if sqlite_index_exists():
        return search_sqlite_entities(query, limit=limit)

    scored: list[tuple[int, dict[str, Any]]] = []
    for record in load_local_entity_records():
        score = fuzzy_score_name(query, record["name"], record.get("aliases", []))
        if score <= 0:
            continue
        if record.get("source") == "OFAC Advanced XML":
            score += 5
        if record.get("sanction_dates"):
            score += 3
        if record.get("addresses"):
            score += 8
        scored.append((score, record))

    scored.sort(key=lambda item: (-item[0], item[1].get("name") or ""))
    return [{"score": score, **record} for score, record in scored[:limit]]


@function_tool
def query_local_sanctions_sources(address: str) -> dict[str, Any]:
    """Look up a blockchain address in local OFAC XML and third-party JSONL sanctions files."""
    hits = lookup_local_sanctions(address)
    return {
        "address": address,
        "normalized_address": normalize_address(address),
        "hit_count": len(hits),
        "hits": hits,
    }


@function_tool
def search_local_sanctioned_entities(query: str, limit: int = 10) -> dict[str, Any]:
    """Fuzzy-search sanctioned entity names in local OFAC XML and third-party JSONL files."""
    hits = search_local_entities(query, limit=limit)
    return {
        "query": query,
        "hit_count": len(hits),
        "hits": hits,
    }
