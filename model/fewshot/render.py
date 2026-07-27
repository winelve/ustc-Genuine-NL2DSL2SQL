"""Prompt rendering for fixed few-shot SQL references."""

from .types import SelectionRecord


_HEADER = (
    "### Retrieved examples (SQL semantic references only; they do not define "
    "the target output format)"
)


def render_reference_examples(record: SelectionRecord | None) -> str:
    """Render SQL-only semantic references without changing the target contract."""
    if record is None:
        return ""
    examples = [
        f"Reference question: {selected.example.question}\n"
        f"Reference SQL: {selected.example.sql}"
        for selected in record.examples
    ]
    return _HEADER + "\n\n" + "\n\n".join(examples)
