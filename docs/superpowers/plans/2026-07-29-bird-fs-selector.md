# BIRD Few-Shot Candidate Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test whether output-contract pairwise selection over the existing
BIRD Direct+FS and DSL+FS predictions improves DSL+FS by at least one EX point.

**Architecture:** A standalone `model.selection` command performs a
deterministic read-only execution router, calls DeepSeek only for successful
different-result pairs, and writes an ordinary prediction JSON plus audit
trace. Evaluation code and existing model variants remain untouched.

**Tech Stack:** Python 3.11+, SQLite read-only execution, existing OpenAI SDK
DeepSeek endpoint, pytest.

## Global Constraints

- Do not rerun Direct+FS or DSL+FS generation.
- Do not read gold SQL or evaluation labels during selection.
- Do not modify existing prediction files.
- Do not change `bird.evaluate` or `archer_eval`.
- Use one selector API call at most per unresolved sample and no selector retry.
- Fall back to DSL on malformed output, API error, both-invalid, or low confidence.
- Stop the idea if the selected result is below 976/1534.

---

### Task 1: Deterministic candidate router

**Files:**
- Create: `model/selection/__init__.py`
- Create: `model/selection/router.py`
- Test: `tests/test_selection.py`

**Interfaces:**
- Consumes: two SQL strings and one database path.
- Produces: `route_candidates(direct_sql, dsl_sql, db_path) -> RouteDecision`.

- [ ] **Step 1: Write failing routing tests**

```python
def test_router_skips_equal_sql(tmp_path):
    decision = route_candidates("SELECT 1", " SELECT 1; ", tmp_path / "missing.sqlite")
    assert decision.route == "same_sql"
    assert decision.winner == "dsl"

def test_router_chooses_only_executable_candidate(toy_db):
    decision = route_candidates("SELECT value FROM t", "SELECT nope FROM t", toy_db)
    assert decision.route == "direct_only_valid"
    assert decision.winner == "direct"

def test_router_sends_different_results_to_pairwise(toy_db):
    decision = route_candidates(
        "SELECT value FROM t WHERE value = 1",
        "SELECT value FROM t WHERE value = 2",
        toy_db,
    )
    assert decision.route == "pairwise"
    assert decision.winner is None
```

- [ ] **Step 2: Run the focused tests and verify missing-module failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_selection.py -q`

Expected: collection fails because `model.selection.router` does not exist.

- [ ] **Step 3: Implement the router**

Implement immutable execution summaries and route decisions. Reuse
`archer_eval.execution.execute_sql` and BIRD's `rows_match`; keep database
connections read-only.

- [ ] **Step 4: Run focused tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_selection.py -q`

Expected: all router tests pass.

### Task 2: One-call output-contract selector

**Files:**
- Create: `model/selection/pairwise.py`
- Create: `model/selection/prompts/pairwise.md`
- Modify: `tests/test_selection.py`

**Interfaces:**
- Consumes: `SelectionInput` containing question, evidence, DDL, candidate SQL,
  execution summaries, and sample index.
- Produces: `PairwiseDecision` with winner, confidence, violations, reason,
  raw reply, metrics, and candidate-source mapping.

- [ ] **Step 1: Write failing parser and fallback tests**

```python
def test_parse_pairwise_decision_accepts_strict_json():
    decision = parse_pairwise_reply(
        '{"winner":"A","confidence":"high","violations_a":[],'
        '"violations_b":["missing LIMIT"],"reason":"A matches top-k."}'
    )
    assert decision.winner == "A"

def test_low_confidence_maps_back_to_dsl():
    chosen = resolve_pairwise_winner("A", "low", {"A": "direct", "B": "dsl"})
    assert chosen == "dsl"
```

- [ ] **Step 2: Verify the focused tests fail because interfaces are missing**

Run: `.venv\Scripts\python.exe -m pytest tests/test_selection.py -q`

Expected: import or attribute failure for the pairwise interfaces.

- [ ] **Step 3: Implement prompt rendering, strict parsing, and one API call**

Use the existing DeepSeek endpoint and `question_metrics`. Deterministically
swap candidate order by sample index. Do not retry malformed or failed calls.

- [ ] **Step 4: Run focused tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_selection.py -q`

Expected: all selector tests pass.

### Task 3: CLI, real experiment, and decision gate

**Files:**
- Create: `model/selection/__main__.py`
- Modify: `tests/test_selection.py`
- Modify: `README.md`
- Modify: `docs/PROGRESS.md`

**Interfaces:**
- Consumes: dataset alias, Direct prediction path, DSL prediction path, output path.
- Produces: aligned prediction JSON and `.trace.json`.

- [ ] **Step 1: Write a failing end-to-end CLI test**

The test supplies two two-question prediction files, a toy database, and a
fake endpoint. It asserts aligned output, one pairwise call only for the
different-result sample, and complete trace routes.

- [ ] **Step 2: Verify the CLI test fails because the entry point is missing**

Run: `.venv\Scripts\python.exe -m pytest tests/test_selection.py -q`

Expected: failure because `model.selection.__main__` has no runnable command.

- [ ] **Step 3: Implement the CLI and artifact validation**

Validate prediction lengths and source hashes before routing. Write artifacts
atomically after all samples finish. Print route counts, API calls, elapsed
time, and token totals.

- [ ] **Step 4: Run focused tests and the full regression suite**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_selection.py -q
.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Run the one permitted main selector experiment**

Run:

```powershell
python -m model.selection --data bird_dev --direct predictions/bird/bird-pro-t-direct-fs_bird_dev.json --dsl predictions/bird/bird-pro-t-dsl-fs_bird_dev.json --out predictions/bird/bird-pro-t-fs-sel_bird_dev.json
python -m bird eval --data bird_dev --pred predictions/bird/bird-pro-t-fs-sel_bird_dev.json --official
```

Expected: an official BIRD report under `results/bird/`.

- [ ] **Step 6: Apply the fixed gate and document the result**

If correct predictions are below 976, record the negative result and stop.
If they are at least 976, record the positive result and prepare one
confirmation selector run before normal-pipeline integration.
