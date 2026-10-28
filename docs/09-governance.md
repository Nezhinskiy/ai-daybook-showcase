# 09 · Governance

[← back to the overview](../README.md)

First commit 2026-05-16, pinned here at 2026-10-26. **8,913 commits and 620 merged pull
requests in 163 days** — around 55 commits and 4 merged PRs a day, by one person.

That rate is the reason this chapter exists. A codebase decays through erosion of the
boundaries that made the code good rather than through bad code, and at fifty-odd commits a
day that erosion takes weeks, not years. There is also no second person to notice it
happening.

So the boundaries are written down as contracts, and the contracts are enforced by machines.
Every one of those 8,913 commits went through them.

## Every package declares what it must not know

The load-bearing artifact is a table with three columns — and the third is the one that does
the work.

| Package | Owns | May know | **Must not know** |
|---|---|---|---|
| `contracts/` | Pydantic contracts at transport, workflow, agent, tool, and outbound boundaries | Stable enum/value modules; JSON-safe payload shapes | SQLAlchemy sessions, prompt text, tool handlers, provider clients, runtime-only objects |
| `workflows/` | Temporal durable control flow, retries, fan-out/fan-in, timers, idempotent orchestration | Activity names and typed activity inputs/outputs | DB business rules, prompt content, provider clients, domain write logic |
| `agents/capability/` | The capability object model, `CapabilityPlan`, `ResolvedPlan`, expansion, resolution, derived registries | Domain unit objects at the aggregation point; stable wire values | Domain runtime behavior, model calls, DB sessions, hand-authored registries that duplicate the object graph |
| `agents/router/` | Message splitting, route selection, intent selection, no-route fallback | Domain agent names, intents, route contracts | Domain record writes, domain tool handlers, **or solving the routed task directly** |
| `db/effects/tools/<domain>` | Domain tool handlers: validation, `user_id` enforcement, writes, change logs | Repositories, models, effect input contracts | Agent prompt reasoning, router decisions, direct provider calls |
| `models/` | SQLAlchemy ORM schema and constraints | `domain_values.py` values that back DB checks | Runtime behavior, repositories, services, prompt/tool logic |

<sub>Six of twenty-two rows. The full table is one of three documents an agent or a
contributor must read before a cross-package change.</sub>

"Owns" and "may know" are aspiration; anyone can write those. **"Must not know" is a
falsifiable claim about an import graph** — and "the router must not solve the routed task
directly" is the single line that keeps an eleven-agent system from collapsing into one agent
with a large prompt.

The same document separates **framework code** (`agents/common/`, `agents/capability/`,
`rag/`, `screen/`, `evals/`, runtime dispatch) from **domain code** (`agents/<domain>/`,
domain effect tools). The rule is deliberately conservative in one direction: *duplicate once
if the abstraction is not yet stable.* Premature framework extraction is the more expensive
mistake, because it is the one that has to be undone across every domain at once.

## Where a boundary was deliberately crossed, and why

Governance that only ever says no is governance nobody follows. The boundaries document also
records the exceptions, each with the argument that admitted it.

The Keeper's `CreateTaskFromNoteAction` — an inventory-domain action — plans a tool call
against `create_task`, a **planning-domain** effect tool. That is exactly the kind of
cross-domain reach the layering exists to prevent. It is allowed, for a stated reason: the
capability guard's allow-set is derived from the *resolved plan*, not from a per-domain tool
list, so the bundle is the security axis and the domain is not. And the owning tool keeps one
hundred percent of its validation — `create_task` still enforces ownership on
`source_note_id` itself, so the calling domain adds no bypass.

The rule that came out of it is written as guidance for the next case: prefer this over
duplicating a write tool per domain when one domain's action is simply "invoke another
domain's existing effect with different input provenance".

The reasoning is what makes it a precedent rather than an inconsistency to be copied.

## Repeated defects trigger a sweep, not another patch

A fix names two things: the patch, and the defect's **class** — its shape, not the site where
it was found. The class goes in the commit message even for a one-site fix, because a second
occurrence has nothing to be recognized against otherwise.

The **second** occurrence of a named class is not another patch. It stops the work and
triggers a sweep:

1. Search the whole surface the class can occur in.
2. Record every site with a disposition — `fixed`, or `excluded` **with the specific reason it
   is safe**.
3. Fix every `fixed` site in the same change.
4. Attach the repo-wide search and its match count to the fix.

Step 2 is the part that is usually skipped and is the reason the rule exists: *"probably fine"
and "checked and judged fine" look identical afterwards; only a written reason tells them
apart.*

This is not a policy someone imagined would be useful. It was written after the underlying
principle — *repeated defects at the same seam require redesign, not another local patch* —
already existed, and still took a human noticing a third instance to fire, with a fourth site
found later by a reviewer rather than by process. Naming the class at fix time converts the
second occurrence into an automatic trigger instead of something that depends on someone
remembering the first.

