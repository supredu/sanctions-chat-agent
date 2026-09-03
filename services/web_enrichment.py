from __future__ import annotations

import html
import json
import os
import re
import socket
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
WEB_TIMEOUT_SECONDS = 8
MAX_PAGE_BYTES = 600_000
ENV_LOADED = False
SANCTION_MARKERS = [
    "sanction",
    "sanctions",
    "ofac",
    "sdn",
    "specially designated nationals",
    "terrorism",
    "executive order",
    "blocked property",
    "uk ofsi",
    "financial sanctions",
    "eu sanctions",
    "un sanctions",
]


@dataclass
class WebSource:
    title: str | None
    url: str
    snippet: str | None = None
    source_type: str = "web"
    publisher: str | None = None


@dataclass
class PageEvidence:
    url: str
    fetched: bool
    title: str | None = None
    description: str | None = None
    matched_markers: list[str] | None = None
    error: str | None = None


class DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[WebSource] = []
        self._in_result_link = False
        self._in_snippet = False
        self._current_url: str | None = None
        self._current_title_parts: list[str] = []
        self._current_snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        classes = attr_map.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._in_result_link = True
            self._current_url = _clean_duckduckgo_url(attr_map.get("href"))
            self._current_title_parts = []
            self._current_snippet_parts = []
        elif "result__snippet" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_result_link:
            self._in_result_link = False
            self._append_current_if_ready()
        elif self._in_snippet and tag in {"a", "div"}:
            self._in_snippet = False
            self._append_current_if_ready()

    def handle_data(self, data: str) -> None:
        if self._in_result_link:
            self._current_title_parts.append(data)
        if self._in_snippet:
            self._current_snippet_parts.append(data)

    def _append_current_if_ready(self) -> None:
        if not self._current_url or not self._current_title_parts:
            return
        if any(source.url == self._current_url for source in self.results):
            return

        self.results.append(
            WebSource(
                title=_clean_text(" ".join(self._current_title_parts)),
                url=self._current_url,
                snippet=_clean_text(" ".join(self._current_snippet_parts)) or None,
                source_type=_source_type_from_url(self._current_url),
                publisher=_publisher_from_url(self._current_url),
            )
        )


def enrich_sanctions_context(
    result: dict[str, Any],
    raw_payload: dict[str, Any] | None = None,
    *,
    max_queries: int = 3,
    results_per_query: int = 4,
) -> dict[str, Any]:
    queries = build_enrichment_queries(result)
    sources: list[WebSource] = build_official_seed_sources(result, raw_payload)
    errors: list[str] = []

    for query in queries[:max_queries]:
        try:
            sources.extend(search_public_web(query, limit=results_per_query))
        except Exception as exc:
            errors.append(f"{query}: {exc}")

    deduped_sources = _dedupe_sources(sources)
    official_sources = [source for source in deduped_sources if source.source_type in {"government", "official_list"}]
    page_evidence = []
    for source in (official_sources or deduped_sources)[:3]:
        page_evidence.append(fetch_page_evidence(source.url))

    return {
        "status": "completed" if deduped_sources else "no_results",
        "queries": queries[:max_queries],
        "sources": [asdict(source) for source in deduped_sources[:8]],
        "page_evidence": [asdict(evidence) for evidence in page_evidence],
        "summary": summarize_web_enrichment(deduped_sources, page_evidence, errors),
        "errors": errors,
    }


