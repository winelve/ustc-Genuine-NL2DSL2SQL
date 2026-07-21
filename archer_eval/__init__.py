"""Archer text-to-SQL evaluation framework.

Implements VA (Valid SQL) and EX (Execution Accuracy) following
Algorithm 1 of "Archer: A Human-Labeled Text-to-SQL Dataset with
Arithmetic, Commonsense and Hypothetical Reasoning" (EACL 2024).

Module dependency graph (arrows point at what a module imports):

    config.py      <- paths & defaults, imported by everything below
    data.py        <- dataset / prediction loading (standalone)
    execution.py   <- one SQL against one SQLite db (standalone)
    metrics.py     <- Algorithm 1, uses execution.ExecutionResult
    evaluate.py    <- orchestration: data + execution + metrics -> report dict
    report.py      <- report dict -> results/<name>.json + .md
    __main__.py    <- CLI wiring it all together
"""

from archer_eval.data import Sample, load_dataset, load_predictions
from archer_eval.evaluate import SampleResult, evaluate
from archer_eval.execution import ExecutionResult, execute_sql
from archer_eval.metrics import execution_match, has_outermost_order_by
from archer_eval.report import write_report

__all__ = [
    "Sample",
    "load_dataset",
    "load_predictions",
    "ExecutionResult",
    "execute_sql",
    "execution_match",
    "has_outermost_order_by",
    "evaluate",
    "SampleResult",
    "write_report",
]
