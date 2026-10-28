# 03 · Durable execution

[← back to the overview](../README.md)

A reminder set for next month has to survive deploys, crashes, restarts, and a laptop
closing. A message that arrives twice must not log the meal twice. An LLM provider that
rate-limits at 2am must not turn into silence.

None of that is agent work, and none of it should be written by hand for each feature.
**Temporal owns every lifecycle**; the agents decide only what domain work means.

## Twenty-four workflows, one rule

Twenty-four `@workflow.defn` classes cover message handling, agent jobs, reminders, episode
derivation and interpretation, approvals and inline-question callbacks, conversation
summaries, Google OAuth completion, inbound and outbound delivery reconciliation, and the
background food work a user never waits on: emoji labelling of saved products, product-code
catalogue checks, and restating past records after a product's nutrition is corrected.

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

Router, domain, summarizer, and speech-to-text calls each retry once on a backup provider
when the primary rate-limits or dies on auth. If no backup is usable, the failure is
terminal — and the user receives a deterministic, no-LLM notice.

On the subscription-backed CLI provider, the three calls a user waits on (router, domain
decision, photo recognition) go one step further: a staggered race. A stalled turn looks
exactly like a slow one until it is too late to retry, so instead of running one attempt to
a fixed budget, a second attempt and then the backup provider start at set boundaries inside
one envelope, but only while every live attempt has gone silent; a turn that is visibly
working is never hedged. With no winner, the outcome is the primary's own error, never
whichever attempt finished last, so a hedge's failure cannot turn a retryable stall into a
terminal one.

A role on the direct Claude API is served by a pool of keys in a fixed order, with key health
shared across processes. A rate-limited or revoked key is marked and the same request repeats
on the next key; a pool with no healthy key hands the role to its subscription-backed
fallback, which then meets its own spend caps and backup like any other call.

That last clause is the design decision. The tempting alternative is to retry until
something works, which converts a five-second failure into a two-minute hang and then
usually still fails. The user experience of "the system is down, nothing was written" is
strictly better than silence, and it is generated without a model, so it works precisely
when models do not.

The same principle runs through the capability guard in [chapter 02](02-agent-architecture.md):
an out-of-bundle decision terminates rather than being repaired, so a violated invariant
shows up in the failure count instead of being absorbed.

## When one route of four fails

The fan-out is deliberately **not atomic**. The run, the omelette, the reminder and the
inventory note are independent facts; losing three because the fourth failed is a worse
outcome than a partial day. Each route commits on its own, and a failed one is terminal for
itself alone.

The user is told, per route, rather than left to discover it. A failed route gets its own
slot in the reply, built without a model from three typed fields: what failed, whether
resending would help, and what is known about that route's writes. That last field has three
values, because "nothing" is not always the honest answer: `some` is a fact (a committed effect row
cannot un-exist), `none` is only as strong as the claim transaction's snapshot, and `unknown`
is reserved for a claim that itself failed. Saying "nothing was saved" when something was is
worse than saying "unknown". Silence is the one unacceptable outcome.

The harder failure is not a route that fails — it is a route that **succeeds wrongly**. A
fragment routed to the wrong domain produces a perfectly valid record of the wrong kind, and
nothing downstream can detect that, because every invariant it would violate belongs to the
domain it was never sent to. There is no runtime mitigation. The defence is entirely
upstream: the router carries 138 of the project's 566 eval cases, a suite second only to
FoodAgent's, and a reply to a mis-routed record routes back to the right agent with full context, so a
correction costs one message rather than a manual edit.

That asymmetry is why the router is the only agent forbidden to solve anything: every
capability it holds is a way for it to be wrong invisibly.

## What this costs

Every workflow must be deterministic and replay-safe. Contracts have to be complete at
import time — a forward reference resolved lazily breaks replay, which is a failure that
appears months later on a workflow you have forgotten. And "just call the API here" is often
simply not available.

That is the trade, and it is worth naming as one: hand-written lifecycle code is cheaper to
write, and it is the code that fails during a deploy at an inconvenient hour.

---

[← agent architecture](02-agent-architecture.md) · [next: security →](04-security.md)
