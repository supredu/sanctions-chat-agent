import json
import re

from pydantic import ValidationError

from agents import Agent, Runner

from config import build_model, build_run_config
from models import SanctionResult
from tools import (
    build_sanctions_search_queries,
    list_priority_sanctions_sources,
)
from services.query_router import route_and_query_local_sources


SANCTION_AGENT_INSTRUCTIONS = """
You are a sanctions intelligence agent focused on blockchain addresses and sanctioned entities.

Given a user-provided blockchain address or sanctioned entity name:
1. Classify the address and infer the likely chain.
   If the input is not a blockchain address, fuzzy-search local entity names.
2. Build targeted sanctions search queries.
3. Identify which primary sanctions sources should be checked.
4. Use route_and_query_local_sources before making a sanctions determination.
5. Return only valid JSON matching this schema:
{
  "address_profile": {
    "address": "string",
    "chain": "string or null",
    "address_type": "string or null",
    "explorer_url": "string or null"
  },
  "finding": {
    "sanctioned": false,
    "sanction_authority": "string or null",
    "sanctioned_entity": "string or null",
    "sanction_date": "string or null",
    "sanction_reason": "string or null",
    "list_name": "string or null",
    "program": "string or null"
  },
  "evidence": [],
  "confidence": "high | medium | low | unknown",
  "summary": "string",
  "gaps": ["string"]
}

For the current MVP, you do not have a live web search connector yet. Be explicit
about that gap. Do not claim an address is sanctioned unless a provided source
or tool result supports it. Prefer "unknown" confidence when evidence is missing.
Do not claim that OFAC, UK OFSI, EU, UN, or analytics sources were checked unless
a tool returned live search or official list data.
Return JSON only. Do not include Markdown fences, bullet points, or explanation
outside the JSON object.
"""


def extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced_match:
        return fenced_match.group(1)

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = stripped[start : end + 1]
        json.loads(candidate)
        return candidate

    raise ValueError("No JSON object found in agent output.")


def build_sanction_agent() -> Agent:
    return Agent(
        name="Blockchain Sanctions Intelligence Agent",
        instructions=SANCTION_AGENT_INSTRUCTIONS,
        model=build_model(),
        tools=[
            route_and_query_local_sources,
            build_sanctions_search_queries,
            list_priority_sanctions_sources,
        ],
    )


def run_sanction_lookup(query: str) -> SanctionResult:
    agent = build_sanction_agent()
    result = Runner.run_sync(
        agent,
        f"Investigate this blockchain address or entity for sanctions exposure: {query}",
        run_config=build_run_config(),
    )

    final_output = result.final_output_as(str)
    try:
        return SanctionResult.model_validate_json(extract_json_object(final_output))
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Agent returned invalid SanctionResult JSON: {final_output}") from exc
