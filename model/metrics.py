"""Concurrency-safe per-question timing and API token accounting."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterator, Mapping


TOKEN_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
    "reasoning_tokens",
)


def _usage_record(usage: Mapping[str, int | None] | None) -> dict[str, int | None]:
    usage = usage or {}
    return {
        field_name: (
            int(usage[field_name])
            if usage.get(field_name) is not None
            else None
        )
        for field_name in TOKEN_FIELDS
    }


@dataclass
class QuestionMetrics:
    """Mutable measurements for one question; serialize after its scope exits."""

    _started_at: float = field(default_factory=perf_counter)
    _finished_at: float | None = None
    _calls: list[dict] = field(default_factory=list)

    def add_api_call(
        self,
        elapsed_seconds: float,
        *,
        usage: Mapping[str, int | None] | None = None,
        error: str | None = None,
    ) -> None:
        call = {
            "elapsed_seconds": round(elapsed_seconds, 6),
            "usage": _usage_record(usage),
        }
        if error is not None:
            call["error"] = error
        self._calls.append(call)

    def finish(self) -> None:
        if self._finished_at is None:
            self._finished_at = perf_counter()

    def to_dict(self) -> dict:
        finished_at = self._finished_at
        if finished_at is None:
            finished_at = perf_counter()

        aggregate: dict[str, int | None] = {}
        for field_name in TOKEN_FIELDS:
            values = [
                call["usage"][field_name]
                for call in self._calls
                if call["usage"][field_name] is not None
            ]
            aggregate[field_name] = sum(values) if values else None

        return {
            "elapsed_seconds": round(finished_at - self._started_at, 6),
            "api_calls": len(self._calls),
            "api_elapsed_seconds": round(
                sum(call["elapsed_seconds"] for call in self._calls), 6
            ),
            "usage": aggregate,
            "calls": list(self._calls),
        }


_CURRENT_METRICS: ContextVar[QuestionMetrics | None] = ContextVar(
    "current_question_metrics",
    default=None,
)


@contextmanager
def question_metrics() -> Iterator[QuestionMetrics]:
    """Bind a fresh collector to the current question execution context."""
    metrics = QuestionMetrics()
    token = _CURRENT_METRICS.set(metrics)
    try:
        yield metrics
    finally:
        metrics.finish()
        _CURRENT_METRICS.reset(token)


def record_api_call(
    elapsed_seconds: float,
    *,
    usage: Mapping[str, int | None] | None = None,
    error: str | None = None,
) -> None:
    """Record against the active question, or no-op for standalone chat calls."""
    metrics = _CURRENT_METRICS.get()
    if metrics is not None:
        metrics.add_api_call(elapsed_seconds, usage=usage, error=error)