The distinction it draws matters too: a defect *class* can recur at unrelated sites with no
shared abstraction — a shell idiom repeated across independent scripts — where the answer is
exhaustive enumeration, not a structural rewrite. That is a different rule from the
same-seam one, and applying the wrong one produces either a needless refactor or a fourth
occurrence.

## The defect ledger is a program, not a file

For most of the project the bug log was one Markdown file. At 95 entries it stopped working
the way shared files stop working: every branch that filed a bug touched the same lines, and
merges resolved by picking a side.

It is now **436 entry files** under `docs/bugs/`, one per bug, with mutable state in
frontmatter and the index generated from them. The tooling began as an in-repository script;
since October 2026 it is `stayfixed bugs`, part of a separately published harness CLI pinned
at an exact version and hash in the lockfile, and a test pins that the replaced scripts do
not come back. It runs in CI in two jobs — the documentation job and the static-checks job —
so both a docs change and a code-only change that mentions a `BR-nnn` reach it.

Four subcommands remain, and the interesting half is what each one *refuses*:

| | |
|---|---|
| `check` | Validates every entry, index freshness, and every `BR-nnn` mentioned anywhere in code. Refuses an empty evidence boundary on a high-severity entry; with `--base`, refuses a change that deletes an entry. |
| `index` | Regenerates the index — and **refuses if the file holds one line the generator did not write**, because rendering over it would delete that content silently, with exit 0. |
| `new` | Allocates the next free identifier across every reference and scaffolds the entry. Refuses an identifier whose file already exists, before writing anything. |
| `renumber` | Moves a colliding entry *and sweeps every reference to it*, failing loudly on any it could not rewrite. |

A fifth, the three-way `migrate --from <ref>` that carried pre-split branches across, was
retired once nothing needed it — and "nothing needed it" was verified per ref, over every
unmerged branch and worktree head, rather than read off a history search that cannot see a
branch editing text inside an existing section.

Two design decisions carry most of the value.

**A destructive command must name the repair, not just the refusal.** Each refusal above
prints the specific command that resolves it — and where no command can (content only a human
can recover), it says so instead of suggesting one. A guard that blocks without naming the
exit gets bypassed.

**Identifiers never move.** Five entries carry `status: void` rather than being deleted,
because BR numbers are cited in commits, prose and code, and a deletion would silently
renumber everything a reader might follow. `check` treats a mention of a void identifier as
valid and a mention of an unfiled one as an error.

**And the guard writes down what it cannot see.** Its runbook carries eight explicit blind
spots: stale `path:line` citations inside an entry, a `fixed_in` naming a commit that does
not exist, an identifier written in a gitignored file, a typo inside a file marked as ledger
fixtures. The sharpest one is a gap in **CI's own path filters**: a `BR-nnn` added under
`scripts/`, `clients/`, `infra/`, `.github/`, `frontend/` or the repository root — roots the
scan reads but no CI filter watches whole — reaches the local check but not the CI one, so
it merges green and surfaces on somebody else's pull request. That is written down as a known gap with its cause and its fix, rather than left
for the next person to rediscover as a mystery. [Chapter 10](10-guards.md) collects every
guard in the project the same way.

