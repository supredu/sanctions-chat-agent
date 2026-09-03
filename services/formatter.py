from models import SanctionResult


def format_result(result: SanctionResult) -> str:
    finding = result.finding
    profile = result.address_profile
    evidence_lines = []

    for item in result.evidence:
        title = item.source_title or "Untitled source"
        url = item.source_url or "No URL"
        evidence_lines.append(f"- {title}: {url}")

    evidence_text = "\n".join(evidence_lines) if evidence_lines else "- No evidence captured"
    related_lines = [
        f"- {item.related_address}: {item.description}"
        for item in result.related_hits
    ]
    related_text = "\n".join(related_lines) if related_lines else "- No related sanctions hits captured"

    return (
        f"Query: {result.query or profile.address}\n"
        f"Query type: {result.query_type}\n"
        f"Address: {profile.address}\n"
        f"Chain: {profile.chain or 'unknown'}\n"
        f"Sanctioned: {finding.sanctioned}\n"
        f"Direct hit: {finding.direct_sanction_hit}\n"
        f"Related hit: {finding.related_sanction_hit}\n"
        f"Authority: {finding.sanction_authority or 'unknown'}\n"
        f"Entity: {finding.sanctioned_entity or 'unknown'}\n"
        f"Sanction date: {finding.sanction_date or 'unknown'}\n"
        f"Reason: {finding.sanction_reason or 'unknown'}\n"
        f"Confidence: {result.confidence}\n"
        f"Summary: {result.summary}\n"
        f"Evidence:\n{evidence_text}\n"
        f"Related hits:\n{related_text}"
    )
