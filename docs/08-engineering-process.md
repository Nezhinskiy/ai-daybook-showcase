# 08 · Engineering process

[← back to the overview](../README.md)

This is a solo-built system. That makes the process question sharper rather than softer:
with no reviewer to catch you, the discipline has to be structural, or it does not exist.

**213 design and plan documents** sit behind the code. Not as ceremony — as the mechanism
that makes the next decision cheaper than the last.

## Design before plan before code

Every non-trivial change moves through the same pipeline, and each stage has a different
job:

1. **Spec** — what is being built and *why this shape*, with the alternatives that were
   rejected and the reason. Approved before anything is planned.
2. **Plan** — the implementation, decomposed into independently testable tasks with their
   test cycles written out.
3. **Implementation** — task by task, tests first.
4. **Review** — an adversarial pass over the diff, with findings reproduced before they are
   acted on.
5. **Eval gate** — the merge barrier described in [chapter 06](06-quality.md).

Specs and plans are **historical evidence**, deliberately not rewritten to match what the
code became. When implementation deviates from a spec, the deviation is recorded as an
erratum in the spec rather than edited away. The trail is therefore a record of what was
believed at each point — which is the only version of a design document worth keeping.

## Documentation as a routed system

One fact has one authoritative home; everything else links to it. Phase status lives in the
roadmap, contracts in the architecture documents, procedures in runbooks, decisions in
specs, defects in bug reports, eval freshness in generated status.

The always-loaded index carries hard budgets — 300 lines, 3,000 words — enforced by a guard
in CI, along with the existence of every file it links to. That constraint is the whole
point: an index that can grow without limit stops being an index, and the budget forces
detail into the document that owns it.

This is not a preference about tidiness. Context is finite. A knowledge base that repeats
itself produces contradictory status, and contradictory status is worse than none.

## Defects get written down before they get fixed

Bug reports carry the symptom, the production evidence that localized it, the exact seam at
fault, the commit that introduced it, and the fix commit by SHA. Rejected findings are
recorded too, with the reasoning — so the same non-bug is not re-investigated in six months.

The habit this enforces: **reproduce before you act.** A finding from a review, a static
analyzer, or another agent is a hypothesis until it is reproduced. Acting on unverified
findings is how a codebase accumulates changes that fix nothing.

## AI-assisted delivery, directed rather than trusted

Much of this system was built with AI assistance. The interesting part is not that it was —
it is what had to be true for that to produce something trustworthy.

Every guard in [chapter 04](04-security.md) and every gate in [chapter 06](06-quality.md) is
a mechanism for not trusting an assertion — including the model's, and including mine. The
eval gate does not care who wrote the change. The capability guard does not care how
confident the decision was. `mypy --strict` over tests catches a test that asserts nothing
just as readily whether a human or a model wrote it.

Concretely, this means:

- **A deterministic oracle beats a review.** When a change is mechanical but large — a
  167-string translation across two locales — the specification is a test that walks the
  result and fails on any Cyrillic, not a checklist that someone promises to have followed.
- **Findings are reproduced, not relayed.** A reviewer's claim gets verified before it is
  repeated, let alone acted on.
- **Flakes are attributed with an A/B against a stashed baseline**, not by rerunning until
  green. Repetition alone does not distinguish "my change broke it" from "this host is
  loaded" — a controlled comparison does.
- **A guard is added at the seam, not at the symptom.** Repeated defects at the same
  boundary are a redesign signal, not an invitation to another local patch.

The claim worth making from all this is not "I used AI to go faster". It is that the
verification apparatus is strong enough that speed does not cost correctness — which is the
same apparatus a team would need, built by one person because there was no one else to
catch the mistakes.

## Three decisions where the judgment was the deliverable

The obvious question about a repository built this way is which parts are actually the
author's. The honest answer is that the volume is not, and the boundaries are — so here are
three places where the implementation was ready and the right call was to overrule it. Each
is verifiable in the code.

**1. The SQL function allow-list was keyed on the wrong thing.** The obvious implementation —
read each function node's canonical name through sqlglot's `sql_name()`, check membership —
collapses every unrecognized function in existence onto a single key, because that is how the
library models a name it does not know. The allow-list would have passed every test written
against the functions I had remembered to name while admitting `pg_read_file`. Six lines to
fix; the finding is the whole value, and it came from reading the library's object model
rather than its documentation.
[Chapter 04 carries it in full](04-security.md#the-bug-that-made-the-allow-list-real).

**2. Refusing to parallelize the context blocks.** Context assembly is the visible latency
cost on every request: six blocks, several of them DB-backed, awaited one after another.
Wrapping them in `asyncio.gather` is the obvious optimization and it is wrong here, because
production and the eval harness both open **one** `AsyncSession` and pass that same session
into every block — and SQLAlchemy's `AsyncSession` forbids concurrent operations. Doing it
"safely" means a session per block, which multiplies connections per turn in a system that
has already exhausted its connection slots once (see
[BR-021](EVIDENCE.md#br-021--an-orphaned-event-loop-leaked-one-postgres-connection-per-agent-run)).

The correct lever was not concurrency but scope: context blocks are declared per capability,
so the fix for wasted reads is to remove them from the bundle. `KeeperNotesCapability` was
split into a note-actions capability and a separate context capability, so an inventory intent
keeps the note actions reachable and drops the recent-notes and tag reads entirely. Same
latency win, no new failure mode.

**3. Not building a prompt-injection filter.** Product names from OpenFoodFacts, window titles
from screen-time events, transcribed voice, and text recognized in photos all reach a model
that can call write tools, and none of it was authored by the user. The expected move is a
filter. There is none, and there will not be one.

The reasoning is in [chapter 04](04-security.md#layer-0--the-models-inputs-are-untrusted-too):
the capability bundle is computed from the user's own intent *before* any untrusted text is
assembled, so injected instructions can at worst cause a wrong call **inside** a plan the user
already authorized. A filter would add a bypassable component and a false sense of coverage
on top of the thing already doing the work. The residual risk — a crafted product name
steering a value inside an authorized plan — is stated rather than papered over.

The common shape of all three: the implementation was available and plausible in each case,
and what decided it was reading one layer below the abstraction — how sqlglot models an
unknown function, what a shared `AsyncSession` actually forbids, where the trust boundary
really is.

---

[← operations](07-operations.md) · [next: governance →](09-governance.md)
