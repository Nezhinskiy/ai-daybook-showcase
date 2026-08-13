# 06 · Quality engineering

[← back to the overview](../README.md)

Testing an agent is not testing a function. The output is non-deterministic, the failure
modes are semantic rather than structural, and a suite that asserts on object shape will
pass while the product quietly gets worse.

Two layers answer that: a large deterministic suite that never calls a model, and an eval
corpus that does.

## The deterministic suite

**8,307 tests** — 7,599 Python and 708 frontend. Test code outweighs production Python
**1.71×** (282k lines against 165k).

The rule is that tests protect *behavior*, not shape. A tool test asserts the persisted row,
the `change_log` entry, and the user scoping — not the shape of the object the tool returned
on its way there. Routing tests use realistic mixed messages rather than one-domain
fixtures. Workflow tests include duplicate delivery.

Tiers, marked and run separately:

| Tier | What it covers |
|---|---|
| default | Fake LLM and fake Telegram. Fast, runs on every change. |
| `db` | Real Postgres: migrations, RLS, repositories, effect tools. |
| `temporal` | A real Temporal test server: workflows, timers, schedules, replay. |
| `llm` | A real model. Rare and deliberate. |

Static checking is doubled and covers the tests themselves: `mypy --strict` **and**
`pyright`, over `src` and `tests`. Typed Pydantic contracts sit at every workflow, activity,
and tool boundary — raw dicts are never passed down and re-parsed.

## The eval corpus

**338 cases across 11 agents**, exercised against **5 models** — `claude-sonnet-5`,
`claude-sonnet-4-6`, `claude-haiku-4-5`, `gpt-5.6-terra`, and `gpt-5.5` — with **45**
recorded result sets.

| Agent | Cases | | Agent | Cases |
|---|---|---|---|---|
| router | 92 | | journal | 24 |
| food | 55 | | inventory | 21 |
| planning | 34 | | faq | 14 |
| query | 29 | | profile | 9 |
| activity | 26 | | raw_events | 9 |
| raw_events_analyzer | 25 | | | |

The router carries the most cases because it is the one component whose mistakes are
invisible downstream: a fragment routed to the wrong domain produces a perfectly valid
record of the wrong kind.

### Deterministic evaluators, not a judge model

**52 purpose-built evaluators** score those cases — `ExpectedToolCalled`,
`ExactPlannedTools`, `OrderedPlannedTools`, `ToolCallCount`, `ToolListFieldExactGroups`,
`ToolStatusAbsent`, `ToolCallWindowsDisjoint`, `ReadToolCalled`, and so on.

This is a deliberate rejection of LLM-as-judge for the merge gate. A judge model gives you a
second non-deterministic system to debug, drifts silently between versions, and is most
likely to be wrong exactly where the case is hardest. A deterministic evaluator encodes the
*product contract*: these tools, in this order, with these fields, and not that status.

The governing rule is that an evaluator encodes what the product must do — never whichever
variant a model happened to emit. Assertions are stabilized before a real-model run, and are
never weakened to make a run pass.

### The gate

A structural eval check runs on every pull request. When an agent's behavior changes, its
suite re-runs against the live model at `--threshold 1.0` — a **strict single pass, no
retries** — before the change can merge.

No retries is the point. A gate that retries measures the best of N attempts, which is not
what a user gets. A flaky case is treated as a defect and root-caused: to the dataset, to
the prompt, to the code, or to a provider transient identified as such. It is never masked.

Real-model runs are also expensive, so the process around them is explicit: scope the run
before paying for it, and follow a cost-safe protocol for blocking runs. Reasoning from each
run is captured alongside the result, so a regression can be read rather than guessed at.

### A recorded run knows when it went stale

Every result set stores the model, `k`, the threshold, the case count, the timestamp — and
four content hashes: of the skill, the dataset, the **evaluation contract**, and the agent
code. Freshness is therefore computable rather than remembered: a run is stale the moment
any of those inputs moves, and the generated status page derives that instead of trusting a
date.

This matters more than it sounds. The failure mode it prevents is the one where a green
result from six weeks ago is quoted as evidence about code that has since changed
underneath it — which is how an eval suite turns into decoration. Hashing the *evaluation
contract* separately from the dataset is the load-bearing part: it distinguishes "we added
cases" from "we changed what passing means", and only the second invalidates a comparison
between two runs.

## Migration-first schema

`metadata.create_all()` is never used. **97 reviewed Alembic migrations**, each inspected
against the models before generation, with a migration-head guard in CI. Narrowing a `CHECK`
or an enum obliges `downgrade()` to purge what no longer fits — a downgrade that would fail
on real data is not a downgrade.

## How these were counted

Every figure in this repository comes from a command run at one pinned commit, `2c683ad5`:

| Metric | Value | Command |
|---|---|---|
| Python test functions | 7,599 | `git ls-files tests \| grep '\.py$' \| tr '\n' '\0' \| xargs -0 grep -hoE '^[[:space:]]*(async )?def test_' \| wc -l` |
| Frontend test cases | 708 | `grep -rhoE "^\s*(it\|test)\(" frontend/src \| wc -l` |
| Deterministic evaluators | 52 | `grep -cE "^class [A-Za-z]+\(Evaluator\)" src/app/evals/evaluators.py` |
| Eval cases | 338 | `grep -hcE "^  - " src/app/agents/skills/*/evals/dataset.yaml \| awk '{s+=$1} END {print s}'` |
| Durable workflows | 20 | `grep -rh '@workflow.defn' src/app/workflows/ \| wc -l` |
| Migrations | 97 | `ls -1 alembic/versions/*.py \| wc -l` |

Two rules, each of which has already produced a wrong number in this project once:

- Count over **tracked** files, with a POSIX character class rather than `\s`. `git grep -E`
  does not implement `\s` — it is a GNU extension — and undercounts by roughly 300.
- Measure at a pinned commit, never in a worktree. Uncommitted and branch-local files move a
  headline figure.

A number without its command is a boast. A number with one is evidence.

---

[← data model](05-data-model.md) · [next: operations →](07-operations.md)