Structural debt has a ledger of its own, built the same way — `docs/debt/TD-nnn.md`
entries, a generated index, and a check that runs on every pull request not aimed at `main`,
with no path filter, because an entry can name a path anywhere and the change that moves that path
is the one that has to fail. [Chapter 08](08-engineering-process.md#defects-get-written-down-before-they-get-fixed)
has the gates it enforces.

## Documentation is routed, and the router is enforced

One fact has one authoritative home. Everything else links.

| Information | Authoritative home |
|---|---|
| Agent-facing rules, invariants, commands, current frontier | `AGENTS.md` |
| Phase status and product backlog | `docs/roadmap.md` |
| Runtime and domain contracts | `docs/architecture/` |
| Operational procedures | `docs/runbooks/` |
| Delivered-narrative history | `docs/roadmap-history.md` |
| Decisions and trade-offs | `docs/adr/` and approved specs |
| Defects, causes, fix status | `docs/bugs/BR-nnn.md` (index generated) |
| Structural debt, its gate and size | `docs/debt/TD-nnn.md` (index generated) |
| Eval freshness and results | `docs/skills/eval-status.md` (generated) |

The always-loaded index is capped, and the cap is a CI step, not a convention:

| Budget | Limit |
|---|---|
| `AGENTS.md` | 300 lines, 3,000 words |
| its `## Current status` section | 50 lines |
| `docs/roadmap.md` prose, above the generated trail | 350 lines, 3,500 words |

<sub>`stayfixed docs check --budgets --links` — the numbers come from the pinned tool's preset,
which the repository may lower and never raise. It also asserts that every local file linked
from the index exists.</sub>

An index that can grow without limit stops being an index. The budget is what forces detail
down into the document that owns it, and the "must not contain" list is as specific as the
boundaries table: no shipped-feature narratives, no PR or commit history, no dated eval
results, no resolved incidents.

The index also has a rule about commands, learned at a price. A command written out in it is
already in context; the procedure that governs it has to be opened, so the index wins by
default — including when it should lose. A ready-to-run `--agent <domain> --k 5` line beat
the scoping protocol that owns that decision, and the blanket run it invited cost a real paid
eval. So a command in the index is either safe in its blanket form or carries the owner's
link on the same line.

The last two constants were added when the roadmap hit the same wall the index had: it had
become a delivery narrative of everything ever shipped, and the frontier — the only part
anyone reads to decide what to do next — was buried under it. It split into a frontier
document and an archive, and the budget now applies to the **hand-written prose only**,
excluding the generated design-and-plan trail below it. That exclusion is the load-bearing
detail: a budget that counted generated content would punish the project for having a
complete index and reward deleting it.

**Where the guard deliberately does not run.** It gates every pull request *not* aimed at
`main` — not `dev` → `main`, not pushes to `main`, not deploys. That is a decision, not a gap:
the release path must be able to ship over a documentation-policy violation when the owner
accepts it knowingly. A guard that can block a production fix on a line-count budget will be
disabled the first time it does, and then it protects nothing.

The condition was once written the other way round, as "base is `dev`". A stacked pull
request based on a feature branch then skipped every documentation gate and came back green,
vacuously. The exclusion the condition exists for is a statement about `main` alone, so that
is what it now says.

## Six ADRs, and what they are for

| | |
|---|---|
| ADR-0001 | Temporal-first, agent-heavy v1 |
| ADR-0002 | No dedicated `ClarificationWorkflow` in v1 |
| ADR-0003 | Telegram Agent Work Chat is a mirror, not a queue |
| ADR-0004 | Agents use typed tools, not raw SQL writes |
| ADR-0005 | Telegram user registration |
| ADR-0006 | Size the operational envelope to measured scale |

Six, because these are the decisions anything else in the system can be checked against —
an ADR per feature would be a changelog under another name. ADR-0002 is the useful shape — it
records a workflow that was *considered and rejected*, so the next design that starts to
reinvent it meets the reasoning instead of the empty space where it would have gone.

ADR-0006 is the only one that records a mistake. The food-storage migration to native
gram and millilitre units was built with the full zero-downtime toolkit — expand/contract
migrations, a configurable writer generation, two application generations able to serve
one schema, soak windows, generated activation reports, a manually dispatched multi-step
release. It worked, with no data loss. The retrospective is about what it was sized against:
a 2,156-line plan and, at peak, about 5,500 lines of rollout choreography in `src` and 7,700
in tests, built over 44 days for a database small enough to dump and restore in seconds, on
one node with no availability target. A short maintenance window with a verified dump and
restore-as-rollback was never written down, so it was never rejected for a reason. Thirteen
ledger entries exist only because two representations or a generation gate were live at
once — and the only data the contraction ever refused was data the migration machinery had
itself written.

The diagnosis is the part worth keeping: not extravagance, but **a default imported from a
different operating scale**, after which every later discipline executed faithfully inside an
already-wrong frame — which is why no review caught it. The decision is a procedure, not a
preference. Before any migration, deploy, rollout or rollback strategy, the plan states the
measured scale, the downtime the owner will accept, and the cheapest strategy that meets
both, written out in full; the chosen strategy is then priced against it, and rejecting the
cheap option needs a named reason. A strategy costing more than about twice the cheapest
needs the owner's approval before work starts. It does not license shortcuts on data: a
verified backup and a rehearsed restore belong to the cheapest acceptable strategy at every
scale. The ADR says plainly that it is enforced by being loaded, not by a guard.

Specs and plans are treated the same way. They are **historical evidence** and are not
rewritten to match what the code became; a deviation is recorded as an erratum inside the
spec rather than edited away — a design document edited to match the implementation tells
you nothing the code does not already.

## What this is actually worth

Four documents, two ledgers, a pinned harness CLI, six ADRs, and a rule about the second
occurrence of a defect class. What it has already bought, over 8,913 commits in 163 days, is
that commit 8,913 had to answer the same questions as commit 12 — and that the answers were
checked by something other than the memory of the person making them, which at that rate is
not a resource you can spend.

---

[← engineering process](08-engineering-process.md) · [next: guards →](10-guards.md)
