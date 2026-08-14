# 03 · Durable execution

[← back to the overview](../README.md)

A reminder set for next month has to survive deploys, crashes, restarts, and a laptop
closing. A message that arrives twice must not log the meal twice. An LLM provider that
rate-limits at 2am must not turn into silence.

None of that is agent work, and none of it should be written by hand for each feature.
**Temporal owns every lifecycle**; the agents decide only what domain work means.

## Twenty workflows, one rule

Twenty `@workflow.defn` classes cover message handling, agent jobs, reminders, episode
derivation and interpretation, approvals, conversation summaries, Google OAuth completion,
inbound reconciliation, and outbound delivery reconciliation.

The rule they share: Temporal controls *when* work runs and guarantees that it eventually
does. It does not replace the agent, and the agent never manages its own retries, timers, or
recovery.

**Concurrency with ordering derived in code.** The four routes from one mixed message run
concurrently. Where one route depends on another's result — a task created, then an activity
linked to it — the ordering is computed deterministically and the identifier is handed off
between steps, rather than being inferred by a model or won by a race.

**Deterministic time.** `workflow.now()` supplies the timestamp, so a replayed workflow
computes the same subjective day it did originally. An agent reading the wall clock would
make replay non-deterministic, which is why agents receive time as a value rather than
fetching it.

## Idempotency at every boundary

Telegram redelivers. Networks retry. Deploys interrupt.

Every external ingress deduplicates by natural key, and every durable effect boundary
carries an idempotency key. A duplicate webhook resolves to the same persisted row rather
than a second one. This is enforced at the boundary rather than checked by the caller.

Every run, tool call, message, and outbound result is persisted. Telegram is a **mirror,
not a queue** — the work chat shows what happened, and deleting it changes nothing, because
the database is the source of truth.

## Failing loudly, never silently

Domain, router, vision, and summarizer calls each retry once on a backup provider when the
primary rate-limits or dies on auth. If no backup is usable, the failure is terminal — and
the user receives a deterministic, no-LLM notice.

That last clause is the design decision. The tempting alternative is to retry until
something works, which converts a five-second failure into a two-minute hang and then
usually still fails. The user experience of "the system is down, nothing was written" is
strictly better than silence, and it is generated without a model, so it works precisely
when models do not.

The same principle runs through the capability guard in [chapter 02](02-agent-architecture.md):
an out-of-bundle decision terminates rather than being repaired. A system that quietly
recovers from a violated invariant teaches you nothing about how often the invariant is
violated.

## When one route of four fails

The fan-out is deliberately **not atomic**. The run, the omelette, the reminder and the
inventory note are independent facts; losing three because the fourth failed is a worse
outcome than a partial day. Each route commits on its own, and a failed one is terminal for
itself alone.

The user is told, per route, rather than left to discover it: a failed effect ends
`failed_terminal`, the response projector takes its failed branch with no committed receipt,
and the reply says plainly that nothing was written for that fragment. Silence is the one
unacceptable outcome.

The harder failure is not a route that fails — it is a route that **succeeds wrongly**. A
fragment routed to the wrong domain produces a perfectly valid record of the wrong kind, and
nothing downstream can detect that, because every invariant it would violate belongs to the
domain it was never sent to. There is no runtime mitigation. The defence is entirely
upstream: the router carries by far the largest eval suite in the project — 92 of 339 cases
— and a reply to a mis-routed record routes back to the right agent with full context, so a
correction costs one message rather than a manual edit.

That asymmetry is why the router is the only agent forbidden to solve anything: every
capability it holds is a way for it to be wrong invisibly.

## What this costs

Every workflow must be deterministic and replay-safe. Contracts have to be complete at
import time — a forward reference resolved lazily breaks replay, which is a failure that
appears months later on a workflow you have forgotten. And "just call the API here" is often
simply not available.

That is the trade. Hand-written lifecycle code is cheaper to write and is the part that
fails at 2am.

---

[← agent architecture](02-agent-architecture.md) · [next: security →](04-security.md)
