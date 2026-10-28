# 07 · Operations

[← back to the overview](../README.md)

This runs in production on a single droplet, deployed by a self-hosted runner. It is small
infrastructure, which is exactly why the failure modes had to be designed rather than
absorbed by redundancy.

## What it actually does, measured

Read from the production database on 2026-10-28. Small numbers, stated precisely — a
portfolio that says "a group of beta users" is hiding something, and the interesting claims
here do not depend on scale. Queries and raw output: [evidence
§8](EVIDENCE.md#8-production).

| | |
|---|---|
| Users | 20 registered · 19 have sent a message · **5 sustained** (≥5 active days); since 2026-08-17, 9 wrote and 2 sustained |
| Period | 2026-06-19 → 2026-10-27, **99 active days** |
| Messages processed | **730** inbound |
| Agent runs | **945** — 862 succeeded, 52 needs-user, 31 terminal (6 guard, 7 other errors, 18 with no error code) |
| Effect-tool calls | **1,221** |
| Records written | 371 meals · 505 activities · 422 episodes · 24 tasks |
| Automated capture | **7,787 raw events → 422 episodes** — an 18.5:1 collapse, every episode citing the raw events behind it |
| Corrections | **460** audited `change_log` entries — 227 on saved products' nutrition, 45 on meals |
| End-to-end reply latency | **p50 19.2 s · p90 57.8 s · p95 82.1 s** (n=576, inbound → first reply sent); p50 22.9 s since 2026-08-17 |
| Capability-guard rejections | **6** — all `empty_actions`, none since 2026-07-15; **0** out-of-bundle |

Three of those deserve comment rather than celebration.

**The latency is the honest weak point.** Nineteen seconds to a median reply, and
twenty-three over the last ten weeks, is slow for something that feels like a chat. The cause is structural and known: the router is on the
critical path for *every* message, so the floor is two sequential model calls plus tool
execution before a word comes back. That is precisely the cost
[deterministic evidence orchestration](11-roadmap.md#direction) is designed to remove — the
roadmap item exists because of this number, not the other way round.

**The corrections are not where the previous revision of this page put them.** It read 225
`change_log` entries against 317 meals as users fixing meal estimates. Grouped by entity, only
31 of those 225 touched a meal; today 45 of 460 do. The largest share, 227, edits the nutrition
of a saved product, and the rest spread over inventory, profile, screen-category rules and
recipe batches. The intended loop holds, log imprecisely and refine later, but the refinement
mostly lands on the reusable product rather than on one meal. The earlier sentence compared a
total with the wrong denominator; it is corrected here rather than quietly replaced.

**The guard's rejections split unevenly, and the split is the interesting part.** The
out-of-bundle barriers — an action or an effect tool outside the plan — have fired **zero**
times in 945 runs. The empty-plan barrier fired **six**, none since 2026-07-15, and the last
of them is the trace recorded as BR-027: a model that answered a user's counter-question
helpfully, in prose, with no action to carry it. The guard was right about the shape and the
schema was wrong about what a decision could be; the fix routed a question-shaped
message-only decision onto `ask_user` rather than relaxing the barrier. [Full trace and
numbers](EVIDENCE.md#8-production).

Zero on the scope barriers, four months in, means production traffic is not what validates
them. Their correctness rests on unit tests and a 58-entry snapshot corpus over every
intent's expanded bundle, which is why [chapter 06](06-quality.md) names those rather than
leaving them implicit.

## What breaks first at 100×

One droplet, one Postgres, one worker pool. The binding constraint is not any of them — it
is **model capacity and its price**. The decision path now runs on a pool of Claude API keys:
the first healthy key serves, a rate-limited or exhausted key is marked in shared state and
the same request moves to the next one, and keys from separate organisations add capacity.
That turns a fixed wall into a bill: capacity can be bought, and spend grows linearly with
traffic. Past that, the next wall is the router being a mandatory serial hop, then Postgres
connection ceilings under the concurrent per-route fan-out. Nothing here needs sharding
before it needs per-user quota enforcement, which is the gap named under
[cost control](#cost-control).

## Deploy and rollback

Images are built to GHCR as immutable per-commit tags and deployed through a self-hosted
GitHub Actions runner on the droplet. Every backend deploy is one ordered script: a
pre-migration database backup, image pull, the writers stopped, a second open-workflow check,
the migration, startup on the new image, and a readiness smoke. A committed release manifest
can suspend ordinary deploys across a boundary that needs a hand-run sequence, and a
separate manually dispatched workflow carries the one-off operations — read-only diagnosis,
an emergency provider cutover and its revert, requeueing stuck messages, break-glass
termination of a wedged workflow. Rollback is a documented procedure rather than an
improvisation.

Two guards worth naming, because both exist for reasons that already happened:

**The drain guard.** A deploy refuses to start while any execution of the checked Temporal
workflow types — message turns, agent jobs, episodes, button callbacks — is still running,
and checks again after the writers stop, so nothing can start in between. A history recorded
by the old code would otherwise replay against the new code and fail on a workflow nobody is
watching.

**Push cancellation.** Pushing to `main` twice cancels the first in-flight deploy. Knowing
that is the difference between "the deploy is slow" and "the deploy you are watching was
superseded ten minutes ago".

Rollback goes downgrade-first whenever the target image is older than the database: the old
image's migrator cannot find a revision it does not contain, and fails with the writers
already stopped. For one RLS-bearing migration the order is stricter still, because Postgres
refuses to drop a column a policy depends on until the downgrade has removed the policy.

**Rollback floors.** Some releases write data the previous build cannot decode. Rather than
ship a reader-first release in front of each one, the runbook names a **rollback floor** — the
oldest build a rollback may target — and states what a forced rollback below it would cost.
That choice is priced, not defaulted: at the measured scale an extra release and acceptance
cycle to protect a day of interactive cards was judged not worth it, under the rule recorded
as [ADR-0006](09-governance.md#six-adrs-and-what-they-are-for).

## Observability

**Sentry** for errors, tracing, structured logs, and `gen_ai` spans across API and worker.
**Langfuse** for LLM cost and latency, attributed per call site, backed by a durable per-user
spend ledger. Provider-health transitions — the CLI circuit opening, the key pool running
dry and recovering — are emitted as events with stable fingerprints, and keys are named by a
hash prefix, never by value.

One deliberate gap, stated because it matters more than the tooling list: Sentry today
*captures*; it does not alert. The fingerprints exist so an alert can be attached without a
code change, but no alert rule is shipped, and code-defined monitors are on the roadmap
rather than in production.

A second, sharper gap was found by reading production rather than dashboards: an effect that
ends in `failed_terminal` is an ordinary receipt failure, not an exception, so an entire
class of user-visible defect — the write that silently does not happen — is **invisible to
error monitoring by construction**. That is a limit of the approach, not a bug in the
configuration, and it is why production reads go through the database and Langfuse traces
rather than stopping at Sentry. Later failure-legibility work added bounded, text-free log
events for a failed route and a degraded context block, which makes the class readable in
the logs; it does not make it an alert.

## Reading production safely

Production observability has a fixed entry point — scripted, not ad-hoc `curl` and never by
opening environment files. Sentry event bodies, Sentry log attribute values, and Langfuse
trace inputs and outputs are excluded by default and require an explicit request, so routine
debugging does not casually page through someone's private log.

The standing constraint above all of it: production user data is not a test fixture.

## Cost control

The interesting answer here is a design decision, not a dashboard — and it has changed.

For most of the project the interactive decision provider was **subscription-backed rather
than metered**: the marginal LLM cost of one more message was zero, the per-user ledger sat
empty because the primary path emitted nothing to meter, and the subscription's shared rate
limit was the scaling constraint. Production's committed configuration now puts the decision,
vision and summarizer roles on the **metered Claude API key pool**, with the subscription CLI
as each role's fallback when no key can serve. The trade reversed: capacity can be bought,
and every message has a price.

What keeps that bounded:

- **The fallback has its own brakes.** The CLI path carries a kill switch and a global monthly
  cap read from the persisted spend ledger, so a run of pool exhaustion cannot quietly move
  unlimited traffic onto it. The cap survives restarts and deploys.
- **Spend is recorded per turn, per user,** priced at list rates with cache reads and writes
  separated.
- **Per-user quota enforcement is built and not wired.** The gate exists with tests and has
  no production call site, and neither does the cross-check of the ledger against Langfuse;
  wiring or deleting both is one open debt entry. At this scale that is a deliberate
  deferral; at a few thousand users it is the first thing that has to change.

Eval runs against real models remain the largest discretionary spend in the project, which
is why [chapter 06](06-quality.md) treats scoping a run before paying for it as part
of the process rather than an afterthought.

---

[← quality](06-quality.md) · [next: engineering process →](08-engineering-process.md)
