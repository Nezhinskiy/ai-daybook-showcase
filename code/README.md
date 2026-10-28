# The capability kernel, verbatim

[← back to the overview](../README.md)

These are unmodified files from the private repository — the part of it that is actually
novel. Everything else the system does (Temporal workflows, SQLAlchemy repositories, a React
SPA) is competent but conventional, and reading it would tell you nothing you do not already
know.

**3,510 lines: 1,270 of source, 2,240 of tests.** Twenty minutes end to end.

## What to read, in order

| File | Lines | What it establishes |
|---|---|---|
| [`plan.py`](src/app/agents/capability/plan.py) | 15 | The whole contract between code and model. Read this first — it is the entire interface the LLM is allowed to act inside. |
| [`model.py`](src/app/agents/capability/model.py) | 126 | `Action`, `Capability`, `IntentBundle` as frozen dataclasses. Note `omit_universal_actions` on `IntentBundle`: opting out of the universal actions is a property of the bundle object, not a special case in the guard. |
| [`registry.py`](src/app/agents/capability/registry.py) | 219 | The intent → bundle table. The only place a capability is composed. |
| [`expand.py`](src/app/agents/capability/expand.py) | 139 | Pure code. Intent in, `CapabilityPlan` out, no model involved. The universal actions (today only `ask_user`) are appended to every plan here, so no bundle lists them; an unknown intent expands to a plan carrying only those rather than raising. |
| [`resolve.py`](src/app/agents/capability/resolve.py) | 175 | Rehydration into typed objects — and `resolved_plan_scope_mismatch`, which re-derives the canonical plan and compares it field by field against the one actually in hand. |
| [`guard.py`](src/app/agents/common/guard.py) | 43 | The fail-closed barrier. It admits exactly the action kinds and effect tools the plan carries, with no second allow-list beside it. Forty-three lines is the point: the work was done upstream. |
| [`readonly_sql.py`](src/app/db/effects/readonly_sql.py) | 507 | The `sqlglot` AST validator that lets a model write free-form SQL against production. |

Tests: [`test_resolve_plan.py`](tests/agents/capability/test_resolve_plan.py) (185),
[`test_common_guard.py`](tests/agents/common/test_common_guard.py) (127),
[`test_readonly_sql.py`](tests/db/effects/test_readonly_sql.py) (1,928).

The SQL validator carries 3.8× its own size in tests because it is the one component where a
miss is an incident rather than a defect.

## Three things worth noticing while you read

**`plan.py` is fifteen lines.** A `CapabilityPlan` is seven lists of strings. It is
serializable, diffable, loggable, and assertable in a test — which is why the boundary can be
checked at all. An object graph that had to be reconstructed to be compared would not be.

**`_function_name` in `readonly_sql.py` (line 293).** sqlglot models a recognized function as
a typed node exposing `sql_name()`, and an unrecognized one as `exp.Anonymous` carrying the
raw name in `.this`. `Anonymous.sql_name()` returns the literal string `"ANONYMOUS"`. Keying
the allow-list off `sql_name()` alone would therefore admit *every unrecognized function under
one key* — `pg_read_file`, `version`, anything — the moment `"anonymous"` appeared in the set.
The two-branch resolution is not defensive style; without it the allow-list admits everything
it does not recognize.

**`resolved_plan_scope_mismatch` ends with a `model_dump` comparison.** Every field is checked
explicitly first, and then the serialized plans are compared anyway. The specific checks
produce a diagnosable error string; the final one catches drift that no specific check
anticipated — a reordered list, a newly added `CapabilityPlan` field.

## What is missing here

The intent bundles reference actions, read tools, context blocks, and skill fragments that
live outside this excerpt, so this directory does not run standalone — it is for reading, not
for importing. `registry.py` shows the composition; the domain implementations it composes are
not included.

---

<sub>Copied verbatim from the private repository at commit `4fc9ea5e`, 2026-10-26.</sub>
