# 07 · Operations

[← back to the overview](../README.md)

This runs in production on a single droplet, deployed by a self-hosted runner. It is small
infrastructure, which is exactly why the failure modes had to be designed rather than
absorbed by redundancy.

## What it actually does, measured

Read from the production database on 2026-08-17. Small numbers, stated precisely — a
portfolio that says "a group of beta users" is hiding something, and the interesting claims
here do not depend on scale. Queries and raw output: [evidence
§8](EVIDENCE.md#8-production).

| | |
|---|---|
| Users | 14 registered · 13 have sent a message · **4 sustained** (≥5 active days) |
| Period | 2026-06-19 → 2026-08-16, **51 active days** |
| Messages processed | **538** inbound |
| Agent runs | **592** — 545 succeeded, 30 needs-user, 17 terminal (6 guard, 3 other errors, 1 backfill, 7 unattributed) |
| Effect-tool calls | **836** |
| Records written | 317 meals · 259 activities · 210 episodes · 13 tasks |
| Automated capture | **2,670 raw events → 210 episodes** — a 12.7:1 collapse, all evidence-backed |
| Corrections | **225** `change_log` entries against 317 meals |
| End-to-end reply latency | **p50 16.0 s · p90 57.3 s · p95 79.9 s** (n=384, inbound → reply sent) |
| Capability-guard rejections | **6** — all `empty_actions`; **0** out-of-bundle |

Three of those deserve comment rather than celebration.

**The latency is the honest weak point.** Fifteen seconds to a median reply is slow for
something that feels like a chat. The cause is structural and known: the router is on the
critical path for *every* message, so the floor is two sequential model calls plus tool
execution before a word comes back. That is precisely the cost
[deterministic evidence orchestration](10-roadmap.md#direction) is designed to remove — the
roadmap item exists because of this number, not the other way round.

**The correction rate is the encouraging one.** 225 corrections against 317 meals means
users routinely fix what the estimate got wrong, which is exactly the intended loop: log
imprecisely and instantly, refine later. A low correction count would have meant the audit
trail was decoration.

**The guard's rejections split unevenly, and the split is the interesting part.** The
out-of-bundle barriers — an action or an effect tool outside the plan — have fired **zero**
times in 592 runs. The empty-plan barrier fired **six**, none since 2026-07-15, and the last
of them is the trace recorded as BR-027: a model that answered a user's counter-question
helpfully, in prose, with no action to carry it. The guard was right about the shape and the
schema was wrong about what a decision could be; the fix routed a question-shaped
message-only decision onto `ask_user` rather than relaxing the barrier. [Full trace and
numbers](EVIDENCE.md#8-production).

Zero on the scope barriers, three months in, means production traffic is not what validates
them. Their correctness rests on unit tests and a 56-entry snapshot corpus over every
intent's expanded bundle, which is why [chapter 06](06-quality.md) names those rather than
leaving them implicit.

## What breaks first at 100×

One droplet, one Postgres, one worker pool. The binding constraint is not any of them — it
is the **provider rate limit** on the subscription-backed decision path, which is shared
across all users and does not scale by adding hardware. Past that, the next wall is the
router being a mandatory serial hop, then Postgres connection ceilings under the concurrent
per-route fan-out. Nothing here needs sharding before it needs a second provider lane.

## Deploy and rollback

Images are built to GHCR and deployed through a self-hosted GitHub Actions runner. Rollback
is a documented procedure rather than an improvisation, and destructive migrations run
through a separate manually-approved path with a quiesce, backup, and restore rehearsal —
never as an ordinary auto-deploy.

Two guards worth naming, because both exist for reasons that already happened:

**The drain guard.** A deploy refuses to start while episodes are live, rather than
interrupting an in-flight interpretation and leaving a partially derived episode behind.

**Push cancellation.** Pushing to `main` twice cancels the first in-flight deploy. Knowing
that is the difference between "the deploy is slow" and "the deploy you are watching was
superseded ten minutes ago".

A schema change that narrows a constraint deploys quiesced — the API and worker stop, the
migration runs, and they restart on the new image — and rolls back downgrade-first, because
Postgres refuses to drop a column an RLS policy depends on.

## Observability

**Sentry** for errors, tracing, and `gen_ai` spans across API and worker. **Langfuse** for
LLM cost and latency, attributed per call site, backed by a durable per-user spend ledger
with quota scaffolding.

One deliberate gap, stated because it matters more than the tooling list: Sentry today
*captures*; it does not alert. Code-defined monitors are on the roadmap rather than shipped.

A second, sharper gap was found by reading production rather than dashboards: an effect that
ends in `failed_terminal` is an ordinary receipt failure, not an exception, so an entire
class of user-visible defect — the write that silently does not happen — is **invisible to
error monitoring by construction**. That is a limit of the approach, not a bug in the
configuration, and it is why production reads go through the database and Langfuse traces
rather than stopping at Sentry.

## Reading production safely

Production observability has a fixed entry point — scripted, not ad-hoc `curl` and never by
opening environment files. Event bodies and trace inputs and outputs are excluded by
default and require an explicit request, so routine debugging does not casually page through
someone's private log.

The standing constraint above all of it: production user data is not a test fixture.

## Cost control

The interesting answer here is a design decision, not a dashboard.

The interactive decision provider is **subscription-backed rather than metered**. The
consequence is that the marginal LLM cost of one more message is zero, and the per-user cost
curve is flat until the subscription's rate limit binds — which is why that limit, not
money, is the scaling constraint named above. The per-user spend ledger exists and is
**empty**, because the primary path emits nothing to meter. Only the metered lanes — the
backup provider on failover, vision, and transcription — cost per call.

That is a deliberate trade: predictable cost and no per-message billing surprise, paid for
with a shared rate limit and a mandatory failover path. It is the right trade at four
sustained users and would be the wrong one at four thousand, at which point the ledger has to
carry real quota enforcement rather than sit ready for it.

Eval runs against real models are therefore the largest discretionary spend in the project,
which is why [chapter 06](06-quality.md) treats scoping a run before paying for it as part
of the process rather than an afterthought.

---

[← quality](06-quality.md) · [next: engineering process →](08-engineering-process.md)
