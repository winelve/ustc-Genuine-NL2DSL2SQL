# Exact Model Prompt Preview Design

## Goal

`python -m model.pipeline --model <name> --data <dataset> --preview <index>`
must print exactly the initial messages that the selected pipeline model would
send for that sample, without calling an API.

## Design

- Move the DSL stage's initial system/user message construction into one method
  shared by runtime generation and preview.
- Move pipeline context preparation (schema, evidence and fixed few-shot
  selection) into one method shared by runtime generation and preview.
- Resolve `--model` through the existing `MODELS` registry. Reject models that
  do not expose pipeline message preview.
- Print only enabled messages. Do not print planner, SQL generator, archived
  components, or repair messages that have not been triggered.
- Preserve the existing zero-based `--preview` index.

## Verification

- A `pro-t-dsl-fs` preview contains the selected examples and no planner text.
- A `bird-pro-t-dsl-fs` preview contains BIRD evidence.
- Runtime and preview use the same message-building method.
- Invalid/non-pipeline model names fail clearly.
