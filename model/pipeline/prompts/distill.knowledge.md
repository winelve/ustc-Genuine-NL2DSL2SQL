You are auditing a text-to-SQL system's mistakes on a benchmark's TRAINING split.

Below are every question the system got wrong, with the SQL it produced and the
reference SQL. Find the patterns that recur across MULTIPLE cases, and write each
one as a single general statement that would have prevented the mistake.

{cases}

Rules for what you write:

- One sentence per item, in English, stating a general convention or reading rule.
- NEVER name a table, a column, or a value from any database. Write the rule so it
  applies to any schema. An item naming a column will be rejected outright.
- Only write an item if at least {min_evidence} of the cases above support it. List
  the case numbers as evidence.
- At most {max_items} items. Fewer is better - prefer the patterns with the most
  supporting cases.
- Do not restate things any competent SQL writer already does. Write only what this
  benchmark decides differently from the obvious reading.

Return one JSON object and nothing else:

{"items": [{"id": "D1", "text": "...", "evidence": [12, 34, 56]}]}
