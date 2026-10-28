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

The rule holds when one correction fans out. Fixing a saved product's nutrition in the Mini
App can optionally restate the past meals and cooked dishes that used it; a durable workflow
rewrites them one transaction each, every rewrite with its own `change_log` row, and it
restates only items whose product still reads as the edit left it, so a later edit or a
typed correction is never overwritten by an older run. Merging two saved products moves their
history to the survivor without changing a single past number, and each relabelled item
records why in its own usage chain, which is what lets a detach give the history back.

## Products and their forms

Food's catalogue is per user. A saved product is one row; each labelled form of it (name,
brand, package, shops, product codes, nutrition) is a row of its own, so a product bought in
two sizes or two shops is one product with two forms rather than two products that drift
apart. Which saved product a meal item used is recorded as a binding with its evidence and a
trust level, not inferred later from a name.

## Episodes carry evidence and confidence

Automated signals — screen time, Wi-Fi places, movement, workouts — arrive as raw events.
They are not activities. A separate interpretation step derives *episodes* from bursts of
them, and every episode records the evidence it was derived from and a confidence score.

Confidence ≥ 0.7 promotes automatically. Below that, the analyzer may ask, and learns from
the answer. An episode is never inferred without persisted evidence — so when a derived
"gym session" is wrong, you can see exactly which events produced it rather than arguing
with a black box.

## Multi-tenancy is a schema property

Every user-owned table carries `user_id`, and every table behind the analytical read surface
carries it directly. Not a foreign-key path to a parent that carries it — directly, including
junction tables, because row-level security policies must be expressible on the table
itself. Some write-side children still reach their user through a parent (memory audiences,
inventory collection links, conversation turn revisions); the rule is that such a table gains
its own `user_id` before it becomes readable, because the alternative silently produces
tables the policy cannot protect; see [chapter 04](04-security.md).

## Destructive changes are expand, then contract

Moving food quantities from grams-only to native grams and millilitres took several
releases, not one. The new storage was added beside the old, the new writer ran in production on the
expanded schema through a soak window, and only then did a single, manually approved run
drop the legacy columns. That run verified the image, schema revision and backup before the
DDL and wrote an append-once receipt in the same transaction; the application's startup
gate now reads that receipt rather than any configuration flag. Historical effect payloads
still speak the old shapes, so their decoders are kept permanently: a contraction removes
columns, never the ability to read what was written before it.

## Typed contracts at every boundary

Pydantic contracts sit at every workflow, activity, and tool boundary. A raw dict is never
passed downstream to be re-parsed by the receiver — the shape is declared once, validated at
the edge, and typed thereafter. Contract models used inside workflows must be complete at
import time, because a forward reference resolved lazily breaks replay.

## Scale

**143 reviewed migrations** across fourteen domains. The schema's shape is set by two rules
rather than by the domain count: on the read surface user scope is a column rather than a
join, and nothing is overwritten.

---

[← security](04-security.md) · [next: quality →](06-quality.md)
