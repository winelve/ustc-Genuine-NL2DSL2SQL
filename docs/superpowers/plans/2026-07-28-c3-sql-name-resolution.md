# C3 SQL Name Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop C3 from rejecting legal quoted physical columns, physical table aliases, and scoped CTE/subquery outputs while preserving unknown-name errors.

**Architecture:** Build a small read-only SQL name environment from the already parsed sqlglot AST. C3 normalizes SQLite identifiers, resolves physical aliases to `SchemaInfo`, and validates CTE/subquery outputs through their declared relation instead of globally accepting every alias.

**Tech Stack:** Python 3.12, sqlglot, pytest, SQLite

## Global Constraints

- Keep `archer_eval` independent from `model`.
- Do not alter prediction-file or evaluation protocols.
- Keep databases read-only.
- Do not weaken C3 for names that cannot be resolved from the SQL AST.

---

### Task 1: Quoted physical identifiers

**Files:**
- Modify: `tests/test_dsl.py`
- Modify: `model/pipeline/dsl/checks.py`

**Interfaces:**
- Consumes: `SchemaInfo`, parsed `sqlglot.exp.Expression`
- Produces: identifier normalization used only by C3

- [ ] Add a parametrized test whose declaration references `singer."Song Name"`,
  ``singer.`Song Name` ``, and `singer.[Song Name]`, plus a control using
  `singer."Missing Name"`.
- [ ] Run the test and verify the three legal references fail on the old code.
- [ ] Add a helper that removes one valid pair of SQLite identifier delimiters and lowercases the result.
- [ ] Use the normalized table and column in `check_column`.
- [ ] Run the test and existing C3 tests.

### Task 2: Physical table aliases

**Files:**
- Modify: `tests/test_dsl.py`
- Modify: `model/pipeline/dsl/checks.py`

**Interfaces:**
- Consumes: `FROM/JOIN` table nodes in the SQL AST
- Produces: `alias -> physical table` mappings for C3

- [ ] Add a test for `SELECT f.Name FROM singer AS f` declared as `f.Name`.
- [ ] Add controls proving `ghost.Name` and `f.Missing` still fail.
- [ ] Run the test and verify only the legal alias case fails on the old code.
- [ ] Collect aliases from physical `exp.Table` nodes and resolve them before checking `SchemaInfo`.
- [ ] Run the alias test and existing C3 tests.

### Task 3: Scoped CTE and subquery outputs

**Files:**
- Modify: `tests/test_dsl.py`
- Modify: `model/pipeline/dsl/checks.py`

**Interfaces:**
- Consumes: CTE/subquery `SELECT` projections
- Produces: relation output maps used by C3

- [ ] Add tests for `WITH rates AS (SELECT Age * 2 AS doubled FROM singer)
  SELECT rates.doubled FROM rates` and for a subquery alias with the same shape.
- [ ] Add controls for `rates.missing` and an unqualified name that is not produced by a visible relation.
- [ ] Run the tests and verify the legal derived references fail on the old code.
- [ ] Derive output names from each CTE/subquery projection and resolve qualified relation references.
- [ ] Allow a derived declaration expression's unqualified column only when it is a physical column or a derived output visible in the SQL query.
- [ ] Run all C3 tests.

### Task 4: BIRD trace regressions and full verification

**Files:**
- Modify: `tests/test_dsl.py`
- Modify: `docs/PROGRESS.md`

**Interfaces:**
- Consumes: distilled structures from BIRD question_id 0, 3, and 8 traces
- Produces: regression protection and progress record

- [ ] Add compact regressions for the quoted `frpm` columns, `f/sc/sat` aliases,
  and `free_meal_rate` CTE output.
- [ ] Run `python -m pytest tests/test_dsl.py -q`.
- [ ] Re-run the trace audit and confirm the identified name classes resolve.
- [ ] Run `.venv\Scripts\python.exe -m pytest -q`.
- [ ] Update `docs/PROGRESS.md` with the fix, evidence, and next step.
