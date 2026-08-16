# 06 · Quality engineering

[← back to the overview](../README.md)

Testing an agent is not testing a function. The output is non-deterministic, the failure
modes are semantic rather than structural, and a suite that asserts on object shape will
pass while the product quietly gets worse.

Two layers answer that: a large deterministic suite that never calls a model, and an eval
corpus that does.

## The numbers on this page

Measured at commit `85d65d2d`, 2026-08-17. Every command is in
[how these were counted](#how-these-were-counted); every output is on the
[evidence page](EVIDENCE.md#1-the-counts-and-the-commands-that-produced-them).

| | |
|---|---|
| Tests | **8,881** — 8,146 Python test functions, 735 frontend |
| Default lane, actually run | **8,434 passed, 3 skipped, 84 s** (parametrization expands functions into items) |
| Test-to-production code | **1.78×** — 302k lines of tests against 170k of Python |
| Eval cases | **341** across 11 agents |
| Deterministic evaluators | **57** |
| Durable Temporal workflows | **20** |
| Alembic migrations | **97** |
| Ledger entries | **141** — 114 fixed, 18 open, 5 void, 3 partial, 1 rejected |

## The deterministic suite

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

**341 cases across 11 agents**, exercised against five models — `claude-sonnet-5`,
`claude-sonnet-4-6`, `claude-haiku-4-5`, `gpt-5.6-terra`, and `gpt-5.5` — reached through three
access lanes (`claude_cli`, `openrouter`, `codex_app_server`), which is what "provider" means
everywhere below.

That is 55 agent×model combinations; **40 are recorded and 15 have never been run**. The
gaps are deliberate and are printed as `never` rather than left blank: the cheapest model was
only ever scoped on the simplest agent, and the most recently added agents have not been run
against every provider. The blocking gate exercises the production model; the rest exist to
answer "would a cheaper or different model hold this contract", not to fill a grid.

| Agent | Cases | | Agent | Cases |
|---|---|---|---|---|
| router | 92 | | journal | 24 |
| food | 58 | | inventory | 21 |
| planning | 34 | | faq | 14 |
| query | 29 | | profile | 9 |
| activity | 26 | | raw_events | 9 |
| raw_events_analyzer | 25 | | | |

The router carries the most cases because it is the one component whose mistakes are
invisible downstream: a fragment routed to the wrong domain produces a perfectly valid
record of the wrong kind.

### Deterministic evaluators, not a judge model

**57 purpose-built evaluators** score those cases — `ExpectedToolCalled`,
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

What that costs, honestly: an eval run failing on a provider transient blocks a change that
is fine. The policy for that is a written procedure — probe the failing case in isolation at
higher `k`, and only call it a transient when the isolated run is clean — not a retry flag.
The [evidence page](EVIDENCE.md#6-a-production-defect-the-eval-suite-could-not-see) carries a
case where the same discipline caught an earlier flake attribution that had been *wrong*: a
failure recorded as a host-login race turned out, under a baseline probe, to be a real 3/5
prompt ambiguity.

Real-model runs are also expensive, so the process around them is explicit: scope the run
before paying for it, and follow a cost-safe protocol for blocking runs. Reasoning from each
run is captured alongside the result, so a regression can be read rather than guessed at.

### A recorded run knows when it went stale

Every result set stores the model, `k`, the threshold, the case count, the timestamp — and
content hashes of the skill, the dataset, the **evaluation contract**, and an execution
profile, plus an optional agent-code fingerprint. Freshness is computed from those rather than
remembered from a date.

Two different questions are answered by different subsets, and conflating them would
overstate what the status page proves:

| Question | What is compared |
|---|---|
| Is the generated status page's verdict `fresh` or `stale`? | skill content hash + dataset hash |
| May a stored result be **reused as gate evidence**? | skill version, skill content hash, dataset hash, and evaluation-contract hash — and the pass rate is recomputed from the recorded cases rather than read off the file |

The second is the stricter gate, and the recompute is the part that matters: a stored
`pass_rate` field is a claim, and the eligibility check declines to trust it.

Hashing the *evaluation contract* separately from the dataset is the load-bearing idea. It
distinguishes "we added cases" from "we changed what passing means", and only the second
invalidates a comparison between two runs. The skill hash is not naive either — it folds in
shared common fragments, and for the FAQ agent the shipped RAG corpus bytes, because a corpus
edit changes behavior while leaving every prompt file untouched.

**No averaged pass rate appears in this repository**, for the reason the mechanism above makes
precise: the recorded runs are snapshots at different dates, different `k`, and different
dataset versions, and 15 of the 55 agent×model cells have never been run. A matrix average
would be arithmetically real and evidentially meaningless. One current, hash-verified run is
worth more than that average, and [the evidence page publishes
it](EVIDENCE.md#9-the-current-strict-gate).

## Migration-first schema

`metadata.create_all()` is never used. **97 reviewed Alembic migrations**, each inspected
against the models before generation, with a migration-head guard in CI. Narrowing a `CHECK`
or an enum obliges `downgrade()` to purge what no longer fits, so the downgrade still runs
against data written under the wider constraint.

## How these were counted

Every figure in this repository comes from a command run at one pinned commit, `85d65d2d`.
The commands and their raw output are on the
[evidence page](EVIDENCE.md#1-the-counts-and-the-commands-that-produced-them):

| Metric | Value | Command |
|---|---|---|
| Python test functions | 8,146 | `git ls-files tests \| grep '\.py$' \| tr '\n' '\0' \| xargs -0 grep -hoE '^[[:space:]]*(async )?def test_' \| wc -l` |
| Frontend test cases | 735 | `grep -rhoE "^\s*(it\|test)\(" frontend/src \| wc -l` |
| Deterministic evaluators | 57 | `grep -cE "^class [A-Za-z]+\(Evaluator\)" src/app/evals/evaluators.py` |
| Eval cases | 341 | `grep -hcE "^  - " src/app/agents/skills/*/evals/dataset.yaml \| awk '{s+=$1} END {print s}'` |
| Durable workflows | 20 | `grep -rh '@workflow.defn' src/app/workflows/ \| wc -l` |
| Migrations | 97 | `ls -1 alembic/versions/*.py \| wc -l` |
| Ledger entries | 141 | `ls -1 docs/bugs/BR-*.md \| wc -l` |

Two rules, each of which has already produced a wrong number in this project once:

- Count over **tracked** files, with a POSIX character class rather than `\s`. `git grep -E`
  does not implement `\s` — it is a GNU extension — and undercounts by roughly 300.
- Measure at a pinned commit, never in a worktree. Uncommitted and branch-local files move a
  headline figure.

A number without its command is a boast.

---

[← data model](05-data-model.md) · [next: operations →](07-operations.md)
