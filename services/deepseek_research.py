from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import get_config


DEEPSEEK_TIMEOUT_SECONDS = 60


def generate_deepseek_research_answer(
    *,
    user_message: str,
    result: dict[str, Any] | None,
    raw_payload: dict[str, Any] | None = None,
    web_enrichment: dict[str, Any] | None = None,
    explorer_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return _call_deepseek_responses(
            user_message=user_message,
            result=result,
            raw_payload=raw_payload,
            web_enrichment=web_enrichment,
            explorer_context=explorer_context,
        )
    except Exception as exc:
        return {
            "status": "fallback",
            "provider": "deepseek",
            "answer": _fallback_answer(result, web_enrichment, explorer_context),
            "error": str(exc),
            "web_search_calls": [],
            "usage": None,
        }


def _call_deepseek_responses(
    *,
    user_message: str,
    result: dict[str, Any] | None,
    raw_payload: dict[str, Any] | None,
    web_enrichment: dict[str, Any] | None,
    explorer_context: dict[str, Any] | None,
) -> dict[str, Any]:
    config = get_config()
    endpoint = config.deepseek_base_url.rstrip("/") + "/responses"
    prompt = _build_research_prompt(
        user_message=user_message,
        result=result,
        raw_payload=raw_payload,
        web_enrichment=web_enrichment,
        explorer_context=explorer_context,
    )
    payload = {
        "model": config.deepseek_model,
        "instructions": (
            "You are a sanctions intelligence analyst. Answer in Chinese. "
            "Use local sanctions data as the primary evidence for exact matches. "
            "Use web search to supplement sanction source, publication source, reason, and context. "
            "Never claim a sanctions hit unless local evidence or cited public sources support it. "
            "When evidence is missing or unclear, say so plainly. "
            "Do not use Markdown headings, Markdown tables, bold markers, horizontal rules, code fences, or emoji. "
            "Use short plain-text paragraphs and concise label-value lines."
        ),
        "input": prompt,
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "max_output_tokens": 1400,
        "text": {"format": {"type": "text"}},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.deepseek_api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=DEEPSEEK_TIMEOUT_SECONDS) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek HTTP {exc.code}: {error_body}") from exc
    except URLError as exc:
        raise RuntimeError(f"DeepSeek request failed: {exc}") from exc

    return {
        "status": "completed",
        "provider": "deepseek",
        "answer": _extract_output_text(response_payload),
        "web_search_calls": _extract_web_search_calls(response_payload),
        "usage": response_payload.get("usage"),
    }


def _build_research_prompt(
    *,
    user_message: str,
    result: dict[str, Any] | None,
    raw_payload: dict[str, Any] | None,
    web_enrichment: dict[str, Any] | None,
    explorer_context: dict[str, Any] | None,
) -> str:
    compact_context = {
        "user_message": user_message,
        "standard_result": result,
        "local_hits": (raw_payload or {}).get("hits", [])[:3],
        "related_hits": (raw_payload or {}).get("related_hits", [])[:10],
        "neighbor_lookup": _public_neighbor_lookup(raw_payload),
        "web_enrichment": _public_web_enrichment(web_enrichment),
        "explorer_context": _public_explorer_context(explorer_context),
    }
    return (
        "请基于下面 JSON 上下文回答用户。输出适合聊天窗口阅读，不要输出 JSON。\n"
        "回答必须包含：结论、制裁对象、制裁时间、制裁源、原因、发布/信息来源、证据链接、仍需核查的缺口。\n"
        "如果 related_hits 不为空，必须明确说明这是“一跳相关制裁命中”，不是输入地址直接被制裁；列出每一个命中的唯一制裁地址。\n"
        "如果 related_hits 不为空，不要把内部 partial_error、抓取失败、HTTP 403、urlopen timeout、Session not found 等工程日志写进用户答案。\n"
        "如果 neighbor_lookup 的 status 是 related_hit，说明一跳相关制裁已经命中；不要再说一跳查询失败或状态异常。\n"
        "如果 related_hits 为空且 neighbor_lookup 的 status 是 error 或 partial_error，只需用产品化语言说明“一跳查询暂未完整完成”，不要输出原始报错。\n"
        "不要向用户展示底层错误日志、栈信息、HTTP 状态码、抓取失败细节或调试字段。\n"
        "不要使用 Markdown 标题、表格、加粗符号、分割线、代码块或 emoji。请使用简短中文段落和普通标签行，例如“制裁对象：...”，不要在每行前加“字段：”。\n"
        "如果是追问，优先回答追问本身，但保留关键证据来源。\n\n"
        + json.dumps(compact_context, ensure_ascii=False, indent=2)
    )


def _public_neighbor_lookup(raw_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    neighbor_lookup = (raw_payload or {}).get("neighbor_lookup")
    if not isinstance(neighbor_lookup, dict):
        return None

    public = {
        "status": neighbor_lookup.get("status"),
        "chain": neighbor_lookup.get("chain"),
        "sampled_transaction_count": neighbor_lookup.get("sampled_transaction_count"),
        "unique_counterparty_count": neighbor_lookup.get("unique_counterparty_count"),
        "truncated": neighbor_lookup.get("truncated"),
        "matched_sanctioned_address_count": neighbor_lookup.get("matched_sanctioned_address_count"),
    }
    if public["status"] in {"error", "partial_error"}:
        public["message"] = "一跳查询暂未完整完成。"
    return public


def _public_web_enrichment(web_enrichment: dict[str, Any] | None) -> dict[str, Any] | None:
    if not web_enrichment:
        return None
    return {
        "status": web_enrichment.get("status"),
        "sources": (web_enrichment.get("sources") or [])[:5],
        "page_evidence": [
            {
                "url": item.get("url"),
                "title": item.get("title"),
                "description": item.get("description"),
                "matched_markers": item.get("matched_markers"),
            }
            for item in (web_enrichment.get("page_evidence") or [])[:3]
            if item.get("fetched")
        ],
    }


def _public_explorer_context(explorer_context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not explorer_context or explorer_context.get("status") != "ok":
        return None
    evidence = explorer_context.get("evidence") or {}
    return {
        "status": explorer_context.get("status"),
        "url": explorer_context.get("url"),
        "matched_markers": evidence.get("matched_markers"),
    }


def _extract_output_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in payload.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts).strip() or "DeepSeek 没有返回可读文本。"


def _extract_web_search_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    calls = []
    for item in payload.get("output") or []:
        if item.get("type") == "web_search_call":
            calls.append(
                {
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "action": item.get("action"),
                }
            )
    return calls


def _fallback_answer(
    result: dict[str, Any] | None,
    web_enrichment: dict[str, Any] | None,
    explorer_context: dict[str, Any] | None,
) -> str:
    if not result:
        return "当前没有可总结的查询结果，请稍后重试。"

    finding = result.get("finding") or {}
    related_hits = result.get("related_hits") or []
    if finding.get("direct_sanction_hit"):
        conclusion = "本地制裁库直接命中该地址。"
    elif related_hits:
        conclusion = "本地制裁库未直接命中该地址，但发现一跳相关制裁命中。"
    else:
        conclusion = "本地制裁库未直接命中该地址。"

    lines = [f"结论：{conclusion}"]
    if finding.get("direct_sanction_hit"):
        lines.extend(
            [
                f"制裁对象：{finding.get('sanctioned_entity') or '-'}",
                f"制裁时间：{finding.get('sanction_date') or '-'}",
                f"制裁源：{finding.get('sanction_authority') or '-'}",
                f"原因：{finding.get('sanction_reason') or '-'}",
            ]
        )
    if related_hits:
        lines.append("一跳相关制裁地址：")
        seen_addresses = set()
        for hit in related_hits:
            address = hit.get("related_address")
            if not address or address.lower() in seen_addresses:
                continue
            seen_addresses.add(address.lower())
            lines.append(
                f"{address}，方向：{hit.get('direction') or '-'}，"
                f"制裁对象：{hit.get('sanctioned_entity') or '-'}，"
                f"制裁源：{hit.get('sanction_authority') or '-'}，"
                f"制裁时间：{hit.get('sanction_date') or '-'}。"
            )
    if not finding.get("direct_sanction_hit") and not related_hits:
        lines.append("仍需核查的缺口：未发现本地直接命中或一跳相关命中，建议结合官方名单和链上数据源继续核查。")
    return "\n".join(lines)
