# 08 · Engineering process

[← back to the overview](../README.md)

This is a solo-built system. That makes the process question sharper rather than softer:
with no reviewer to catch you, the discipline has to be structural, or it does not exist.

**227 design and plan documents** sit behind the code. Not as ceremony — as the mechanism
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
erratum in the spec rather than edited away, so the trail records what was believed at each
point rather than what turned out to be true.

## Documentation as a routed system

One fact has one authoritative home; everything else links to it. Phase status lives in the
roadmap, contracts in the architecture documents, procedures in runbooks, decisions in
specs, defects in bug reports, eval freshness in generated status.

The always-loaded index carries hard budgets — 300 lines, 3,000 words — enforced by a guard
in CI, along with the existence of every file it links to. The budget is what forces detail
into the document that owns it — see [chapter 09](09-governance.md#documentation-is-routed-and-the-router-is-enforced).

This is not a preference about tidiness. Context is finite, and a knowledge base that repeats
itself produces contradictory status.

## Defects get written down before they get fixed

**141 entries**, one file each, with the index generated from them. Each carries the symptom,
the production evidence that localized it, the exact seam at fault, and the fix commit or pull
request — [four of them are reproduced in full](EVIDENCE.md#7-four-defects-unabridged). The
tooling that validates them is [chapter 09](09-governance.md#the-defect-ledger-is-a-program-not-a-file).

Three rules govern the file, and each was written after the absence of it cost something:

- **An entry is filed at the moment a finding is deferred**, not batched at the end of a run.
  Two genuine hot-path performance regressions once lived only in a gitignored task log and
  would have evaporated with the worktree that wrote it; a final review caught them by
  accident, not by process.
- **Rejected findings stay, with the reasoning.** A verified non-bug that is deleted gets
  re-investigated in six months, and deleting it would also renumber everything after it —
  identifiers have to stay stable for the evidence to be citable.
- **A cited covering test must exist — verify the path before saving the entry.** An earlier
  entry cited `tests/evals/test_reasoning_log.py`, a file that has never existed in this
  repository. An unverifiable citation reads as "covered" when it is not, which is worse than
  citing nothing.

The third rule is the transplantable one: the process noticed that it had produced a false
coverage claim, and closed that specific hole.

The habit all three enforce: **reproduce before you act.** A finding from a review, a static
analyzer, or another agent is a hypothesis until it is reproduced.

## AI-assisted delivery, directed rather than trusted

Much of this system was built with AI assistance. The interesting part is not that it was —
it is what had to be true for that to produce something trustworthy.

Start with the number a reader will otherwise compute themselves and frame however they
like: **4,117 commits and 270 merged pull requests in 93 days**, one author. Roughly forty-four
commits a day. That rate is not evidence of anything on its own — it is the reason every
mechanism in [chapter 09](09-governance.md) exists, because a boundary nobody checks erodes
in weeks at that speed, and a review pass by the person writing the change is not a check.

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

## Implementation plans written for a fleet, not a person

The system in this repository orchestrates agents. So does the process that built it, and the
artifact is checkable: the implementation plans are written to **fan out across parallel
agents**, and the merge commits carry the lane names.

The most recent one — deterministic product-code binding, twelve tasks — opens with a
dependency graph rather than a task list:

```text
Wave 1 (4 lanes, fully parallel)
  L-EVAL    Task 0   eval fixtures pass response_language
  L-SEAM    Task 1   move resolve_product to catalog_resolution.py
  L-REPO    Task 2   FoodProductCodeRepository.lookup_many
  L-ORACLE  Task 8   evaluator: tool alternation + any_of groups

Wave 2 (1 lane)              needs Task 1 + Task 2
  L-BIND    Task 3   code_binding.py + the shared test scaffolding

Wave 3 (3 lanes, parallel)   M and C need Task 3; E needs only Task 8
  L-MEALS   Task 4 → 5   (meals.py — sequential inside the lane, one file)
  L-COOK    Task 6        (cooking.py)
  L-EVALS   Task 9        (dataset + the materialization proof test)

Wave 4 (1 lane, after every Wave-3 merge)
  L-INT     Task 7   static gates + the whole -m db lane

Wave 5 (1 lane, serialized, human-gated: it spends paid runs)
  L-SHIP    Task 11  the two real-model gate runs
```

Three isolation rules make that safe, and each exists because the alternative loses work:

- **Every lane owns an exclusive write set**, listed file by file in the plan. A lane may
  write only the files its tasks name. If a task turns out to need a file another lane owns,
  it stops and the plan is amended — merging two lanes that both edited one file is how a
  wave loses work silently.
- **Every lane gets its own git worktree**, so a rebase in one cannot move another's HEAD.
- **Every lane gets its own Postgres database.** The `-m db` tier runs real migrations and
  real fixtures; two lanes sharing one test database corrupt each other's state in ways that
  read as flaky tests. The plan assigns `ai_daybook_s0_<lane>` per lane rather than leaving it
  to whoever runs it.

And the last wave is **human-gated on purpose**: it is the one that spends paid real-model
runs, so it is serialized behind a person rather than dispatched. Cost is a scheduling
constraint, not an afterthought.

The transferable claim is not "I used subagents". It is that fanning work out across
independent agents is an *orchestration design problem* — dependency graph, exclusive
ownership, state isolation, and a gate where the resource is scarce — and that it is the same
problem the capability model solves inside the product, one level up.

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
