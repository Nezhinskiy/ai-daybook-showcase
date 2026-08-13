# 09 · Roadmap

[← back to the overview](../README.md)

Chapters 01–08 describe only what is shipped and reachable in code at the pinned commit.
This chapter is everything else, and it is labelled honestly, because a roadmap that blurs
into the feature list is worth nothing to anyone reading it.

| Label | Meaning |
|---|---|
| **Designed** | An approved design exists. No implementation plan, no code. |
| **Planned** | A written implementation plan exists. Deliberately not started. |
| **Backlog** | Identified and scoped in prose. No design pass yet. |
| **Next** | Direction agreed. Not yet specified. |

## What the Mini App does not show yet

The most important entry, because a reader would otherwise infer it from the screenshots
and draw the wrong conclusion.

Keeper notes, journal entries, and CBT records are **fully shipped on the capture side** —
typed effect tools, tags, corrections, the note→task handoff, and nine read-only QueryAgent
SQL views over them. They have no Mini App endpoint and no screen.

That is sequencing, not neglect: capture was built first because a missing screen is
recoverable and a missing record is not. Everything logged through chat is queryable and
auditable today; it is simply not yet drawn.

- **Notes in the Mini App** — *Backlog.* A list and detail surface with tags, the note→task
  affordance, and soft delete. The endpoint shape is the small part; how notes, inventory,
  and memory coexist in one navigation is the real question, and it needs a design pass.
- **Journal and CBT read views** — *Backlog*, after notes. Capture stays chat-only by
  design: silent capture is a product decision, not a missing screen.
- **Read-surface coverage for nutrition and recipes** — *Backlog.* Records that exist and
  are queryable but are not yet drawn anywhere.

## Designed

- **Food product identity** — a six-document program: an umbrella design plus five slices
  covering per-user identity beyond product codes, usage bindings, a lexical shadow index,
  semantic calibration, and resolution UX. No slice has an implementation plan; nothing has
  reached code or migrations.
- **Rare router clarification and context-preserving continuations** — one categorical
  router abstention plus durable continuations, layered over the already-shipped inline
  questions and durable conversation context.
- **Journal J2–J5** — pgvector infrastructure and three embedding tables (which gate
  semantic note search), guided CBT breakdown, relapse-passport trajectory matching,
  cross-domain correlations, behavioral activation, a session-mode therapist agent, and a
  decision journal with calibration review.
- **Expiry reminders** — wiring `expires_at` into the actionable-reminder system.

## Planned

- **Connector distribution** — PyInstaller bundles, signing and notarization, a release
  workflow, and bootstrap installers. The install endpoints return 404 until both plans
  land, which is why the connector is not presented as available.
- **iPhone screen time** — transport, Wi-Fi places, and workout episodes are shipped;
  app-open and app-close events into screen blocks are not.

## Backlog

- Episode debugging views.
- `workout_log` sets-and-reps promotion.
- Charting and correlation analytics.
- Code-defined alerting — Sentry captures today, it does not alert
  ([chapter 07](07-operations.md)).

## Next

Direction agreed, nothing specified yet.

- **Deterministic evidence orchestration (v2).** The first domain decision returns either
  final typed actions or a closed evidence plan; pure code validates and executes only
  intent-scoped deterministic read tools; a tool-free model turn then produces the decision
  from a frozen evidence bundle. Predictable fallbacks belong in the initial plan, with one
  bounded replan reserved for an unexpected missing need.
- **Service extraction (v3).** Pulling stable repeated logic out of the agents — food
  resolution, nutrition calculation, batch matching, confidence policy, episode building,
  activity classification — now that the behavior has stabilized enough to be worth
  freezing.
- **A native mobile application**, replacing the Telegram Mini App as the primary visual
  surface while Telegram remains a capture channel.
- **Explicit Apple Health export** from the phone, replacing inference from proxy signals
  with the user's own authoritative record.
- **Geolocation places**, superseding Wi-Fi-only detection so a place resolves without a
  known network in range.
- **One-tap Shortcuts installation** from the Shortcuts library.

---

[← engineering process](08-engineering-process.md) · [back to the overview](../README.md)
