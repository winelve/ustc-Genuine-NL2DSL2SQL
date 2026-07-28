"""Run the official DPC pipeline on a fixed, conservative BIRD pilot."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
from time import perf_counter
from typing import Any, Mapping

import sqlglot
from sqlglot import exp

import config
from archer_eval.data import load_dataset, load_predictions, resolve_dataset
from archer_eval.evaluate import find_db_file
from archer_eval.progress import Progress
from model.dpc_pilot.prepare import merge_dpc_results
from model.dpc_pilot.safe_executor import SafePythonExecutor
from model.llm import _response_usage
from model.metrics import TOKEN_FIELDS, question_metrics, record_api_call


OFFICIAL_DPC_URL = "https://github.com/HKUSTDial/DPC.git"
OFFICIAL_DPC_COMMIT = "f75c759e58cc5b2b2a0d9b5227e38536e9a248ad"
DEFAULT_OFFICIAL_ROOT = config.DATA_DIR / "dpc" / "official"
RUN_FORMAT = "bird-dpc-run-v2"
_SOLVER_SYSTEM_MARKER = "Python data scientist expert in Pandas"
_SOLVER_EXECUTION_CONTRACT = """

Execution restrictions:
- Pandas is already available as `pd`, and all listed DataFrames are already
  in the namespace. Do not import modules.
- Write straight-line Pandas code when possible; small pure helper functions are allowed.
- Do not access files, the network, processes, environment variables, or
  private/dunder attributes.
""".strip()


def bootstrap_official_dpc(root: str | Path = DEFAULT_OFFICIAL_ROOT) -> Path:
    """Clone the official source once and pin it to the reviewed commit."""
    destination = Path(root).resolve()
    if destination.exists():
        if not (destination / ".git").is_dir():
            raise ValueError(
                f"official DPC destination exists but is not a git checkout: "
                f"{destination}"
            )
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                OFFICIAL_DPC_URL,
                str(destination),
            ],
            check=True,
        )
    subprocess.run(
        [
            "git",
            "-C",
            str(destination),
            "checkout",
            "--detach",
            OFFICIAL_DPC_COMMIT,
        ],
        check=True,
    )
    actual = subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual != OFFICIAL_DPC_COMMIT:
        raise RuntimeError(
            f"official DPC commit mismatch: expected {OFFICIAL_DPC_COMMIT}, "
            f"got {actual}"
        )
    return destination


def _require_official_dpc(
    root: str | Path = DEFAULT_OFFICIAL_ROOT,
) -> None:
    root = Path(root).resolve()
    if not (root / "dpc" / "core" / "pipeline.py").is_file():
        raise RuntimeError(
            "official DPC checkout is missing; run "
            r".\.venv\Scripts\python.exe -m model.dpc_pilot bootstrap"
        )
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        import dpc  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "official DPC dependencies are missing; run "
            r".\.venv\Scripts\python.exe -m pip install "
            "-r requirements-dpc.txt"
        ) from exc


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: str | Path, value: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    temporary.replace(destination)


class DeterministicSlicer:
    """Zero-API schema slice: physical candidate tables, with all columns."""

    def __init__(self, llm) -> None:
        self.llm = llm

    def run(
        self,
        candidate_sqls: list[str],
        full_schema: Mapping[str, Any],
        max_correction_attempts: int = 0,
    ) -> dict[str, Any]:
        del max_correction_attempts
        referenced: set[str] = set()
        parsed_any = False
        for sql in candidate_sqls:
            try:
                tree = sqlglot.parse_one(sql, read="sqlite")
            except Exception:
                continue
            parsed_any = True
            cte_names = {
                cte.alias_or_name.lower()
                for cte in tree.find_all(exp.CTE)
                if cte.alias_or_name
            }
            for table in tree.find_all(exp.Table):
                name = table.name
                if name and name.lower() not in cte_names:
                    referenced.add(name.lower())

        lookup = {name.lower(): name for name in full_schema}
        selected_names = {
            lookup[name]
            for name in referenced
            if name in lookup
        }
        if not parsed_any or not selected_names:
            return dict(full_schema)
        return {
            name: schema
            for name, schema in full_schema.items()
            if name in selected_names
        }


def apply_solver_execution_contract(
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Align the official Solver prompt with the constrained executor."""
    adjusted = [dict(message) for message in messages]
    for message in adjusted:
        if (
            message.get("role") == "system"
            and _SOLVER_SYSTEM_MARKER in message.get("content", "")
        ):
            message["content"] = (
                message["content"].rstrip()
                + "\n\n"
                + _SOLVER_EXECUTION_CONTRACT
            )
            break
    return adjusted


