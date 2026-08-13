# 05 · Data model

[← back to the overview](../README.md)

A life log has an unusual property: it is append-mostly, corrections arrive late, and the
value is almost entirely in cross-domain joins. That shapes the schema more than the
domains do.

## Every record keeps what you said

Alongside the parsed fields, each domain record stores `raw_input` — the user's original
text, verbatim. It costs a column and it buys two things: a misparse is always traceable to
its source, and a record can be re-derived later when parsing improves, because the input
was never discarded.

## Corrections are events, not overwrites

A user-initiated update writes a `change_log` entry with a before/after snapshot. Nutrition
history, agent memory, and prior corrections are never silently replaced.

The practical reason is that "how did this value get here?" is a question you will ask, and
a schema that overwrites cannot answer it. The stronger reason: an agent that can quietly
rewrite history is an agent whose past output you cannot trust, which makes the whole log
worthless as evidence about your own life.

Clearing a value is its own explicit channel rather than a null slipping through — a blank
string is rejected instead of being normalized into a clear, because "I meant to erase this"
and "the model omitted a field" must not look identical to the database.

## Episodes carry evidence and confidence

Automated signals — screen time, Wi-Fi places, movement, workouts — arrive as raw events.
They are not activities. A separate interpretation step derives *episodes* from bursts of
them, and every episode records the evidence it was derived from and a confidence score.

Confidence ≥ 0.7 promotes automatically. Below that, the analyzer may ask, and learns from
the answer. An episode is never inferred without persisted evidence — so when a derived
"gym session" is wrong, you can see exactly which events produced it rather than arguing
with a black box.

## Multi-tenancy is a schema property

Every row carries `user_id` directly. Not a foreign-key path to a parent that carries it —
directly, including junction tables, because row-level security policies must be
expressible on the table itself. That house rule exists because the alternative silently
produces tables the policy cannot protect; see [chapter 04](04-security.md).

## Typed contracts at every boundary

Pydantic contracts sit at every workflow, activity, and tool boundary. A raw dict is never
passed downstream to be re-parsed by the receiver — the shape is declared once, validated at
the edge, and typed thereafter. Contract models used inside workflows must be complete at
import time, because a forward reference resolved lazily breaks replay.

## Scale

**97 reviewed migrations** across fourteen domains. The schema's shape is set by two rules
rather than by the domain count: every row carries `user_id` directly, and nothing is
overwritten.

---

[← security](04-security.md) · [next: quality →](06-quality.md)
