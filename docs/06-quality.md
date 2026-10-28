# 06 · Quality engineering

[← back to the overview](../README.md)

Testing an agent is not testing a function. The output is non-deterministic, the failure
modes are semantic rather than structural, and a suite that asserts on object shape will
pass while the product quietly gets worse.

Two layers answer that: a large deterministic suite that never calls a model, and an eval
corpus that does.

## The numbers on this page

Measured at commit `4fc9ea5e`, 2026-10-26. Every command is in
[how these were counted](#how-these-were-counted); every output is on the
[evidence page](EVIDENCE.md#1-the-counts-and-the-commands-that-produced-them).

| | |
|---|---|
| Tests | **16,259** — 15,186 Python test functions, 1,073 frontend |
| Default lane, actually run | **17,581 passed, 3 skipped** (parametrization expands functions into items; the wall time was taken on a loaded machine, [see why it is not quoted](EVIDENCE.md#1-the-counts-and-the-commands-that-produced-them)) |
| Test-to-production code | **2.11×** — 566k lines of tests against 268k of Python |
| Eval cases | **566** across 11 agents |
| Deterministic evaluators | **68** |
| Durable Temporal workflows | **24** |
| Alembic migrations | **143** |
| Bug ledger entries | **436** — 321 fixed, 84 open, 19 partial, 6 void, 6 rejected |
| Debt ledger entries | **469** — 278 open, 172 done, 19 dropped |

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

Static checking is doubled and covers the tests themselves: mypy, configured so that every
function must be annotated and untyped bodies are still checked (`disallow_untyped_defs`,
`check_untyped_defs`), **and** `pyright`, both run over `src` and `tests` in CI. Typed
Pydantic contracts sit at every workflow, activity, and tool boundary — raw dicts are never
passed down and re-parsed.

## The eval corpus

**566 cases across 11 agents**, recorded against six models: `claude-sonnet-5-5`,
`claude-sonnet-5`, `claude-sonnet-4-6`, `claude-haiku-4-5`, `gpt-5.6-terra` and `gpt-5.5`.
They are reached through four access lanes, which is what "provider" means everywhere below:
`anthropic` (the Claude API, which production now uses), `claude_cli` (the Claude
subscription, production's fallback), `codex_app_server`, and `openrouter`, which is tracked
but has never been run.

The status page has 77 agent×model cells: **62 recorded and 15 never run**. It tracks four
provider:model pairs for every agent and adds any other model that has a stored result. The
gaps are deliberate and are printed as `never` rather than left blank. OpenRouter accounts
for 11 of them, because it was never run on any agent. `gpt-5.5` was never run on the four
most recently added agents, and the cheapest model was only ever scoped on the simplest
agent. Only the production model's rows can be current evidence. The rest exist to answer
"would a cheaper or different model hold this contract", not to fill a grid.

| Agent | Cases | | Agent | Cases |
|---|---|---|---|---|
| food | 163 | | raw_events_analyzer | 28 |
| router | 138 | | journal | 25 |
| query | 56 | | faq | 17 |
| planning | 44 | | profile | 16 |
| activity | 39 | | raw_events | 9 |
| inventory | 31 | | | |

FoodAgent now carries the most cases, 163, because it has the widest product surface. The
router comes second, with 138, because it is the one component whose mistakes are invisible
downstream: a fragment routed to the wrong domain produces a perfectly valid record of the
wrong kind.

### Deterministic evaluators, not a judge model

**68 purpose-built evaluators** score those cases — `ExpectedToolCalled`,
`ExactPlannedTools`, `OrderedPlannedTools`, `ToolCallCount`, `ToolListFieldExactGroups`,
`ToolStatusAbsent`, `ToolCallWindowsDisjoint`, `ReadToolCalled`, and so on.

This is a deliberate rejection of LLM-as-judge for the eval gate. A judge model gives you a
second non-deterministic system to debug, drifts silently between versions, and is most
likely to be wrong exactly where the case is hardest. A deterministic evaluator encodes the
*product contract*: these tools, in this order, with these fields, and not that status.

The governing rule is that an evaluator encodes what the product must do — never whichever
variant a model happened to emit. Assertions are stabilized before a real-model run, and are
never weakened to make a run pass.

### The gate

A structural eval check runs on every pull request. A real-model run is a local rule, not a
CI step: when an agent's behavior changes, its suite is run against the live model before the
change is pushed. The CI job that would do this on `main` is switched off for cost. The
standard a run is held to is **k=5 with every attempt of every case passing**. The
eligibility check enforces it (`--required-k 5 --floor 1.0`) and recomputes the result from
the recorded cases.

No retries is the point. A gate that retries measures the best of N attempts, which is not
what a user gets. Attempts may be accumulated across invocations (1 + 1 + 3 reaches five), but
none is discarded. A failed attempt stays counted until a journaled repair replaces it, and
the status page shows that repair in the `k` column. A flaky case is treated as a defect and
root-caused: to the dataset, to the prompt, to the code, or to a provider transient identified
as such. It is never masked.

What that costs, honestly: an eval run failing on a provider transient blocks a change that
is fine. The policy for that is a written procedure — probe the failing case in isolation at
higher `k`, and only call it a transient when the isolated run is clean — not a retry flag.
The [evidence page](EVIDENCE.md#6-a-production-defect-the-eval-suite-could-not-see) carries a
case where the same discipline caught an earlier flake attribution that had been *wrong*: a
failure recorded as a host-login race turned out, under a baseline probe, to be a real 3/5
prompt ambiguity.

Real-model runs are also expensive, and on the production lane they are now billed per token,
so the process around them is explicit. Each run is scoped before it is paid for, a guard
refuses an unscoped run, a run of every agent at once, and any single run above `--k 4`, and
blocking runs follow a cost-safe protocol. Reasoning from each run is captured alongside the
result, so a regression can be read rather than guessed at.

### A recorded run knows when it went stale

Every result set stores the model, `k`, the threshold, the case count and the timestamp. It
also stores content hashes of the skill, the dataset, the **evaluation contract** and the
execution profile, and seven identity hashes that split what a run depended on into the eval
harness, the shared agent runtime, the agent's own domain code, the prompt surface, the cases,
the evaluators, and the evaluators' dependencies. Freshness is computed from those rather than
remembered from a date.

Two different questions are answered by different subsets, and conflating them would
overstate what the status page proves:

| Question | What is compared |
|---|---|
| Is the generated status page's verdict `fresh` or `stale`? | skill version + the seven identity hashes, reconciled; the flat skill and dataset hashes now only choose the words of a refusal (`stale: prompt`, `stale: code`, …). The execution profile is deliberately not compared. |
| May a stored result be **reused as gate evidence**? | everything above, plus the dataset hash, the evaluation-contract hash, the exact ordered case names and each case's assertion keys, `k` against the required minimum, and every case and every assertion against the floor. The pass rate is recomputed from the recorded cases rather than read off the file. |

The second is the stricter gate, and the recompute is the part that matters: a stored
`pass_rate` field is a claim, and the eligibility check declines to trust it.

The load-bearing idea is in what may be excused. A change can be attested as
behavior-neutral, and the evidence kept, if it touches the harness, the runtime, the domain
code or the prompt. Such a row reads `fresh (levelled)`, never plain `fresh`. A change to what
a case expects or to how it is judged can never be excused, and it always costs a re-run. The
skill hash is not naive either — it folds in
shared common fragments, and for the FAQ agent the shipped RAG corpus bytes, because a corpus
edit changes behavior while leaving every prompt file untouched.

**No averaged pass rate appears in this repository**, for the reason the mechanism above makes
precise: the recorded runs are snapshots at different dates, different `k`, and different
dataset versions, and 15 of the 77 agent×model cells have never been run. A matrix average
would be arithmetically real and evidentially meaningless. One current, hash-verified run is
worth more than that average, and [the evidence page publishes what is
current](EVIDENCE.md#9-the-current-strict-gate). At this pin that is a k=1 screen on the
production lane, not a strict gate, and the page says so.

## Migration-first schema

`metadata.create_all()` is never used. **143 reviewed Alembic migrations**, each inspected
against the models before generation, with a migration-head guard in CI. Narrowing a `CHECK`
or an enum obliges `downgrade()` to purge what no longer fits, so the downgrade still runs
against data written under the wider constraint.

## How these were counted

Every figure in this repository comes from a command run at one pinned commit, `4fc9ea5e`,
with one exception: the production read in [evidence §8](EVIDENCE.md#8-production), taken on
2026-08-17 and not repeated. The commands and their raw output are on the
[evidence page](EVIDENCE.md#1-the-counts-and-the-commands-that-produced-them):

| Metric | Value | Command |
|---|---|---|
| Python test functions | 15,186 | `git ls-files tests \| grep '\.py$' \| tr '\n' '\0' \| xargs -0 grep -hoE '^[[:space:]]*(async )?def test_' \| wc -l` |
| Frontend test cases | 1,073 | `grep -rhoE "^\s*(it\|test)\(" frontend/src \| wc -l` |
| Deterministic evaluators | 68 | `git ls-files src/app/evals/evaluators \| grep '\.py$' \| tr '\n' '\0' \| xargs -0 grep -hcE "^class [A-Za-z]+\(Evaluator\)" \| awk '{s+=$1} END {print s}'` |
| Eval cases | 566 | `grep -hcE "^  - " src/app/agents/skills/*/evals/dataset.yaml \| awk '{s+=$1} END {print s}'` |
| Durable workflows | 24 | `grep -rh '@workflow.defn' src/app/workflows/ \| wc -l` |
| Migrations | 143 | `ls -1 alembic/versions/*.py \| wc -l` |
| Design and plan documents | 305 | `ls -1 docs/specs/*.md docs/plans/*.md \| wc -l` |
| Bug ledger entries | 436 | `ls -1 docs/bugs/BR-*.md \| wc -l` |
| Debt ledger entries | 469 | `ls -1 docs/debt/TD-*.md \| wc -l` |

Two commands changed since the previous pin because files moved: the evaluators module became
a package, and specs and plans moved out of `docs/superpowers/`. The evidence page shows
both, and that the evaluator command still gives the old figure at the old pin.

Two rules, each of which has already produced a wrong number in this project once:

- Count over **tracked** files, with a POSIX character class rather than `\s`. `git grep -E`
  does not implement `\s` — it is a GNU extension — and undercounts by roughly 300.
- Measure at a pinned commit on a clean tree, never on a working branch. Uncommitted and
  branch-local files move a headline figure.

A number without its command is a boast.

---

[← data model](05-data-model.md) · [next: operations →](07-operations.md)