def _normalized_usage(
    usage: Mapping[str, int | None] | None,
) -> dict[str, int | None]:
    usage = usage or {}
    return {
        field: (
            int(usage[field])
            if usage.get(field) is not None
            else None
        )
        for field in TOKEN_FIELDS
    }


class DeepSeekDpcLLM:
    """DPC LLM contract backed by DeepSeek with project-native accounting."""

    def __init__(
        self,
        *,
        model_name: str,
        thinking: bool,
        max_tokens: int,
    ) -> None:
        from openai import OpenAI

        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("缺少环境变量 DEEPSEEK_API_KEY")
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.thinking = thinking
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
        )
        self._usage_lock = threading.Lock()
        self._usage = {field: None for field in TOKEN_FIELDS}
        self._calls: list[dict[str, Any]] = []

    def reset_usage(self) -> None:
        with self._usage_lock:
            self._usage = {field: None for field in TOKEN_FIELDS}
            self._calls = []

    def get_usage(self) -> dict[str, int | None]:
        with self._usage_lock:
            return dict(self._usage)

    def get_calls(self) -> list[dict[str, Any]]:
        with self._usage_lock:
            return [
                {
                    **call,
                    "usage": dict(call["usage"]),
                }
                for call in self._calls
            ]

    def _add_usage(self, usage: Mapping[str, int | None] | None) -> None:
        if not usage:
            return
        with self._usage_lock:
            for field in TOKEN_FIELDS:
                value = usage.get(field)
                if value is None:
                    continue
                previous = self._usage[field] or 0
                self._usage[field] = previous + int(value)

    def _add_call(
        self,
        elapsed_seconds: float,
        *,
        usage: Mapping[str, int | None] | None = None,
        error: str | None = None,
    ) -> None:
        call = {
            "elapsed_seconds": round(elapsed_seconds, 6),
            "usage": _normalized_usage(usage),
        }
        if error:
            call["error"] = error
        with self._usage_lock:
            self._calls.append(call)

    def ask(self, messages: list[dict[str, str]]) -> str:
        messages = apply_solver_execution_contract(messages)
        request: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "extra_body": {
                "thinking": {
                    "type": "enabled" if self.thinking else "disabled"
                }
            },
        }
        if not self.thinking:
            request["temperature"] = 0.0
        started = perf_counter()
        try:
            response = self.client.chat.completions.create(**request)
        except Exception as exc:
            elapsed = perf_counter() - started
            record_api_call(
                elapsed,
                error=type(exc).__name__,
            )
            self._add_call(elapsed, error=type(exc).__name__)
            raise
        usage = _response_usage(response)
        elapsed = perf_counter() - started
        record_api_call(elapsed, usage=usage)
        self._add_usage(usage)
        self._add_call(elapsed, usage=usage)
        return (response.choices[0].message.content or "").strip()


def metrics_with_llm_calls(
    base_metrics: Mapping[str, Any],
    llm: Any | None,
) -> dict[str, Any]:
    """Use LLM-owned records because official DPC creates worker threads."""
    result = dict(base_metrics)
    if llm is None or not hasattr(llm, "get_calls"):
        return result
    calls = llm.get_calls()
    result["api_calls"] = len(calls)
    result["api_elapsed_seconds"] = round(
        sum(call["elapsed_seconds"] for call in calls),
        6,
    )
    result["usage"] = _normalized_usage(llm.get_usage())
    result["calls"] = calls
    return result


def classify_pipeline_status(reason: str | None) -> str:
    reason = reason or ""
    if "Error" in reason or "fallback" in reason.lower():
        return "fallback"
    if reason == "No Challenger":
        return "no_duel"
    return "ok"


