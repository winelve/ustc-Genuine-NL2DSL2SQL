# Exact Model Prompt Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a no-API, model-aware CLI that prints only the exact initial messages sent by the selected DSL pipeline.

**Architecture:** Runtime and preview share context preparation and initial-message construction. The CLI resolves the existing model registry and invokes a preview hook without initializing `ChatEndpoint`.

**Tech Stack:** Python, argparse, pytest, existing pipeline templates and few-shot store.

## Global Constraints

- Preview must not call or initialize an API client.
- Preview must not show disabled stages or speculative repair messages.
- Existing generation behavior and templates must remain unchanged.

---

### Task 1: Exact message construction

**Files:**
- Modify: `model/pipeline/models.py`
- Modify: `model/pipeline/stages/declare.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `PlanSQL.preview_messages(sample, db_path) -> list[dict[str, str]]`
- Produces: `DeclareStage.initial_messages(ctx, plan) -> list[dict[str, str]]`

- [ ] Write tests proving FS/evidence are present and unused components absent.
- [ ] Run focused tests and confirm failure because preview hooks are missing.
- [ ] Extract shared context and message construction.
- [ ] Run focused tests and confirm success.

### Task 2: Model-aware CLI and documentation

**Files:**
- Modify: `model/pipeline/__main__.py`
- Modify: `README.md`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `PlanSQL.preview_messages`
- Produces: `python -m model.pipeline --model NAME --data DATA --preview N`

- [ ] Write a failing CLI test for exact `pro-t-dsl-fs` output.
- [ ] Add `--model`, registry validation and exact message printing.
- [ ] Update README commands.
- [ ] Run focused and full test suites.
- [ ] Update `docs/PROGRESS.md` and commit exact task files.
