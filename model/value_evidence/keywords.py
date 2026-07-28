"""Offline CHESS keyword extraction with resumable DeepSeek calls."""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping

from archer_eval.data import Sample
from model.fewshot.store import sample_key
from model.llm import ChatEndpoint
from model.metrics import TOKEN_FIELDS, question_metrics


KEYWORD_FORMAT_VERSION = 1
KEYWORD_STRATEGY = "chess-keywords-deepseek-v1"
KEYWORD_MODEL = "deepseek-v4-flash"
_PROMPT_PATH = Path(__file__).parent / "prompts" / "extract_keywords.md"
_FENCE = re.compile(r"```(?:python|json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def render_keyword_prompt(question: str, evidence: str | None = None) -> str:
    """Render the versioned CHESS-style question + hint prompt."""
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace("{QUESTION}", question).replace(
        "{HINT}", evidence or ""
    )


def parse_keywords(reply: str) -> list[str]:
    """Accept the JSON/Python list shapes commonly returned by chat models."""
    text = reply.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    parsed: Any
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError) as exc:
            raise ValueError("keyword output must be a list of strings") from exc
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("keyword output must be a non-empty list of strings")
    if any(not isinstance(item, str) or not item.strip() for item in parsed):
        raise ValueError("keyword output must contain only non-empty strings")
    output: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        keyword = item.strip()
        if keyword not in seen:
            output.append(keyword)
            seen.add(keyword)
    return output


def sample_evidence(sample: Sample) -> str:
    """Return the official evidence/hint without inventing new information."""
    for key in ("evidence", "hint"):
        value = sample.extras.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return (sample.commonsense_knowledge or "").strip()


class DeepSeekKeywordExtractor:
    """Callable extractor using the user's only available API provider."""

    def __init__(self) -> None:
        self.endpoint = ChatEndpoint(
            base_url="https://api.deepseek.com/v1",
            model=KEYWORD_MODEL,
            key_env="DEEPSEEK_API_KEY",
            request_params={
                "temperature": 0.0,
                "max_tokens": 256,
                "extra_body": {"thinking": {"type": "disabled"}},
            },
        )

    def __call__(self, sample: Sample) -> dict[str, Any]:
        with question_metrics() as metrics:
            reply = self.endpoint.chat_messages(
                [
                    {
                        "role": "user",
                        "content": render_keyword_prompt(
                            sample.question, sample_evidence(sample)
                        ),
                    }
                ]
            )
        return {"keywords": parse_keywords(reply), "usage": metrics.to_dict()["usage"]}


def build_keyword_artifact(
    samples: Iterable[Sample],
    *,
    output_path: str | Path,
    dataset: str,
    dataset_sha256: str,
    extractor: Callable[[Sample], Mapping[str, Any]],
    chunk: int = 50,
    concurrency: int = 10,
) -> dict[str, Any]:
    """Extract all keywords, checkpoint successes, and resume exact failures."""
    sample_list = list(samples)
    if chunk <= 0 or concurrency <= 0:
        raise ValueError("chunk and concurrency must be positive")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(".partial.jsonl")
    stamp = _artifact_stamp(dataset, dataset_sha256)
    records = _load_partial(partial, stamp)
    failures: list[tuple[str, Exception]] = []

    pending = []
    pending_keys: set[str] = set()
    for sample in sample_list:
        key = sample_key(sample.db_id, sample.question)
        if key not in records and key not in pending_keys:
            pending.append(sample)
            pending_keys.add(key)
    for offset in range(0, len(pending), chunk):
        batch = pending[offset : offset + chunk]

        def one(sample: Sample) -> tuple[str, dict[str, Any] | None, Exception | None]:
            target_key = sample_key(sample.db_id, sample.question)
            try:
                raw = extractor(sample)
                keywords = _validate_extractor_result(raw)
                record = {
                    "target_key": target_key,
                    "db_id": sample.db_id,
                    "question": sample.question,
                    "evidence": sample_evidence(sample),
                    "keywords": keywords,
                    "usage": _normalise_usage(raw.get("usage")),
                }
                return target_key, record, None
            except Exception as exc:
                return target_key, None, exc

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for target_key, record, error in pool.map(one, batch):
                if error is not None:
                    failures.append((target_key, error))
                else:
                    records[target_key] = record
        _write_partial(partial, stamp, records)

    if failures:
        details = "; ".join(
            f"{key[:8]}: {type(error).__name__}: {error}"
            for key, error in failures[:5]
        )
        raise RuntimeError(
            f"{len(failures)} keyword extraction failure(s); rerun to resume. {details}"
        )

    ordered_records = []
    ordered_keys: set[str] = set()
    for sample in sample_list:
        key = sample_key(sample.db_id, sample.question)
        if key in ordered_keys:
            continue
        if key not in records:
            raise RuntimeError(f"keyword artifact is missing target {key}")
        ordered_records.append(records[key])
        ordered_keys.add(key)
    payload = {
        **stamp,
        "usage": _sum_usage(record["usage"] for record in ordered_records),
        "records": ordered_records,
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    partial.unlink(missing_ok=True)
    return payload


def _artifact_stamp(dataset: str, dataset_sha256: str) -> dict[str, Any]:
    prompt_bytes = _PROMPT_PATH.read_bytes()
    return {
        "format_version": KEYWORD_FORMAT_VERSION,
        "strategy": KEYWORD_STRATEGY,
        "dataset": dataset,
        "dataset_sha256": dataset_sha256,
        "model": KEYWORD_MODEL,
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "request_params": {
            "temperature": 0.0,
            "max_tokens": 256,
            "thinking": "disabled",
        },
    }


def _validate_extractor_result(raw: Mapping[str, Any]) -> list[str]:
    if not isinstance(raw, Mapping):
        raise ValueError("keyword extractor result must be an object")
    keywords = raw.get("keywords")
    if not isinstance(keywords, list):
        raise ValueError("keyword extractor result requires a keywords list")
    return parse_keywords(json.dumps(keywords, ensure_ascii=False))


def _normalise_usage(value: Any) -> dict[str, int | None]:
    usage = value if isinstance(value, Mapping) else {}
    return {
        field: int(usage[field]) if usage.get(field) is not None else None
        for field in TOKEN_FIELDS
    }


def _sum_usage(values: Iterable[Mapping[str, int | None]]) -> dict[str, int | None]:
    records = list(values)
    return {
        field: (
            sum(value[field] for value in records if value.get(field) is not None)
            if any(value.get(field) is not None for value in records)
            else None
        )
        for field in TOKEN_FIELDS
    }


def _load_partial(path: Path, stamp: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return {}
    try:
        header = json.loads(lines[0])
    except json.JSONDecodeError:
        return {}
    if header != dict(stamp):
        return {}
    records: dict[str, dict[str, Any]] = {}
    for line in lines[1:]:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and isinstance(record.get("target_key"), str):
            records[record["target_key"]] = record
    return records


def _write_partial(
    path: Path,
    stamp: Mapping[str, Any],
    records: Mapping[str, Mapping[str, Any]],
) -> None:
    lines = [json.dumps(dict(stamp), ensure_ascii=False, separators=(",", ":"))]
    lines.extend(
        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        for _, record in sorted(records.items())
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