def pending_records(
    records: list[Mapping[str, Any]],
    completed: Mapping[str, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Rerun checkpoints from older adapters that lost usage/fallback state."""
    return [
        record
        for record in records
        if completed.get(str(record["question_id"]), {}).get("run_format")
        != RUN_FORMAT
    ]


class _ScriptedDpcLLM:
    """Deterministic, no-network LLM used by the public self-test."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._index = 0
        self._lock = threading.Lock()

    def reset_usage(self) -> None:
        return None

    def get_usage(self) -> dict[str, int]:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def ask(self, messages: list[dict[str, str]]) -> str:
        del messages
        with self._lock:
            if self._index >= len(self._responses):
                raise RuntimeError("offline self-test exhausted scripted replies")
            response = self._responses[self._index]
            self._index += 1
            return response

    @property
    def call_count(self) -> int:
        with self._lock:
            return self._index


def run_offline_self_test(
    official_root: str | Path = DEFAULT_OFFICIAL_ROOT,
) -> dict[str, Any]:
    """Run the real official pipeline end-to-end without an API key."""
    _patch_official_executor(official_root)
    from dpc.agents.solver_agent import PythonSolverAgent
    from dpc.agents.tester_agent import TesterAgent
    from dpc.core.pipeline import DPCPipeline

    tester_reply = """
<thinking>An age-18 row distinguishes greater-than from at-least.</thinking>
<result>
{
  "test_data": {
    "people": [
      {"id": 1, "name": "Alex", "age": 18},
      {"id": 2, "name": "Blair", "age": 19}
    ]
  }
}
</result>
""".strip()
    solver_reply = """
<thinking>Keep people whose age is at least 18.</thinking>
<result>
import pandas as pd

def adults(frame):
    return frame.loc[frame["age"] >= 18, ["name"]]

result = adults(people).sort_values("name").reset_index(drop=True)
</result>
""".strip()
    llm = _ScriptedDpcLLM([tester_reply, solver_reply])
    pipeline = DPCPipeline(
        slicer=DeterministicSlicer(llm),
        tester=TesterAgent(llm),
        solver=PythonSolverAgent(llm),
        grouper=None,
        llm=llm,
    )
    champion = (
        "SELECT name FROM people WHERE age > 18 ORDER BY name"
    )
    challenger = (
        "SELECT name FROM people WHERE age >= 18 ORDER BY name"
    )

    with tempfile.TemporaryDirectory(prefix="dpc-self-test-") as temp_dir:
        db_path = Path(temp_dir) / "people.sqlite"
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(
                "CREATE TABLE people "
                "(id INTEGER PRIMARY KEY, name TEXT, age INTEGER)"
            )
            connection.executemany(
                "INSERT INTO people (id, name, age) VALUES (?, ?, ?)",
                [(1, "Alex", 18), (2, "Blair", 19)],
            )
            connection.commit()
        finally:
            connection.close()
        result = pipeline.run(
            question="List names of people who are at least 18 years old.",
            db_path=str(db_path),
            candidate_sqls=[champion, challenger],
            evidence="at least means greater than or equal to",
            max_correction_attempts=0,
            num_test_data=1,
            num_solver_attempts=1,
            phase1_selection_mode="execution",
            eval_metric="bs_f1",
        )

    selected = result["selected_sql"]
    return {
        **result,
        "winner": "direct" if selected == challenger else "dsl",
        "scripted_calls": llm.call_count,
    }


def _load_completed(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"DPC checkpoint must be an object: {path}")
    return {str(key): record for key, record in value.items()}


def _patch_official_executor(official_root: str | Path) -> None:
    _require_official_dpc(official_root)
    import dpc.agents.solver_agent as solver_module

    solver_module.PythonExecutor = SafePythonExecutor


def _run_one(
    record: Mapping[str, Any],
    *,
    db_root: Path,
    model_name: str,
    thinking: bool,
    max_tokens: int,
    max_correction_attempts: int,
    sql_timeout: int,
    python_timeout: int,
    epsilon: float,
) -> dict[str, Any]:
    from dpc.agents.solver_agent import PythonSolverAgent
    from dpc.agents.tester_agent import TesterAgent
    from dpc.core.pipeline import DPCPipeline

    qid = str(record["question_id"])
    dsl_sql, direct_sql = record["candidates"]
    llm = None
    with question_metrics() as metrics:
        try:
            llm = DeepSeekDpcLLM(
                model_name=model_name,
                thinking=thinking,
                max_tokens=max_tokens,
            )
            pipeline = DPCPipeline(
                slicer=DeterministicSlicer(llm),
                tester=TesterAgent(llm),
                solver=PythonSolverAgent(llm),
                grouper=None,
                llm=llm,
            )
            db_path = find_db_file(db_root, record["db_id"])
            result = pipeline.run(
                question=record["question"],
                db_path=str(db_path),
                candidate_sqls=[dsl_sql, direct_sql],
                evidence=record.get("evidence") or "",
                sql_timeout=sql_timeout,
                python_timeout=python_timeout,
                epsilon=epsilon,
                max_correction_attempts=max_correction_attempts,
                num_test_data=1,
                num_solver_attempts=1,
                phase1_selection_mode="execution",
                eval_metric="bs_f1",
            )
            selected = result["selected_sql"]
            if selected not in record["candidates"]:
                raise ValueError("official DPC returned an unknown SQL")
            status = classify_pipeline_status(
                result.get("selection_reason")
            )
            error = None
        except Exception as exc:
            result = {
                "selected_sql": dsl_sql,
                "selection_reason": "safe DSL fallback",
                "champion_score": 0.0,
                "challenger_score": 0.0,
                "token_usage": {},
            }
            selected = dsl_sql
            status = "fallback"
            error = f"{type(exc).__name__}: {exc}"

    final_metrics = metrics_with_llm_calls(metrics.to_dict(), llm)
    return {
        "run_format": RUN_FORMAT,
        "question_id": qid,
        "index": record["index"],
        "db_id": record["db_id"],
        "difficulty": record["difficulty"],
        "status": status,
        "selected_sql": selected,
        "winner": "dsl" if selected == dsl_sql else "direct",
        "selection_reason": result.get("selection_reason"),
        "champion_score": result.get("champion_score"),
        "challenger_score": result.get("challenger_score"),
        "metrics": final_metrics,
        **({"error": error} if error else {}),
    }


def run_pilot(
    *,
    manifest_path: str | Path,
    dsl_path: str | Path,
    output_path: str | Path,
    checkpoint_path: str | Path,
    db_root: str | Path,
    limit: int | None,
    concurrency: int,
    model_name: str,
    thinking: bool,
    max_tokens: int,
    max_correction_attempts: int,
    sql_timeout: int,
    python_timeout: int,
    epsilon: float,
    official_root: str | Path = DEFAULT_OFFICIAL_ROOT,
    progress: bool = True,
) -> tuple[list[str], dict[str, dict]]:
    _patch_official_executor(official_root)
    manifest_path = Path(manifest_path)
    dsl_path = Path(dsl_path)
    output_path = Path(output_path)
    checkpoint_path = Path(checkpoint_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline = load_predictions(dsl_path)

    expected_dsl_sha = manifest.get("sources", {}).get("dsl_sha256")
    if expected_dsl_sha and _sha256(dsl_path) != expected_dsl_sha:
        raise ValueError("DSL prediction SHA-256 no longer matches manifest")

    completed = _load_completed(checkpoint_path)
    records = manifest["records"]
    if limit is not None:
        if limit <= 0:
            raise ValueError("--limit must be positive")
        records = records[:limit]
    pending = pending_records(records, completed)
    reusable = len(records) - len(pending)
    print(
        f"DPC-1x1 pilot: {len(records)} target, "
        f"{reusable} reusable checkpointed, {len(pending)} pending"
    )
    bar = Progress(len(pending), "dpc", enabled=progress)

    kwargs = {
        "db_root": Path(db_root),
        "model_name": model_name,
        "thinking": thinking,
        "max_tokens": max_tokens,
        "max_correction_attempts": max_correction_attempts,
        "sql_timeout": sql_timeout,
        "python_timeout": python_timeout,
        "epsilon": epsilon,
    }
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(_run_one, record, **kwargs): record
            for record in pending
        }
        for future in as_completed(futures):
            result = future.result()
            completed[result["question_id"]] = result
            write_json_atomic(checkpoint_path, completed)
            bar.step()

    current_completed = {
        qid: record
        for qid, record in completed.items()
        if record.get("run_format") == RUN_FORMAT
    }
    predictions = merge_dpc_results(
        baseline,
        manifest,
        current_completed,
    )
    write_json_atomic(output_path, predictions)
    trace_path = output_path.with_name(output_path.stem + ".trace.json")
    ordered_trace = [
        current_completed[str(record["question_id"])]
        for record in manifest["records"]
        if str(record["question_id"]) in current_completed
    ]
    write_json_atomic(trace_path, ordered_trace)

    switches = sum(record["winner"] == "direct" for record in ordered_trace)
    fallbacks = sum(record["status"] == "fallback" for record in ordered_trace)
    usage = {}
    for field in TOKEN_FIELDS:
        values = [
            record["metrics"]["usage"][field]
            for record in ordered_trace
            if record["metrics"]["usage"][field] is not None
        ]
        usage[field] = sum(values) if values else None
    print(
        f"completed {len(ordered_trace)}/{manifest['size']}; "
        f"switches_to_direct={switches}; fallbacks={fallbacks}"
    )
    print(f"usage {json.dumps(usage, ensure_ascii=False)}")
    print(f"wrote {output_path}")
    print(f"wrote {trace_path}")
    return predictions, completed
