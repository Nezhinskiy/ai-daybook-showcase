# 11 · Roadmap

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

- **Notes in the Mini App** *(next)*. A list and detail surface with tags, the note→task
  affordance, and soft delete. The endpoint shape is the small part; how notes, inventory, and
  memory coexist in one navigation is the real question.
- **Journal and CBT read views**, after notes. Capture stays chat-only by design — silent
  capture is a product decision, not a missing screen.
- **A public demo entry point** *(next)*. The fixture-only build is already public; what is
  missing is a short `/demo` address and a gate that keeps the 375-wide layout off desktop.

## Moved out since the previous revision

Now in code at the pin. Described in [chapter 01](01-product.md): Food Product Identity v2
(the recently used product window, per-item and package cards, taps that edit the original
reply, merge and detach); saved-product, cooked-dish and recipe cards in the Mini App, which
retire the old "nutrition and recipes are not drawn anywhere" entry; first-run onboarding; the
router's card for a photo it cannot place. Described in [chapter 05](05-data-model.md): the
destructive food-schema contraction that gated the identity work, which removes the old
S1–S5 entry here (S3–S5 were superseded by v2 rather than built). Also shipped: the macOS
screen-time connector's install command, typed observations of the QR codes and printed
links on a photo, and a pgvector-enabled Postgres image in every environment, which no table
uses yet.

## Designed

A written design or plan exists; no code does.

- **Links on food packaging, slice S-C** — a minimal browsing service and a FoodAgent tool
  that opens a package's link only when the photo's own data are not enough. It reads
  schema.org markup first with a schema-bound model extraction as fallback, follows at most
  three hops under a time budget, and hands the agent extracted fields, never page text. The
  router never fetches. The first two slices (the routing card and the link observations it
  reads) are in code; this one has an approved plan.
- **Journal J2–J5** — J2-a, three embedding tables on the now-deployed pgvector image, is next
  and gates semantic note search. Then coping rules with cue matching, an anti-rumination
  cooldown, relapse-passport trajectory matching, cross-domain correlations, behavioral
  activation, a session-mode therapist agent, and a decision journal with calibration review.
- **Structured training** — strength and other sports as first-class records: a shared
  exercise catalogue with a per-user overlay, per-set load, a quiet live session with a
  deterministic fast path, and progress and muscle-balance views, owned by a new
  TrainingAgent. The design exists; it is to be re-planned against the shipped product
  identity work before any plan is written.
- **Rare router clarification and context-preserving continuations** — one categorical router
  abstention plus durable continuations, layered over the already-shipped inline questions
  and durable conversation context.
- **Windows connector installer** — the macOS install command is shipped; a PowerShell
  bootstrap and a scheduled task remain for Windows.
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
- Episode debugging views · charting and correlation analytics · code-defined alerting
  (Sentry captures today, it does not alert).

---

[← guards](10-guards.md) · [back to the overview](../README.md)
