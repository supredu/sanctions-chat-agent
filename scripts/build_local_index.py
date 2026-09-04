from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.local_sanctions import (
    load_ftm_jsonl_entities,
    load_ftm_jsonl_hits,
    load_ofac_advanced_xml_entities,
    load_ofac_advanced_xml_hits,
    load_uk_sanctions_xml_entities,
    load_uk_sanctions_xml_hits,
    normalize_address,
    normalize_name,
    ftm_jsonl_files,
)


DEFAULT_INDEX_PATH = Path("data/sanctions_index.sqlite")


def build_index(index_path: Path = DEFAULT_INDEX_PATH) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = index_path.with_suffix(".tmp.sqlite")
    if temp_path.exists():
        temp_path.unlink()

    connection = sqlite3.connect(temp_path)
    try:
        create_schema(connection)
        insert_address_hits(connection)
        insert_entity_records(connection)
        connection.execute("PRAGMA optimize")
        connection.commit()
    finally:
        connection.close()

    temp_path.replace(index_path)


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode = WAL;

        CREATE TABLE address_hits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normalized_address TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE INDEX idx_address_hits_normalized_address
        ON address_hits(normalized_address);

        CREATE TABLE entity_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normalized_name TEXT NOT NULL,
            normalized_aliases TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE INDEX idx_entity_records_normalized_name
        ON entity_records(normalized_name);
        """
    )


def insert_address_hits(connection: sqlite3.Connection) -> None:
    hits = load_ofac_advanced_xml_hits()
    hits.extend(load_uk_sanctions_xml_hits())
    for path in ftm_jsonl_files():
        hits.extend(load_ftm_jsonl_hits(path))

    connection.executemany(
        "INSERT INTO address_hits (normalized_address, payload_json) VALUES (?, ?)",
        [
            (
                normalize_address(hit.address),
                json.dumps(hit.to_dict(), ensure_ascii=False, separators=(",", ":")),
            )
            for hit in hits
        ],
    )


def insert_entity_records(connection: sqlite3.Connection) -> None:
    records = load_ofac_advanced_xml_entities()
    records.extend(load_uk_sanctions_xml_entities())
    for path in ftm_jsonl_files():
        records.extend(load_ftm_jsonl_entities(path))

    rows = []
    for record in records:
        payload = record.to_dict()
        rows.append(
            (
                normalize_name(record.name),
                " ".join(normalize_name(alias) for alias in record.aliases),
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            )
        )

    connection.executemany(
        "INSERT INTO entity_records (normalized_name, normalized_aliases, payload_json) VALUES (?, ?, ?)",
        rows,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a compact local sanctions SQLite index.")
    parser.add_argument("--output", type=Path, default=DEFAULT_INDEX_PATH)
    args = parser.parse_args()

    build_index(args.output)
    print(f"Built local sanctions index: {args.output}")


if __name__ == "__main__":
    main()
