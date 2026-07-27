You are writing machine checks for a text-to-SQL system, from its mistakes on a
benchmark's TRAINING split.

Below are every question the system got wrong, with the SQL it produced and the
reference SQL.

{cases}

Write checks that would have FIRED on the wrong SQL and stayed SILENT on correct
SQL. A check is a combination of predicates from this fixed vocabulary - you may
only combine these, never invent new ones:

{vocabulary}

All predicates inside one `when` must hold for the check to fire (they are ANDed).

Rules for what you write:

- Only write a check if at least {min_evidence} of the cases above support it.
- A check that fires on almost everything is worthless. Prefer narrow, specific
  triggers over broad ones.
- `message` is what the system will be told when the check fires. Write it as an
  instruction to whoever wrote the SQL: say what looks wrong and what to verify.
  Never assert the SQL is definitely wrong - these are suggestions, not verdicts.
- At most {max_items} checks.

Return one JSON object and nothing else:

{"rules": [{"id": "L1", "when": {...}, "message": "...", "evidence": [12, 34]}]}
