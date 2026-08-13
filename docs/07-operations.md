# 07 · Operations

[← back to the overview](../README.md)

This runs in production for a small group of beta users, on a single droplet, deployed by a
self-hosted runner. It is small infrastructure, which is exactly why the failure modes had
to be designed rather than absorbed by redundancy.

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
Claiming alerting that does not exist is how an on-call rotation discovers it at 3am.

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

The interactive decision provider is subscription-backed rather than metered, with
multi-provider failover behind it. Per-call cost and latency are attributed in Langfuse and
accumulated into a per-user ledger, so "what does one user cost per month" is a query rather
than an estimate. Eval runs against real models are the largest discretionary spend, which
is why [chapter 06](06-quality.md) treats scoping a run before paying for it as part of the
process rather than an afterthought.

---

[← quality](06-quality.md) · [next: engineering process →](08-engineering-process.md)
