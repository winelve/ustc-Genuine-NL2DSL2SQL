You are selecting the better of two SQLite queries for one text-to-SQL
question. You must choose Candidate A or Candidate B. Never write a new SQL.

Derive the output contract from the question and external knowledge, then
compare both candidates. Check all of these:

1. requested output columns and aliases;
2. aggregation, arithmetic, CASE expressions, and derived formulas;
3. filters, literal values, and entity scope;
4. joins and join keys;
5. GROUP BY and HAVING;
6. ordering, top-k, and LIMIT;
7. temporal constraints;
8. definitions supplied by the external knowledge.

Execution summaries are diagnostic only. A non-empty result is not
automatically correct. Use `low` confidence when neither candidate has a
concrete semantic advantage.

Database schema:
{schema}

Question:
{question}

External knowledge:
{evidence}

Candidate A:
{candidate_a}

Candidate A execution summary:
{summary_a}

Candidate B:
{candidate_b}

Candidate B execution summary:
{summary_b}

Return exactly one JSON object and no Markdown:
{"winner":"A","confidence":"high","violations_a":[],"violations_b":["specific contract violation"],"reason":"one concise comparison"}

`winner` must be `A` or `B`. `confidence` must be `high`, `medium`, or `low`.