def build_official_seed_sources(
    result: dict[str, Any],
    raw_payload: dict[str, Any] | None = None,
) -> list[WebSource]:
    sources: list[WebSource] = []
    finding = result.get("finding") or {}
    sanction_date = finding.get("sanction_date")
    authority = finding.get("sanction_authority") or ""
    entity = finding.get("sanctioned_entity") or result.get("query") or ""

    if "office of foreign assets control" in authority.lower() or authority.upper() == "OFAC":
        if sanction_date and re.match(r"^\d{4}-\d{2}-\d{2}$", sanction_date):
            sources.append(
                WebSource(
                    title=f"OFAC recent actions for {sanction_date}",
                    url=f"https://ofac.treasury.gov/recent-actions/{sanction_date.replace('-', '')}",
                    snippet=f"OFAC recent-action page for the local sanction date linked to {entity}.",
                    source_type="government",
                    publisher="ofac.treasury.gov",
                )
            )

    for hit in (raw_payload or {}).get("hits") or []:
        authority_id = hit.get("authority_id") or (hit.get("metadata") or {}).get("profile_id")
        if authority_id and (hit.get("authority") or "").lower() == "office of foreign assets control":
            sources.append(
                WebSource(
                    title=f"OFAC Sanctions List Search details for {hit.get('name') or hit.get('entity_name') or entity}",
                    url=f"https://sanctionssearch.ofac.treas.gov/Details.aspx?id={authority_id}",
                    snippet="Official OFAC Sanctions List Search details page inferred from the local OFAC profile id.",
                    source_type="official_list",
                    publisher="sanctionssearch.ofac.treas.gov",
                )
            )

        for source_url in hit.get("source_urls") or []:
            sources.append(
                WebSource(
                    title=hit.get("source") or hit.get("list_name") or "Local source URL",
                    url=source_url,
                    snippet="Source URL carried by the local sanctions record.",
                    source_type=_source_type_from_url(source_url),
                    publisher=_publisher_from_url(source_url),
                )
            )

    return _dedupe_sources(sources)


def lookup_explorer_context(result: dict[str, Any]) -> dict[str, Any]:
    profile = result.get("address_profile") or {}
    explorer_url = profile.get("explorer_url")
    if not explorer_url:
        return {
            "status": "not_applicable",
            "url": None,
            "summary": "当前查询没有可用的区块链浏览器 URL。",
            "evidence": None,
        }

    evidence = fetch_page_evidence(explorer_url)
    markers = evidence.matched_markers or []
    if evidence.fetched and markers:
        summary = "区块链浏览器页面可访问，并出现了潜在制裁/风险相关关键词；需要人工复核页面标签和上下文。"
        status = "markers_found"
    elif evidence.fetched:
        summary = "区块链浏览器页面可访问，但页面文本中没有发现明显制裁关键词。"
        status = "fetched"
    else:
        summary = "暂时无法读取区块链浏览器页面；可能是反爬、网络或页面渲染限制。"
        status = "fetch_failed"

    return {
        "status": status,
        "url": explorer_url,
        "summary": summary,
        "evidence": asdict(evidence),
    }


def build_enrichment_queries(result: dict[str, Any]) -> list[str]:
    finding = result.get("finding") or {}
    query = result.get("query")
    entity = finding.get("sanctioned_entity")
    authority = finding.get("sanction_authority")
    sanction_date = finding.get("sanction_date")
    reason = finding.get("sanction_reason")
    program = finding.get("program")

    candidates = [
        _join_terms([entity, authority, sanction_date, "sanctions"]),
        _join_terms([entity, reason, "sanctions"]),
        _join_terms([query, "sanctions", "OFAC", "UK OFSI", "EU", "UN"]),
        _join_terms([query, "blockchain address sanction label"]),
        _join_terms([entity, program, "press release"]),
    ]
    return [candidate for candidate in candidates if candidate]


def search_public_web(query: str, *, limit: int = 5) -> list[WebSource]:
    load_env_once()
    if os.getenv("BRAVE_SEARCH_API_KEY"):
        return search_brave(query, limit=limit)
    if os.getenv("SERPAPI_API_KEY"):
        return search_serpapi(query, limit=limit)
    return search_duckduckgo_html(query, limit=limit)


def search_brave(query: str, *, limit: int = 5) -> list[WebSource]:
    api_key = os.environ["BRAVE_SEARCH_API_KEY"]
    url = f"https://api.search.brave.com/res/v1/web/search?q={quote_plus(query)}&count={limit}"
    body = _fetch_text(url, headers={"Accept": "application/json", "X-Subscription-Token": api_key})
    payload = json.loads(body)
    results = (payload.get("web") or {}).get("results") or []
    return [
        WebSource(
            title=_clean_text(item.get("title")),
            url=item.get("url"),
            snippet=_clean_text(item.get("description")),
            source_type=_source_type_from_url(item.get("url") or ""),
            publisher=_publisher_from_url(item.get("url") or ""),
        )
        for item in results[:limit]
        if item.get("url")
    ]


