<div align="center">

# ai-daybook

**A production life-logging system: eleven long-lived LLM agents on Temporal, where the model
gets exactly one decision per request — inside a boundary computed in advance by ordinary
code.**

[**▶ Live demo**](https://ai-daybook.cc/app/demo.html) · [**Evidence**](docs/EVIDENCE.md) · [**The code**](code/)

<sub>Demo runs on synthetic data and is built for a phone.</sub>

</div>

---

You text it the way you'd text a friend, and one message can carry four unrelated things:

```text
you ▸ morning run, 5k. then an omelette and coffee. remind me tomorrow
      at 9 to book the dentist — oh, and I'm out of whey protein

router ▸ 4 fragments · 4 domains · dispatched concurrently

   🏃 ActivityAgent   run · 5 km · morning            → activities
   🍳 FoodAgent       omelette + coffee ≈ 430 kcal    → meals (estimated, no questions)
   ⏰ PlanningAgent   "book dentist" tomorrow 09:00   → durable Temporal timer
   📦 InventoryAgent  whey protein → running low      → inventory
```

Four typed, audited, user-scoped database writes. No forms, no follow-up interrogation. It is
built for people with ADHD or autism, which is the reason the architecture looks the way it
does — [chapter 01](docs/01-product.md).

## Three claims, each with its proof

| Claim | Why it holds | See it run |
|---|---|---|
| **One LLM decision per request, pre-scoped.** An intent expands into a `CapabilityPlan` by pure code; an out-of-bundle call is `FAILED_TERMINAL` with no partial writes — checked against the *plan*, so "no partial writes" is structural rather than a rollback. | [chapter 02](docs/02-agent-architecture.md) | [the guard, exercised](docs/EVIDENCE.md#3-the-guard-exercised) |
| **An LLM writes free-form SQL against production, safely.** `sqlglot` AST validation, a role holding no write grant, and Postgres row-level security. Defeating any one of the three buys nothing. | [chapter 04](docs/04-security.md) | [the validator, exercised](docs/EVIDENCE.md#5-the-sql-validator-exercised) |
| **566 eval cases, 68 deterministic evaluators, no judge model, no retries.** The standard is k=5 with every attempt of every case passing; a flaky case is a defect to root-cause, never something to retry past. At this pin the current runs are a k=1 screen, not that gate, and the evidence page says so. | [chapter 06](docs/06-quality.md) | [a defect the evals could not see](docs/EVIDENCE.md#6-a-production-defect-the-eval-suite-could-not-see) · [what is current](docs/EVIDENCE.md#9-the-current-strict-gate) |

## Provenance

The implementation repository is private, so you cannot run these yourself. What you can do
is see which command produced each figure, at one pinned commit, and hold the two against each
other:

```console
$ python3 scripts/pytest_in_tree.py -m "not integration" -n 8 -q -p no:cacheprovider
17581 passed, 3 skipped in 595.99s (0:09:55)

$ git ls-files tests | grep '\.py$' | tr '\n' '\0' \
    | xargs -0 grep -hoE '^[[:space:]]*(async )?def test_' | wc -l
   15186
```

<sub>Two different things: 15,186 test *functions* in tracked files, 17,581 test *items* pytest
collects after parametrization in the lane that excludes the Postgres and Temporal tiers. The
run shared a loaded machine, so its wall time says nothing about the suite's speed.</sub>

[**docs/EVIDENCE.md**](docs/EVIDENCE.md) carries the rest as raw output: every count with its
command, one request traced from intent to written row, the guard and the SQL validator
rejecting real input, four defects unabridged, and what the system did in production when
last read.

[**code/**](code/) is the capability kernel itself — 1,270 lines of source and 2,240 of tests,
copied verbatim, readable in twenty minutes.

## Read on

If you read one thing, read [the evidence](docs/EVIDENCE.md). If you read two chapters, read
**02** and **06** — or **09** and **10** if what you are hiring for is the person who keeps a
codebase honest rather than the person who designs the agent loop.

| | |
|---|---|
| [01 · Product](docs/01-product.md) | Audience, use cases, and the UX decisions that carry them |
| **[02 · Agent architecture](docs/02-agent-architecture.md)** | The capability model and the fail-closed boundary |
| [03 · Durable execution](docs/03-durable-execution.md) | Temporal, idempotency, provider failover |
| [04 · Security](docs/04-security.md) | Guarded SQL, row-level security, typed effects |
| [05 · Data model](docs/05-data-model.md) | The lifelog schema, audit trail, derived episodes |
| **[06 · Quality](docs/06-quality.md)** | The eval gate, the test tiers, the counting rules |
| [07 · Operations](docs/07-operations.md) | Deploy, rollback, observability, cost ledger |
| [08 · Engineering process](docs/08-engineering-process.md) | How the work is directed and verified |
| [09 · Governance](docs/09-governance.md) | The rules the codebase enforces on itself |
| **[10 · Guards](docs/10-guards.md)** | Every automated check, and the incident behind each one |
| [11 · Roadmap](docs/11-roadmap.md) | What is shipped, and what deliberately is not |

<details>
<summary><b>Stack</b></summary>

| Layer | Choice |
|---|---|
| Language | Python 3.13, typed throughout (mypy with every function annotated, plus `pyright`, over source *and* tests) |
| Durable execution | [Temporal](https://temporal.io) |
| Agents | [LangGraph](https://github.com/langchain-ai/langgraph) + [PydanticAI](https://ai.pydantic.dev), inside Temporal activities |
| LLM providers | The Claude API through a pool of keys, with subscription-backed Claude via `claude_cli` as each role's fallback, and a backup provider on failure |
| API & admin | FastAPI, SQLAdmin |
| Persistence | PostgreSQL, async SQLAlchemy 2.0, Alembic |
| SQL guard | [`sqlglot`](https://github.com/tobymao/sqlglot) + Postgres row-level security |
| Messaging | aiogram, Telegram webhook |
| Mini App | React + Vite SPA, served by nginx |
| RAG | `fastembed`, local and in-memory |
| Integrations | Google Calendar, OpenFoodFacts, barcode decoding (`zxing-cpp`), voice transcription |
| Observability | Sentry (including `gen_ai` spans), Langfuse for cost and latency |
| Infra | Docker Compose, GHCR images, self-hosted deploy runner |

</details>

## Rights

A case study. The implementation repository is private; the files under [`code/`](code/) are
published for reading and no license to use them is granted. All rights reserved.
© 2026 Mikhail Nezhinsky · [mikhail.nezhinsky@gmail.com](mailto:mikhail.nezhinsky@gmail.com)

---

<sub>Snapshot of commit `4fc9ea5e`, 2026-10-26; the production figures are from an earlier read,
on 2026-08-17. The private repository has moved on since; figures here are not updated
continuously.</sub>
