"""SQL structure signatures and deterministic semantic/structure rank fusion."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Mapping, Sequence

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel


StructureFeatures = Counter[str]


@dataclass(frozen=True)
class FusedCandidate:
    """One candidate's ranks and final retrieval score."""

    source_id: str
    semantic_rank: int
    structure_rank: int
    structure_similarity: float
    fusion_score: float


_PREDICATE_TYPES = (
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.In,
    exp.Between,
    exp.Like,
    exp.ILike,
    exp.Is,
    exp.Exists,
    exp.And,
    exp.Or,
    exp.Not,
)
_ARITHMETIC_TYPES = (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod)
_SET_OPERATION_NAMES = {
    exp.Union: "union",
    exp.Intersect: "intersect",
    exp.Except: "except",
}


def _valid_tree(tree: exp.Expression) -> bool:
    """Reject permissively parsed fragments that are not usable SELECT SQL."""
    selects = list(tree.find_all(exp.Select))
    if not selects:
        return False
    for select in selects:
        if not select.expressions:
            return False
        where = select.args.get("where")
        if where is not None and where.this is None:
            return False
        from_clause = select.args.get("from_")
        if from_clause is not None and from_clause.this is None:
            return False
    return True


def _projection_kind(expression: exp.Expression) -> str:
    while isinstance(expression, (exp.Alias, exp.Paren)):
        expression = expression.this
    if isinstance(expression, exp.AggFunc):
        return "aggregate"
    if isinstance(expression, exp.Window):
        return "window"
    if isinstance(expression, exp.Column):
        return "column"
    if isinstance(expression, exp.Star):
        return "star"
    if isinstance(expression, exp.Literal):
        return "literal"
    if isinstance(expression, exp.Subquery):
        return "subquery"
    if isinstance(expression, exp.Case):
        return "case"
    if isinstance(expression, _ARITHMETIC_TYPES):
        return "arithmetic"
    return expression.key


def _join_kind(join: exp.Join) -> str:
    side = str(join.args.get("side") or "").lower()
    kind = str(join.args.get("kind") or "").lower()
    method = str(join.args.get("method") or "").lower()
    return "_".join(part for part in (method, side, kind) if part) or "inner"


def _query_depth(tree: exp.Expression) -> int:
    max_depth = 0

    def visit(node: exp.Expression, depth: int) -> None:
        nonlocal max_depth
        next_depth = depth + int(isinstance(node, (exp.Subquery, exp.CTE)))
        max_depth = max(max_depth, next_depth)
        for child in node.iter_expressions():
            visit(child, next_depth)

    visit(tree, 0)
    return max_depth


def sql_structure_features(sql: str) -> StructureFeatures:
    """Return an identifier/literal-invariant multiset signature for SQL."""
    if not isinstance(sql, str) or not sql.strip():
        return Counter()
    try:
        tree = sqlglot.parse_one(
            sql,
            read="sqlite",
            error_level=ErrorLevel.RAISE,
        )
    except (sqlglot.errors.ParseError, ValueError, TypeError):
        return Counter()
    if tree is None or not _valid_tree(tree):
        return Counter()

    features: StructureFeatures = Counter()
    for select in tree.find_all(exp.Select):
        features["query:select"] += 1
        features["projection_count"] += len(select.expressions)
        for projection in select.expressions:
            features[f"projection:{_projection_kind(projection)}"] += 1

        for argument, label in (
            ("from_", "from"),
            ("where", "where"),
            ("group", "group"),
            ("having", "having"),
            ("qualify", "qualify"),
        ):
            if select.args.get(argument) is not None:
                features[f"clause:{label}"] += 1

        group = select.args.get("group")
        if group is not None:
            features["group_key_count"] += len(group.expressions)

    for node in tree.walk():
        if isinstance(node, exp.AggFunc):
            features[f"aggregate:{node.key}"] += 1
            if node.args.get("distinct") or isinstance(node.this, exp.Distinct):
                features["aggregate:distinct"] += 1
        if isinstance(node, exp.Join):
            features[f"join:{_join_kind(node)}"] += 1
        if isinstance(node, _PREDICATE_TYPES):
            features[f"predicate:{node.key}"] += 1
        if isinstance(node, _ARITHMETIC_TYPES):
            features[f"arithmetic:{node.key}"] += 1
        if isinstance(node, exp.Window):
            features["window"] += 1
        if isinstance(node, exp.Order):
            features["clause:order"] += 1
        if isinstance(node, exp.Limit):
            features["clause:limit"] += 1
        if isinstance(node, exp.Offset):
            features["clause:offset"] += 1
        if isinstance(node, exp.Subquery):
            features["subquery"] += 1
        if isinstance(node, exp.CTE):
            features["cte"] += 1
        for node_type, name in _SET_OPERATION_NAMES.items():
            if isinstance(node, node_type):
                features[f"setop:{name}"] += 1
                break

    depth = _query_depth(tree)
    if depth:
        features["query_depth"] = depth
    return features


def multiset_jaccard(
    left: Mapping[str, int], right: Mapping[str, int]
) -> float:
    """Compute weighted Jaccard similarity between non-negative counters."""
    keys = set(left) | set(right)
    if not keys:
        return 0.0
    intersection = sum(min(left.get(key, 0), right.get(key, 0)) for key in keys)
    union = sum(max(left.get(key, 0), right.get(key, 0)) for key in keys)
    return float(intersection / union) if union else 0.0


def _normalized_borda(rank: int, count: int) -> float:
    if count == 1:
        return 1.0
    return (count - rank) / (count - 1)


def rank_fusion(
    semantic_order: Sequence[str],
    structure_scores: Mapping[str, float],
    *,
    semantic_weight: float = 0.5,
) -> tuple[FusedCandidate, ...]:
    """Fuse semantic and structural ranks with stable, scale-free scoring."""
    if not 0.0 <= semantic_weight <= 1.0 or not math.isfinite(semantic_weight):
        raise ValueError("semantic_weight must be finite and within [0, 1]")
    if len(set(semantic_order)) != len(semantic_order):
        raise ValueError("semantic_order source IDs must be unique")
    if set(semantic_order) != set(structure_scores):
        raise ValueError("semantic_order and structure_scores must have the same source IDs")
    if any(not math.isfinite(float(score)) for score in structure_scores.values()):
        raise ValueError("structure scores must be finite")
    if not semantic_order:
        return ()

    semantic_ranks = {
        source_id: rank
        for rank, source_id in enumerate(semantic_order, start=1)
    }
    structure_order = sorted(
        semantic_order,
        key=lambda source_id: (
            -float(structure_scores[source_id]),
            semantic_ranks[source_id],
            source_id,
        ),
    )
    structure_ranks = {
        source_id: rank
        for rank, source_id in enumerate(structure_order, start=1)
    }
    count = len(semantic_order)
    candidates = []
    for source_id in semantic_order:
        semantic_rank = semantic_ranks[source_id]
        structure_rank = structure_ranks[source_id]
        score = (
            semantic_weight * _normalized_borda(semantic_rank, count)
            + (1.0 - semantic_weight)
            * _normalized_borda(structure_rank, count)
        )
        candidates.append(
            FusedCandidate(
                source_id=source_id,
                semantic_rank=semantic_rank,
                structure_rank=structure_rank,
                structure_similarity=float(structure_scores[source_id]),
                fusion_score=score,
            )
        )

    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                -candidate.fusion_score,
                candidate.semantic_rank,
                candidate.source_id,
            ),
        )
    )
