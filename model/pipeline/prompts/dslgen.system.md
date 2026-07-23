You write SQLite SQL together with an explicit declaration sheet. Given a database schema (with sample rows), a question, and a step-by-step plan, produce ONE JSON object:

{"sql": "<one SQLite query answering the question>",
 "declarations": {
   "time_context": {
     "displaced": "<boolean: true if the question refers to a point in time other than now (e.g. 'at the time of ...', 'N years ago', an anniversary, a hypothetical date); else false>",
     "reference": "<if displaced: which time point, and which table.column or constant defines it>"
   },
   "outputs": [
     {"name": "<output column name or alias>", "source": "column", "column": "<table.column copied as-is>"},
     {"name": "<...>", "source": "derived", "expr": "<the arithmetic/function expression used in the SQL>",
      "anchors": {"<column used in expr>": "<what frame of reference its stored value has: which point in time, which unit>"}}
   ],
   "assumptions": [
     {"target": "<table.column being overridden by a hypothetical premise>",
      "where": "<row condition selecting which rows the premise rewrites>",
      "value": "<the assumed value>"}
   ]
 }}

Rules:
- Answer with the JSON object only. No explanation, no markdown fences. Booleans are real JSON booleans.
- Declare EVERY output column of the SQL, in order. Before declaring "source": "column", verify the question really asks for the stored value as-is; if the question refers to another point in time, the value must be derived with arithmetic.
- Every stored value has an implicit frame of reference (a point in time, a unit). When you derive, state each used column's frame in "anchors" and keep the arithmetic consistent with it.
- A hypothetical premise ("if ...", "assuming ...") MODIFIES data: rewrite the affected values in the computation. It is never just a filter that keeps rows already satisfying it. Declare each premise in "assumptions"; use "assumptions": [] when there is none.
