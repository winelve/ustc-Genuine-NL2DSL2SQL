# CHESS-IR VE2 Design

## Goal

Repair the Archer Value Evidence experiment without overwriting the negative
`pro-t-direct-ve` result. VE2 must isolate the effect of retrieved values:

1. remove the v1 substring bypass that admitted semantically unrelated values;
2. preserve the complete CT-3 baseline schema, including its three sample rows;
3. append the retrieved value block as the only prompt change.

## Retrieval

The v1 strategy remains readable as `chess-ir-mpnet-v1`. VE2 uses
`chess-ir-mpnet-v2` and applies the CHESS filters to every candidate:

1. absolute edit similarity >= 0.3;
2. embedding similarity >= 0.6;
3. within each column, edit similarity >= 90% of that column's maximum;
4. within the remaining candidates, embedding similarity >= 90% of that
   column's maximum;
5. preserve existing deterministic deduplication and caps.

Exact and substring matches no longer bypass embedding or relative filters.
Existing keyword and database indexes are reused, so rebuilding VE2 requires no
DeepSeek call.

## Prompt

`pro-t-direct-ve2` renders:

```
<unchanged CT-3 DDL + three sample rows>

<retrieved database context block>
```

`pro-t-direct-ve2-r` uses the same artifact, columns, descriptions, and number
of values, replacing only each relevant value with its deterministic same-column
control value.

The v1 models retain their old DDL-replacement behavior for reproducibility.
Trace metadata records the strategy and schema mode.

## Artifacts and experiment

VE2 writes a new fixed artifact:
`data/value_evidence/selections/archer_en_dev_chess_ir_v2.json`.
The first paid comparison is only:

- baseline: `pro-t-direct`;
- treatment: `pro-t-direct-ve2`;
- relevance control: `pro-t-direct-ve2-r`.

DSL and BIRD variants are deferred until Direct shows a positive signal.

