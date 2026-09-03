from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from services.deepseek_research import generate_deepseek_research_answer
from services.query_router import infer_query_type, lookup_local_query
from services.result_builder import build_sanction_result_from_local_payload
from services.web_enrichment import enrich_sanctions_context, lookup_explorer_context


@dataclass
class ChatSession:
    session_id: str
    pending_candidates: list[dict[str, Any]] = field(default_factory=list)
    last_query: str | None = None
    last_payload: dict[str, Any] | None = None
    last_result: dict[str, Any] | None = None
    last_web_enrichment: dict[str, Any] | None = None
    last_explorer_context: dict[str, Any] | None = None
    last_llm_research: dict[str, Any] | None = None


class SanctionsChatOrchestrator:
    def __init__(self) -> None:
        self.sessions: dict[str, ChatSession] = {}

    def handle_message(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        cleaned_message = message.strip()
        session = self._get_session(session_id)

        if not cleaned_message:
            return self._response(
                session,
                "请输入一个区块链地址、实体名称，或者对上一条结果的追问。",
                kind="clarification",
            )

        selected_candidate = self._candidate_from_selection(cleaned_message, session)
        if selected_candidate:
            return self._handle_selected_entity(session, selected_candidate)
        if session.pending_candidates and self._is_candidate_rejection(cleaned_message):
            return self._handle_rejected_candidates(session, cleaned_message)

        query_type = infer_query_type(cleaned_message)
        if query_type == "address":
            return self._handle_address_query(session, cleaned_message)

        if session.last_result and self._looks_like_follow_up(cleaned_message):
            return self._handle_follow_up(session, cleaned_message)

        return self._handle_entity_query(session, cleaned_message)

    def _get_session(self, session_id: str | None) -> ChatSession:
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]

        new_session = ChatSession(session_id=session_id or uuid4().hex)
        self.sessions[new_session.session_id] = new_session
        return new_session

    def _handle_address_query(self, session: ChatSession, query: str) -> dict[str, Any]:
        payload = lookup_local_query(query)
        result = build_sanction_result_from_local_payload(payload).model_dump()
        session.pending_candidates = []
        session.last_query = query
        session.last_payload = payload
        session.last_result = result

        finding = result["finding"]
        if finding["direct_sanction_hit"]:
            web_enrichment = enrich_sanctions_context(result, payload)
            explorer_context = lookup_explorer_context(result)
            session.last_web_enrichment = web_enrichment
            session.last_explorer_context = explorer_context
            llm_research = generate_deepseek_research_answer(
                user_message=query,
                result=result,
                raw_payload=payload,
                web_enrichment=web_enrichment,
                explorer_context=explorer_context,
            )
            session.last_llm_research = llm_research
            return self._response(
                session,
                llm_research["answer"],
                kind="address_direct_hit",
                result=result,
                raw=payload,
                web_enrichment=web_enrichment,
                explorer_context=explorer_context,
                llm_research=llm_research,
            )

        web_enrichment = enrich_sanctions_context(result, payload)
        explorer_context = lookup_explorer_context(result)
        session.last_web_enrichment = web_enrichment
        session.last_explorer_context = explorer_context
        llm_research = generate_deepseek_research_answer(
            user_message=query,
            result=result,
            raw_payload=payload,
            web_enrichment=web_enrichment,
            explorer_context=explorer_context,
        )
        session.last_llm_research = llm_research
        return self._response(
            session,
            llm_research["answer"],
            kind="address_no_local_hit",
            result=result,
            raw=payload,
            web_enrichment=web_enrichment,
            explorer_context=explorer_context,
            llm_research=llm_research,
        )

    def _handle_entity_query(self, session: ChatSession, query: str) -> dict[str, Any]:
        payload = lookup_local_query(query)
        hits = payload.get("hits") or []
        session.last_query = query
        session.last_payload = payload

        if not hits:
            session.pending_candidates = []
            answer = (
                "本地制裁库没有找到明确匹配的实体。"
                "后续联网模块会用这个名称去查官方制裁公告、新闻和公开数据库；当前 MVP 先如实返回未命中。"
            )
            result = build_sanction_result_from_local_payload(payload).model_dump()
            session.last_result = result
            web_enrichment = enrich_sanctions_context(result, payload)
            session.last_web_enrichment = web_enrichment
            llm_research = generate_deepseek_research_answer(
                user_message=query,
                result=result,
                raw_payload=payload,
                web_enrichment=web_enrichment,
            )
            session.last_llm_research = llm_research
            return self._response(
                session,
                llm_research["answer"],
                kind="entity_no_local_hit",
                result=result,
                raw=payload,
                web_enrichment=web_enrichment,
                llm_research=llm_research,
            )

        session.pending_candidates = hits[:5]
        candidate_lines = []
        for index, hit in enumerate(session.pending_candidates, start=1):
            candidate_lines.append(
                f"{index}. {hit.get('name') or hit.get('entity_name') or 'Unknown entity'}"
                f" | {hit.get('authority') or 'Unknown authority'}"
                f" | {self._first(hit.get('sanction_dates')) or 'No official date'}"
            )

        answer = (
            "我在本地库里找到了多个可能匹配的实体。请回复编号选择你要深入查看的一条，"
            "比如回复 1；如果都不是你要找的对象，请回复“以上没有命中”。\n\n" + "\n".join(candidate_lines)
        )
        return self._response(session, answer, kind="entity_candidates", candidates=session.pending_candidates)

    def _handle_rejected_candidates(self, session: ChatSession, message: str) -> dict[str, Any]:
        query = session.last_query or message
        payload = {
            "query": query,
            "query_type": "entity",
            "address_profile": None,
            "hit_count": 0,
            "hits": [],
            "related_hit_count": 0,
            "related_hits": [],
        }
        result = build_sanction_result_from_local_payload(payload).model_dump()
        session.pending_candidates = []
        session.last_payload = payload
        session.last_result = result
        web_enrichment = enrich_sanctions_context(result, payload)
        session.last_web_enrichment = web_enrichment
        llm_research = generate_deepseek_research_answer(
            user_message=f"用户表示本地候选都不对，请联网核查实体名称：{query}",
            result=result,
            raw_payload=payload,
            web_enrichment=web_enrichment,
        )
        session.last_llm_research = llm_research
        return self._response(
            session,
            llm_research["answer"],
            kind="entity_candidates_rejected",
            result=result,
            raw=payload,
            web_enrichment=web_enrichment,
            llm_research=llm_research,
        )

    def _handle_selected_entity(self, session: ChatSession, hit: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "query": hit.get("name") or hit.get("entity_name") or session.last_query or "",
            "query_type": "entity",
            "address_profile": None,
            "hit_count": 1,
            "hits": [hit],
            "related_hit_count": 0,
            "related_hits": [],
        }
        result = build_sanction_result_from_local_payload(payload).model_dump()
        session.pending_candidates = []
        session.last_payload = payload
        session.last_result = result
        web_enrichment = enrich_sanctions_context(result, payload)
        session.last_web_enrichment = web_enrichment
        llm_research = generate_deepseek_research_answer(
            user_message=f"用户选择了实体：{payload['query']}",
            result=result,
            raw_payload=payload,
            web_enrichment=web_enrichment,
        )
        session.last_llm_research = llm_research
        return self._response(
            session,
            llm_research["answer"],
            kind="entity_selected",
            result=result,
            raw=payload,
            web_enrichment=web_enrichment,
            llm_research=llm_research,
        )

    def _handle_follow_up(self, session: ChatSession, message: str) -> dict[str, Any]:
        result = session.last_result
        if not result:
            return self._response(session, "我还没有上一条查询上下文。请先输入一个地址或实体名称。", kind="clarification")

        web_enrichment = enrich_sanctions_context(result, session.last_payload)
        session.last_web_enrichment = web_enrichment
        llm_research = generate_deepseek_research_answer(
            user_message=message,
            result=result,
            raw_payload=session.last_payload,
            web_enrichment=web_enrichment,
            explorer_context=session.last_explorer_context,
        )
        session.last_llm_research = llm_research
        return self._response(
            session,
            llm_research["answer"],
            kind="follow_up_reserved",
            result=result,
            raw=session.last_payload,
            web_enrichment=web_enrichment,
            explorer_context=session.last_explorer_context,
            llm_research=llm_research,
        )

    def _candidate_from_selection(self, message: str, session: ChatSession) -> dict[str, Any] | None:
        if not session.pending_candidates:
            return None
        if not message.isdigit():
            return None
        index = int(message)
        if index < 1 or index > len(session.pending_candidates):
            return None
        return session.pending_candidates[index - 1]

    def _looks_like_follow_up(self, message: str) -> bool:
        lowered = message.lower()
        markers = [
            "why",
            "how",
            "what",
            "source",
            "reason",
            "detail",
            "tell me",
            "为什么",
            "原因",
            "来源",
            "详细",
            "解释",
            "这个",
            "它",
            "该",
            "和",
            "关系",
        ]
        return any(marker in lowered for marker in markers)

    def _is_candidate_rejection(self, message: str) -> bool:
        lowered = message.lower()
        markers = ["以上没有命中", "都不对", "都不是", "不是", "none", "no", "not these", "wrong"]
        return any(marker in lowered for marker in markers)

    def _response(
        self,
        session: ChatSession,
        answer: str,
        *,
        kind: str,
        result: dict[str, Any] | None = None,
        raw: dict[str, Any] | None = None,
        candidates: list[dict[str, Any]] | None = None,
        actions: list[dict[str, Any]] | None = None,
        web_enrichment: dict[str, Any] | None = None,
        explorer_context: dict[str, Any] | None = None,
        llm_research: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "kind": kind,
            "answer": answer,
            "result": result,
            "raw": raw,
            "candidates": candidates or [],
            "next_actions": actions or [],
            "web_enrichment": web_enrichment,
            "explorer_context": explorer_context,
            "llm_research": llm_research,
        }

    def _web_research_action(self, result: dict[str, Any]) -> dict[str, Any]:
        finding = result.get("finding") or {}
        search_terms = [
            finding.get("sanctioned_entity"),
            finding.get("sanction_authority"),
            finding.get("sanction_date"),
            finding.get("program"),
            result.get("query"),
        ]
        query = " ".join(term for term in search_terms if term)
        return {
            "type": "web_research",
            "status": "reserved",
            "description": "联网补充官方公告、公开新闻、制裁原因和发布源描述。",
            "suggested_query": query,
        }

    def _explorer_lookup_action(self, result: dict[str, Any]) -> dict[str, Any]:
        profile = result.get("address_profile") or {}
        return {
            "type": "explorer_lookup",
            "status": "reserved",
            "description": "查询对应区块链浏览器的基础信息、公开标签和潜在制裁标签。",
            "explorer_url": profile.get("explorer_url"),
        }

    def _first(self, values: list[str] | None) -> str | None:
        return values[0] if values else None
