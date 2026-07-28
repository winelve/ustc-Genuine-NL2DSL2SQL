# CHESS-IR Value Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fixed-artifact CHESS Information Retriever for Archer and BIRD, with relevant-value and equal-budget random-value model arms.

**Architecture:** Heavy database indexing and embedding retrieval run only through `model.value_evidence.offline` in the separate few-shot environment. Online Direct/DSL models load a strict JSON store and render DDL plus retrieved values/descriptions without importing Torch, SentenceTransformers, NumPy, or datasketch.

**Tech Stack:** Python 3.11+, SQLite read-only access, datasketch MinHashLSH, sentence-transformers/all-mpnet-base-v2, DeepSeek OpenAI-compatible chat API, pytest.

## Global Constraints

- BIRD human evidence stays enabled.
- Direct and DSL share the same fixed selection artifact.
- Baselines with Value Evidence disabled must remain byte-identical and must not read VE files.
- Prediction JSON remains a SQL-only list; provenance is trace-only.
- Database access is read-only.
- API keys come only from environment variables.
- Dev gold SQL and dev EX may not tune retrieval thresholds.
- Real API/data preparation may be skipped during implementation, but commands and artifact contracts must be complete and fail closed.

---

### Task 1: Strict runtime artifact and renderer

**Files:**
- Create: `model/value_evidence/__init__.py`
- Create: `model/value_evidence/types.py`
- Create: `model/value_evidence/store.py`
- Create: `model/value_evidence/render.py`
- Test: `tests/test_value_evidence.py`

**Interfaces:**
- Produces: `ValueEvidenceStore.from_path(path)`, `ValueEvidenceStore.for_sample(db_id, question)`, `render_value_schema(db_path, record, mode)`, and `value_evidence_trace(...)`.

- [ ] Write failing tests for strict metadata/record validation, missing records, duplicate values, relevant/random render equality except cell values, and DDL-only schema output.
- [ ] Run `pytest tests/test_value_evidence.py -q` and confirm failures are caused by the missing package.
- [ ] Implement immutable dataclasses, strict JSON loader, deterministic renderer, and trace serialization without heavy imports.
- [ ] Run `pytest tests/test_value_evidence.py -q` and confirm the runtime tests pass.

### Task 2: CHESS-compatible database preprocessing

**Files:**
- Create: `model/value_evidence/index.py`
- Modify: `requirements-fewshot.txt`
- Test: `tests/test_value_evidence.py`

**Interfaces:**
- Consumes: SQLite paths and optional BIRD column docs.
- Produces: `extract_unique_text_values(db_path)`, `create_minhash(...)`, `build_database_index(...)`, and an ignored per-database index directory.

- [ ] Add failing tests using a toy SQLite database for primary-key, ID/date/address, TEXT type, and size-filter behavior.
- [ ] Run the focused tests and verify the expected failures.
- [ ] Port the CHESS filtering rules with quoted identifiers and `connect_ro`; import datasketch/NumPy only inside heavy functions.
- [ ] Serialize metadata, unique values, LSH/minhash objects, docs, and local description embeddings with input checksums.
- [ ] Add `datasketch==1.6.4` to the offline requirements.
- [ ] Run the focused tests and confirm they pass.

### Task 3: DeepSeek keyword artifact

**Files:**
- Create: `model/value_evidence/keywords.py`
- Create: `model/value_evidence/prompts/extract_keywords.md`
- Test: `tests/test_value_evidence.py`

**Interfaces:**
- Produces: `render_keyword_prompt(question, evidence)`, `parse_keywords(reply)`, and chunked `build_keyword_artifact(...)`.

- [ ] Add failing tests for exact CHESS prompt fields, Python/JSON list parsing, fenced output rejection/cleanup, deduplication, invalid replies, and checkpoint resume.
- [ ] Run the focused tests and verify RED.
- [ ] Implement the CHESS prompt and DeepSeek Flash non-thinking caller with temperature 0 and max_tokens 256.
- [ ] Record per-question usage, prompt/model checksum, target key, and failures; fail finalization if any target is missing.
- [ ] Run the focused tests and confirm GREEN.

### Task 4: Entity/context retrieval and deterministic control

**Files:**
- Create: `model/value_evidence/retrieve.py`
- Create: `model/value_evidence/offline.py`
- Test: `tests/test_value_evidence.py`

**Interfaces:**
- Consumes: keyword artifact, database indexes, all-mpnet encoder.
- Produces: strict `chess-ir-mpnet-v1` selection JSON and CLI commands `index`, `keywords`, `select`, `audit`.

- [ ] Add failing tests for keyword expansion, top-N LSH ordering, edit threshold, exact/substring preservation, relative per-column filtering, caps, context merge, and stable length-matched controls.
- [ ] Run focused tests and verify RED.
- [ ] Implement pure candidate post-processing separately from heavy index/model adapters.
- [ ] Implement exact cosine context retrieval and batched candidate encoding with normalized all-mpnet vectors.
- [ ] Implement deterministic control selection from the same table/column and closest-length candidates.
- [ ] Implement CLI metadata/checksum/audit validation and module entry point.
- [ ] Run focused tests and confirm GREEN.

### Task 5: Direct/DSL/BIRD integration

**Files:**
- Modify: `config.py`
- Modify: `.gitignore`
- Modify: `model/prompts.py`
- Modify: `bird/official.py`
- Modify: `model/api.py`
- Modify: `model/pipeline/context.py`
- Modify: `model/pipeline/models.py`
- Modify: `model/bird.py`
- Modify: `model/__init__.py`
- Modify: `model/__main__.py`
- Test: `tests/test_value_evidence.py`
- Test: `tests/test_model.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_bird.py`

**Interfaces:**
- Consumes: `archer_en_dev_chess_ir.json` or `bird_dev_chess_ir.json`.
- Produces: eight registered `*-ve` / `*-ve-r` model arms and per-question VE trace.

- [ ] Add failing prompt/message tests proving baseline bytes remain unchanged and VE variants fail closed without records.
- [ ] Add failing class-registration and single-variable-switch tests.
- [ ] Run only the named tests and verify RED.
- [ ] Add `VALUE_EVIDENCE_DIR`, lazy store loading, optional schema override, runtime rendering, trace fields, and model registrations.
- [ ] Keep BIRD Direct evidence enabled and insert VE between DDL and official comment block.
- [ ] Run the named tests and confirm GREEN.

### Task 6: Documentation and completion verification

**Files:**
- Modify: `README.md`
- Modify: `docs/PROGRESS.md`

**Interfaces:**
- Produces: copy-paste PowerShell commands for environment setup, index/keyword/selection/audit, preview/smoke/full runs, and staged experiment stopping rules.

- [ ] Document the 1.4M keyword-token budget, separate offline environment, artifact paths, resumability, and the minimal test order.
- [ ] Document that `ve` is run first; `ve-r` and DSL full runs are conditional on positive signal.
- [ ] Run `git diff --check`.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_value_evidence.py tests/test_model.py tests/test_pipeline.py tests/test_bird.py -q`.
- [ ] Run `.venv\Scripts\python.exe -m pytest -q`.
- [ ] Inspect model list and no-API prompt previews using a temporary toy artifact.
- [ ] Update `docs/PROGRESS.md` with implementation, decisions, verification evidence, missing real artifacts, and next commands.