def search_serpapi(query: str, *, limit: int = 5) -> list[WebSource]:
    api_key = os.environ["SERPAPI_API_KEY"]
    url = f"https://serpapi.com/search.json?engine=google&q={quote_plus(query)}&api_key={quote_plus(api_key)}&num={limit}"
    body = _fetch_text(url)
    payload = json.loads(body)
    results = payload.get("organic_results") or []
    return [
        WebSource(
            title=_clean_text(item.get("title")),
            url=item.get("link"),
            snippet=_clean_text(item.get("snippet")),
            source_type=_source_type_from_url(item.get("link") or ""),
            publisher=_publisher_from_url(item.get("link") or ""),
        )
        for item in results[:limit]
        if item.get("link")
    ]


def search_duckduckgo_html(query: str, *, limit: int = 5) -> list[WebSource]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    body = _fetch_text(url)
    parser = DuckDuckGoHTMLParser()
    parser.feed(body)
    return parser.results[:limit]


def fetch_page_evidence(url: str) -> PageEvidence:
    try:
        body = _fetch_text(url, max_bytes=MAX_PAGE_BYTES)
    except Exception as exc:
        return PageEvidence(url=url, fetched=False, error=str(exc), matched_markers=[])

    visible_text = _clean_text(_strip_tags(body)).lower()
    matched = sorted({marker for marker in SANCTION_MARKERS if marker in visible_text})
    return PageEvidence(
        url=url,
        fetched=True,
        title=_extract_title(body),
        description=_extract_meta_description(body),
        matched_markers=matched,
    )


def summarize_web_enrichment(
    sources: list[WebSource],
    page_evidence: list[PageEvidence],
    errors: list[str],
) -> str:
    if not sources:
        if errors:
            return "联网搜索执行了，但没有拿到可用公开结果；可能是网络、搜索引擎限制或查询词需要调整。"
        return "联网搜索没有发现可用公开结果。"

    official_count = sum(1 for source in sources if source.source_type in {"government", "official_list"})
    fetched_count = sum(1 for evidence in page_evidence if evidence.fetched)
    marker_count = sum(1 for evidence in page_evidence if evidence.matched_markers)
    return (
        f"联网搜索找到 {len(sources)} 条公开结果，其中 {official_count} 条看起来来自官方或制裁相关来源；"
        f"抽样读取了 {fetched_count} 个页面，{marker_count} 个页面出现制裁相关关键词。"
    )


def _fetch_text(url: str, *, max_bytes: int = MAX_PAGE_BYTES, headers: dict[str, str] | None = None) -> str:
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers)
    try:
        with urlopen(request, timeout=WEB_TIMEOUT_SECONDS) as response:
            raw = response.read(max_bytes)
            content_type = response.headers.get_content_charset() or "utf-8"
            return raw.decode(content_type, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except (URLError, TimeoutError, socket.timeout) as exc:
        raise RuntimeError(str(exc)) from exc


def load_env_once() -> None:
    global ENV_LOADED
    if ENV_LOADED:
        return
    ENV_LOADED = True
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _clean_duckduckgo_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("//duckduckgo.com/l/"):
        parsed = urlparse("https:" + url)
        return unquote((parse_qs(parsed.query).get("uddg") or [url])[0])
    if "duckduckgo.com/l/" in url:
        parsed = urlparse(url)
        return unquote((parse_qs(parsed.query).get("uddg") or [url])[0])
    return html.unescape(url)


def _source_type_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if any(domain in host for domain in ["treasury.gov", "state.gov", "gov.uk", "europa.eu", "un.org"]):
        return "government"
    if any(domain in host for domain in ["sanctionssearch.ofac", "ofac.treasury.gov"]):
        return "official_list"
    if any(domain in host for domain in ["etherscan.io", "tronscan.org", "solscan.io", "blockchain.com"]):
        return "blockchain_explorer"
    return "web"


def _publisher_from_url(url: str) -> str | None:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host or None


def _dedupe_sources(sources: list[WebSource]) -> list[WebSource]:
    seen: set[str] = set()
    deduped = []
    for source in sources:
        key = source.url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _extract_title(body: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
    return _clean_text(match.group(1)) if match else None


def _extract_meta_description(body: str) -> str | None:
    match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        match = re.search(
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return _clean_text(match.group(1)) if match else None


def _strip_tags(body: str) -> str:
    body = re.sub(r"<script\b.*?</script>", " ", body, flags=re.IGNORECASE | re.DOTALL)
    body = re.sub(r"<style\b.*?</style>", " ", body, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"<[^>]+>", " ", body)


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _join_terms(values: list[str | None]) -> str:
    return " ".join(value for value in values if value)
