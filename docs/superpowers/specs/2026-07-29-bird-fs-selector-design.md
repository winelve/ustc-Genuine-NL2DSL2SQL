# BIRD Few-Shot Candidate Selector Design

## Goal

Reuse the existing `bird-pro-t-direct-fs` and `bird-pro-t-dsl-fs` prediction
files to test whether a low-cost selector can improve the current BIRD
`bird_dev` best score of 960/1534 (62.58%). Candidate generation is not rerun.

The experiment succeeds only if the selected output reaches at least 976/1534
(63.62%, at least +1.04 EX). If it misses that gate, stop this direction
without adding it to the normal generation pipeline.

## Scope

The selector is a post-generation command under `model/selection/`. It reads
two aligned prediction files and writes a third standard prediction file, so
`bird.evaluate` and `archer_eval` remain unchanged and continue communicating
with `model` only through prediction JSON.

The experiment uses:

- `predictions/bird/bird-pro-t-direct-fs_bird_dev.json`
- `predictions/bird/bird-pro-t-dsl-fs_bird_dev.json`
- `data/bird/dev.json`
- the configured read-only BIRD databases

It never reads gold SQL or per-question evaluation matches while selecting.

## Routing

For each aligned pair:

1. If normalized SQL text is equal, return the DSL candidate without executing.
2. Otherwise execute both candidates read-only.
3. If their successful result sets are equal under BIRD's official
   `set(rows)` semantics, return the DSL candidate.
4. If exactly one candidate executes, return that candidate.
5. If neither executes, return the DSL candidate.
6. Only when both execute and return different results, call the pairwise
   selector.

The current artifacts contain 1114 equal-result cases and 387 successful
different-result cases, so only about 25.23% require an API call.

## Pairwise Selector

The selector receives only the question, BIRD evidence, database DDL,
anonymized Candidate A/B SQL, and execution summaries (`ok`, `n_rows`,
`n_cols`, error). It does not receive result rows, gold SQL, gold results, or
evaluation labels.

Candidate order is deterministically swapped from the sample index so the
prompt does not consistently place Direct or DSL first. A single DeepSeek call
must inspect the output contract:

- requested output columns;
- aggregation and derived formulas;
- filters and literal values;
- joins and entity scope;
- grouping and HAVING;
- ordering, top-k and LIMIT;
- temporal constraints;
- special definitions in BIRD evidence.

The model may only choose A or B; it may not generate a third SQL. It returns
strict JSON with `winner`, `confidence`, candidate violations, and a concise
reason. A malformed response, API failure, or `low` confidence falls back to
DSL. There is no selector retry.

## Artifacts and Audit

The command writes:

- `predictions/bird/bird-pro-t-fs-sel_bird_dev.json`
- `predictions/bird/bird-pro-t-fs-sel_bird_dev.trace.json`

Each trace entry records the route, candidate-source mapping, execution
summaries, selector decision, final source, elapsed time, token usage, and
source-file hashes. Result rows are not persisted.

## Experiment

Run one full selector pass over the existing predictions and evaluate it with
the local BIRD implementation plus the official script. Compare it with
DSL+FS using paired flips and the exact McNemar test.

- `< 976` correct: reject and stop.
- `>= 976` correct: treat as a positive result, run one confirmation selector
  pass before integrating it into the normal workflow.

Only a positive result justifies README integration and a deployable
dual-generation workflow. A negative experiment retains the standalone
artifacts and records the result in `docs/PROGRESS.md`.
