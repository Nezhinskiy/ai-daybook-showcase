# 10 · Roadmap

[← back to the overview](../README.md)

Chapters 01–09 describe only what is shipped and reachable in code at the pinned commit. This
chapter is everything else.

Two labels, because a reader outside the project cannot act on more: **Designed** means a
written design or implementation plan exists and no code does. **Direction** means the
decision is made and nothing is specified.

## Shipped in chat, not yet in the Mini App

The most important entry, because a reader would otherwise infer it from the screenshots and
draw the wrong conclusion.

Keeper notes, journal entries, and CBT records are **fully shipped on the capture side** —
typed effect tools, tags, corrections, the note→task handoff, and nine read-only QueryAgent
SQL views over them. They have no Mini App endpoint and no screen.

That is sequencing, not neglect: capture was built first because a missing screen is
recoverable and a missing record is not. Everything logged through chat is queryable and
auditable today; it is simply not yet drawn.

- **Notes in the Mini App.** A list and detail surface with tags, the note→task affordance,
  and soft delete. The endpoint shape is the small part; how notes, inventory, and memory
  coexist in one navigation is the real question.
- **Journal and CBT read views**, after notes. Capture stays chat-only by design — silent
  capture is a product decision, not a missing screen.
- **Read surfaces for nutrition and recipes.** Records that exist and are queryable but are
  not drawn anywhere.

## Designed

A written design or plan exists; no code does.

- **Food product identity, slices S1–S5** — a seven-document program covering per-user
  identity beyond product codes: usage bindings, a lexical shadow index, semantic
  calibration, and resolution UX. **S0, deterministic product-code binding, shipped in
  August 2026**; S1–S5 have no implementation plan and nothing in code or migrations, and are
  gated behind a destructive schema contraction that has not started. The roadmap states that
  gate as a table of five checkpoints with the evidence that each has not begun — an absent
  migration file, an absent workflow file, three columns still mapped in the ORM — rather
  than as a status word.
- **Rare router clarification and context-preserving continuations** — one categorical router
  abstention plus durable continuations, layered over the already-shipped inline questions
  and durable conversation context.
- **Journal J2–J5** — pgvector infrastructure and three embedding tables (which gate semantic
  note search), guided CBT breakdown, relapse-passport trajectory matching, cross-domain
  correlations, behavioral activation, a session-mode therapist agent, and a decision journal
  with calibration review.
- **Connector distribution** — PyInstaller bundles, signing and notarization, a release
  workflow, bootstrap installers. The install endpoints return 404 until both plans land,
  which is why the connector is not presented as available.
- **iPhone screen time** — transport, Wi-Fi places, and workout episodes are shipped;
  app-open and app-close events into screen blocks are not.
- **Expiry reminders** — wiring `expires_at` into the actionable-reminder system.

## Direction

Decided, not specified.

- **Deterministic evidence orchestration (v2).** The first domain decision returns either
  final typed actions or a closed evidence plan; pure code validates and executes only
  intent-scoped deterministic read tools; a tool-free model turn then produces the decision
  from a frozen evidence bundle. Predictable fallbacks belong in the initial plan, with one
  bounded replan reserved for an unexpected missing need. This is the change that would move
  the latency in [chapter 07](07-operations.md#what-it-actually-does-measured).
- **Service extraction (v3).** Pulling stable repeated logic out of the agents — food
  resolution, nutrition calculation, batch matching, confidence policy, episode building,
  activity classification — now that the behavior has stabilized enough to be worth freezing.
- **A native mobile application**, replacing the Telegram Mini App as the primary visual
  surface while Telegram remains a capture channel.
- **Explicit Apple Health export** from the phone, replacing inference from proxy signals
  with the user's own authoritative record.
- **Geolocation places**, superseding Wi-Fi-only detection so a place resolves without a
  known network in range.
- **One-tap Shortcuts installation** from the Shortcuts library.
- Episode debugging views · `workout_log` sets-and-reps promotion · charting and correlation
  analytics · code-defined alerting (Sentry captures today, it does not alert).

---

[← governance](09-governance.md) · [back to the overview](../README.md)
