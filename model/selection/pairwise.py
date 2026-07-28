"""One-call output-contract judge for unresolved SQL candidate pairs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from model.selection.router import ExecutionSummary

_PROMPT_PATH = Path(__file__).parent / "prompts" / "pairwise.md"
_CHOICES = {"A", "B"}
_CONFIDENCE = {"high", "medium", "low"}


@dataclass(frozen=True)
class PairwiseDecision:
    winner: str
    confidence: str
    violations_a: tuple[str, ...]
    violations_b: tuple[str, ...]
    reason: str
    raw_reply: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def parse_pairwise_reply(reply: str) -> PairwiseDecision:
    text = reply.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"selector did not return strict JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("selector response must be a JSON object")

    winner = data.get("winner")
    confidence = data.get("confidence")
    if winner not in _CHOICES:
        raise ValueError("selector winner must be A or B")
    if confidence not in _CONFIDENCE:
        raise ValueError("selector confidence must be high, medium, or low")

    violations = {}
    for key in ("violations_a", "violations_b"):
        value = data.get(key)
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise ValueError(f"selector {key} must be a list of strings")
        violations[key] = tuple(value)
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("selector reason must be a non-empty string")

    return PairwiseDecision(
        winner=winner,
        confidence=confidence,
        violations_a=violations["violations_a"],
        violations_b=violations["violations_b"],
        reason=reason.strip(),
        raw_reply=reply,
    )


def candidate_mapping(sample_index: int) -> dict[str, str]:
    """Alternate source order deterministically to avoid a fixed A/B bias."""
    if sample_index % 2 == 0:
        return {"A": "direct", "B": "dsl"}
    return {"A": "dsl", "B": "direct"}


def resolve_pairwise_winner(
    winner: str,
    confidence: str,
    mapping: dict[str, str],
) -> str:
    if confidence == "low":
        return "dsl"
    return mapping[winner]


def _summary_text(summary: ExecutionSummary) -> str:
    return json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True)


def render_pairwise_prompt(
    *,
    question: str,
    evidence: str,
    schema: str,
    candidate_a: str,
    candidate_b: str,
    summary_a: ExecutionSummary,
    summary_b: ExecutionSummary,
) -> str:
    text = _PROMPT_PATH.read_text(encoding="utf-8")
    values = {
        "schema": schema,
        "question": question,
        "evidence": evidence.strip() or "(none)",
        "candidate_a": candidate_a,
        "candidate_b": candidate_b,
        "summary_a": _summary_text(summary_a),
        "summary_b": _summary_text(summary_b),
    }
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def judge_pairwise(
    endpoint,
    *,
    sample_index: int,
    question: str,
    evidence: str,
    schema: str,
    direct_sql: str,
    dsl_sql: str,
    direct_summary: ExecutionSummary,
    dsl_summary: ExecutionSummary,
) -> tuple[PairwiseDecision, dict[str, str]]:
    mapping = candidate_mapping(sample_index)
    sql_by_source = {"direct": direct_sql, "dsl": dsl_sql}
    summary_by_source = {"direct": direct_summary, "dsl": dsl_summary}
    prompt = render_pairwise_prompt(
        question=question,
        evidence=evidence,
        schema=schema,
        candidate_a=sql_by_source[mapping["A"]],
        candidate_b=sql_by_source[mapping["B"]],
        summary_a=summary_by_source[mapping["A"]],
        summary_b=summary_by_source[mapping["B"]],
    )
    reply = endpoint.chat_messages([{"role": "user", "content": prompt}])
    return parse_pairwise_reply(reply), mapping
