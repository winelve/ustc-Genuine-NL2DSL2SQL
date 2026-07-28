"""Concurrent selection runner shared by the CLI and tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from archer_eval.data import Sample
from archer_eval.progress import Progress
from bird.official import schema_ddl_block
from model.metrics import question_metrics
from model.selection.pairwise import (
    judge_pairwise,
    resolve_pairwise_winner,
)
from model.selection.router import route_candidates


def select_all(
    *,
    samples: list[Sample],
    db_paths: list[Path],
    direct_predictions: list[str],
    dsl_predictions: list[str],
    endpoint,
    concurrency: int,
    progress: bool = True,
) -> tuple[list[str], list[dict]]:
    sizes = {
        len(samples),
        len(db_paths),
        len(direct_predictions),
        len(dsl_predictions),
    }
    if len(sizes) != 1:
        raise ValueError(
            "samples, db_paths, direct predictions, and DSL predictions "
            "must have equal lengths"
        )

    def one(indexed):
        index, (sample, db_path, direct_sql, dsl_sql) = indexed
        error = None
        pairwise = None
        mapping = None
        with question_metrics() as metrics:
            route = route_candidates(direct_sql, dsl_sql, db_path)
            winner = route.winner
            if route.route == "pairwise":
                try:
                    pairwise, mapping = judge_pairwise(
                        endpoint,
                        sample_index=index,
                        question=sample.question,
                        evidence=sample.commonsense_knowledge or "",
                        schema=schema_ddl_block(db_path),
                        direct_sql=direct_sql,
                        dsl_sql=dsl_sql,
                        direct_summary=route.direct,
                        dsl_summary=route.dsl,
                    )
                    winner = resolve_pairwise_winner(
                        pairwise.winner,
                        pairwise.confidence,
                        mapping,
                    )
                except Exception as exc:
                    winner = "dsl"
                    error = f"{type(exc).__name__}: {exc}"

        prediction = direct_sql if winner == "direct" else dsl_sql
        trace = {
            "index": index,
            "question": sample.question,
            "db_id": sample.db_id,
            "route": route.route,
            "winner": winner,
            "direct": route.direct.to_dict() if route.direct else None,
            "dsl": route.dsl.to_dict() if route.dsl else None,
            "candidate_mapping": mapping,
            "pairwise": pairwise.to_dict() if pairwise else None,
            "metrics": metrics.to_dict(),
        }
        if error:
            trace["error"] = error
        return prediction, trace

    items = list(enumerate(zip(
        samples,
        db_paths,
        direct_predictions,
        dsl_predictions,
    )))
    bar = Progress(len(items), "select", enabled=progress)
    predictions, traces = [], []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for prediction, trace in pool.map(one, items):
            predictions.append(prediction)
            traces.append(trace)
            bar.step()
    return predictions, traces
