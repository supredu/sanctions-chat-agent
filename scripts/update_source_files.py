from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_local_index import build_index


SOURCE_DIR = PROJECT_ROOT / "source_files"
DATA_DIR = PROJECT_ROOT / "data"
MANIFEST_PATH = DATA_DIR / "source_manifest.json"
DEFAULT_INDEX_PATH = DATA_DIR / "sanctions_index.sqlite"


@dataclass(frozen=True)
class SourceDownload:
    key: str
    url: str
    output_path: Path
    min_bytes: int


SOURCES = {
    "ofac": SourceDownload(
        key="ofac",
        url="https://sanctionslistservice.ofac.treas.gov/api/download/sdn_advanced.xml",
        output_path=SOURCE_DIR / "sdn_advanced.xml",
        min_bytes=20_000_000,
    ),
    "uk": SourceDownload(
        key="uk",
        url="https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml",
        output_path=SOURCE_DIR / "UK-Sanctions-List.xml",
        min_bytes=1_000_000,
    ),
}


def download_file(source: SourceDownload, timeout: int, retries: int) -> dict[str, str | int]:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        temp_path = source.output_path.with_suffix(source.output_path.suffix + ".download")
        try:
            _download_to_path(source.url, temp_path, timeout)
            size = temp_path.stat().st_size
            if size < source.min_bytes:
                raise RuntimeError(
                    f"{source.key} download too small: {size} bytes, expected at least {source.min_bytes}."
                )
            _validate_xml(temp_path)
            digest = _sha256(temp_path)
            temp_path.replace(source.output_path)
            return {
                "key": source.key,
                "url": source.url,
                "path": str(source.output_path.relative_to(PROJECT_ROOT)),
                "bytes": size,
                "sha256": digest,
                "updated_at": _utc_now(),
            }
        except Exception as exc:
            last_error = exc
            temp_path.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(min(2**attempt, 10))

    raise RuntimeError(f"Failed to update {source.key}: {last_error}") from last_error


def _download_to_path(url: str, path: Path, timeout: int) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "sanctions-chat-agent-data-updater/0.1",
            "Accept": "application/xml,text/xml,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with path.open("wb") as file:
            shutil.copyfileobj(response, file)


def _validate_xml(path: Path) -> None:
    # iterparse streams the file and catches malformed partial downloads without
    # loading the 100MB+ OFAC file into memory.
    for _, _ in ET.iterparse(path, events=("start",)):
        break
    for _, _ in ET.iterparse(path, events=("end",)):
        pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_manifest(records: list[dict[str, str | int]], rebuilt_index: bool) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _utc_now(),
        "rebuilt_index": rebuilt_index,
        "sources": records,
    }

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=DATA_DIR,
        delete=False,
        prefix="source_manifest.",
        suffix=".tmp",
    ) as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
        temp_name = file.name
    Path(temp_name).replace(MANIFEST_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download official sanctions XML source files and optionally rebuild the local SQLite index."
    )
    parser.add_argument(
        "--source",
        choices=["all", *SOURCES.keys()],
        default="all",
        help="Source to update. Defaults to all official XML sources.",
    )
    parser.add_argument("--timeout", type=int, default=180, help="Download timeout in seconds per request.")
    parser.add_argument("--retries", type=int, default=3, help="Download retry count per source.")
    parser.add_argument("--skip-build", action="store_true", help="Only refresh XML files; do not rebuild SQLite.")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_PATH, help="SQLite index output path.")
    args = parser.parse_args()

    selected = SOURCES.values() if args.source == "all" else [SOURCES[args.source]]
    records = []
    for source in selected:
        print(f"Updating {source.key} from {source.url}")
        record = download_file(source, timeout=args.timeout, retries=args.retries)
        records.append(record)
        print(f"Updated {record['path']} ({record['bytes']} bytes)")

    if not args.skip_build:
        print(f"Rebuilding local sanctions index: {args.index}")
        build_index(args.index)
        print(f"Built local sanctions index: {args.index}")

    write_manifest(records, rebuilt_index=not args.skip_build)
    print(f"Wrote update manifest: {MANIFEST_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, urllib.error.URLError, ET.ParseError) as exc:
        print(f"Data update failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
