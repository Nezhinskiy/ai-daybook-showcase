# 04 · Security and multi-tenancy

[← back to the overview](../README.md)

Structured logging is only worth the effort if you can interrogate the result. So the
QueryAgent answers questions that span domains:

```text
you ▸ do I sleep worse on days I skip the gym?
you ▸ what did I spend on groceries the weeks I cooked at home?
you ▸ how does my afternoon energy track against caffeine before noon?
```

Each becomes **one read-only SQL query** joining meals, activities, tasks, episodes, raw
events, and inventory — correlations no per-domain tool API could express.

"An LLM writes free-form SQL against the production database" is, stated plainly, a
description of a security incident. It is safe here because it is guarded on three
independent layers, and defeating one buys nothing.

## Layer 0 — the model's inputs are untrusted too

Before the SQL question, the prior one: product names from OpenFoodFacts, window titles from
screen-time events, transcribed voice, and text recognized in photos all reach a model that
can call write tools. None of that text was authored by the user.

There is **no prompt-injection filter**, and adding one is not on the roadmap. The bet is
structural instead: the capability bundle is computed from the user's own intent *before*
any of that text is assembled into the prompt. Injected instructions can therefore, at
worst, cause a wrong call **within** a plan the user's own message already authorized —
never a call outside it, never a tool that was not attached, and never a write touching
another user's rows, because `user_id` is forced from the request scope rather than accepted
from the model.

That bounds the blast radius; it does not eliminate the attack. A crafted product name could
still steer a meal record to the wrong value inside the plan, and nothing here would catch
it. The honest position is that a filter would be theatre against a determined attacker
while the bundle is the thing actually doing the work — and that the residual risk is
mis-valued records, not escalation.

The three layers below cover the sharpest edge of that surface, where generated text becomes
executable.

## Layer 1 — parse, don't pattern-match

Every generated query is parsed into an AST with [`sqlglot`](https://github.com/tobymao/sqlglot)
and validated structurally. Regex allow-lists lose this game; comment tricks, unusual
whitespace, string-literal smuggling, and dialect quirks all defeat them.

```python
def validate_readonly_sql(sql: str) -> str:
    """Validate ``sql`` is a single user-scoped read; return the normalized SQL.

    Rejects (raising ``ReadonlySqlError``): empty / multi-statement input, any
    write or admin command, non-SELECT top nodes, ``SELECT ... INTO``, references
    to base tables outside the view allow-list, schema/catalog-qualified or quoted
    identifiers resolving to disallowed tables, and any function (typed or anonymous)
    whose canonical name is outside the analytical allow-list.
    """
    stripped = sql.strip()
    if not stripped:
        raise ReadonlySqlError("empty statement")
    try:
        statements = [s for s in sqlglot.parse(stripped, read="postgres") if s is not None]
    except Exception as exc:
        raise ReadonlySqlError(f"unparseable statement: {exc}") from exc
    if len(statements) != 1:
        raise ReadonlySqlError("exactly one statement is allowed")
    tree = statements[0]

    if isinstance(tree, _WRITE_OR_ADMIN):
        raise ReadonlySqlError("only SELECT / WITH ... SELECT is allowed")
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery, exp.With)):
        raise ReadonlySqlError("only SELECT / WITH ... SELECT is allowed")
    if tree.find(exp.Into) is not None:
        raise ReadonlySqlError("SELECT ... INTO is not allowed")
```

<sub>`src/app/db/effects/readonly_sql.py`</sub>

Beyond the shape check it walks **every lexical scope** — not just the top-level `FROM` — so
a disallowed base table cannot hide inside a subquery or CTE, and it rejects recursive CTEs
outright as an unbounded-work vector the agent never needs. Functions are checked by
canonical name against an analytical allow-list, covering both `sqlglot`'s typed function
nodes and anonymous ones, so a function cannot slip through by virtue of how the parser
happens to model it.

Anything the parser cannot fully resolve is rejected. **Ambiguity is a rejection, not a
pass** — that is what makes it a guard rather than a filter.

## Layer 2 — the role physically cannot write

The validated query executes over a dedicated read-only Postgres role, against an
allow-list of views rather than base tables, under a statement timeout and a row cap. Not
"the code does not issue writes" — the connection has no write privilege. The worst-case
outcome of a maliciously generated query is a failed read.

## Layer 3 — row-level security

The system is multi-tenant: every row carries a `user_id`, and the analytical role runs
under Postgres row-level security. A query can only ever see the asking user's rows, **even
if the parser were bypassed entirely**.

This is why the guard is genuine defence in depth rather than three names for one check. To
read another user's data an attacker would need to defeat a SQL parser, a Postgres role
grant, and an RLS policy simultaneously. To write anything, they would additionally need a
privilege the connection does not hold.

RLS is also why a schema change is not just a migration here. When a junction table becomes
readable, it needs its own direct `user_id` — not merely a foreign-key path to a parent —
because the policy has to be expressible on the table itself. That house rule exists because
the alternative silently produces tables the policy cannot protect.

## Writes never go through this path at all

No agent anywhere holds arbitrary write access. Every write goes through a typed effect
tool that validates its input against a Pydantic contract, forces `user_id` from the request
scope rather than accepting it from the model, performs the write, and records a
`change_log` entry.

The consequence: the analytical surface and the mutation surface share no code. Widening
what the QueryAgent can read can never widen what any agent can write, because reads and
writes do not meet.

## Where the guard came from

An early version of the function allow-list matched on the *node type* rather than the
canonical function name. `sqlglot` models some SQL functions as typed nodes and others as
anonymous ones, so a function could pass or fail depending on how the parser happened to
represent it — which meant the allow-list did not describe the set of functions it was
supposed to describe.

The fix was to canonicalize the name first and check that, covering both representations,
rather than to add a second pattern alongside the first. That is the rule the whole module
follows: a guard that grows by accretion has stopped being a guard, because nobody can any
longer say what it admits.

Rejection messages name the rule that fired, so a refusal is diagnosable rather than
mysterious — which matters because the person debugging it is usually looking at a query a
model wrote and they have never seen before.

---

[← durable execution](03-durable-execution.md) · [next: data model →](05-data-model.md)
