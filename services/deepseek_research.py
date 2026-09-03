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
        "related_hits": (raw_payload or {}).get("related_hits", [])[:5],
        "web_enrichment": web_enrichment,
        "explorer_context": explorer_context,
    }
    return (
        "请基于下面 JSON 上下文回答用户。输出适合聊天窗口阅读，不要输出 JSON。\n"
        "回答必须包含：结论、制裁对象、制裁时间、制裁源、原因、发布/信息来源、证据链接、仍需核查的缺口。\n"
        "不要使用 Markdown 标题、表格、加粗符号、分割线、代码块或 emoji。请使用简短中文段落和普通标签行，例如“制裁对象：...”，不要在每行前加“字段：”。\n"
        "如果是追问，优先回答追问本身，但保留关键证据来源。\n\n"
        + json.dumps(compact_context, ensure_ascii=False, indent=2)
    )


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
        return "DeepSeek 暂时不可用，且当前没有可总结的本地结果。"

    finding = result.get("finding") or {}
    lines = [
        "DeepSeek 暂时不可用，我先基于本地和已抓取网页结果返回简版结论。",
        f"结论：{'本地命中制裁记录' if finding.get('direct_sanction_hit') else '本地未命中明确制裁记录'}。",
        f"制裁对象：{finding.get('sanctioned_entity') or '-'}",
        f"制裁时间：{finding.get('sanction_date') or '-'}",
        f"制裁源：{finding.get('sanction_authority') or '-'}",
        f"原因：{finding.get('sanction_reason') or '-'}",
    ]
    if web_enrichment:
        lines.append(f"联网补充：{web_enrichment.get('summary') or '-'}")
    if explorer_context:
        lines.append(f"浏览器检查：{explorer_context.get('summary') or '-'}")
    return "\n".join(lines)
