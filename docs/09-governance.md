# 09 · Governance

[← back to the overview](../README.md)

A codebase that one person maintains for a year and a half decays in a specific way: not
through bad code, but through erosion of the boundaries that made the code good. Nobody
notices, because there is no one to notice.

So the boundaries are written down as contracts, and the contracts are enforced by machines.
**3,673 commits** have gone through them.

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

An exception with its reasoning attached is a precedent. Without it, it is just an
inconsistency that the next person will copy.

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

## Documentation is routed, and the router is enforced

One fact has one authoritative home. Everything else links.

| Information | Authoritative home |
|---|---|
| Agent-facing rules, invariants, commands, current frontier | `AGENTS.md` |
| Phase status and product backlog | `docs/roadmap.md` |
| Runtime and domain contracts | `docs/architecture/` |
| Operational procedures | `docs/runbooks/` |
| Decisions and trade-offs | `docs/adr/` and approved specs |
| Defects, causes, fix status | `docs/bug-reports.md` |
| Eval freshness and results | `docs/skills/eval-status.md` (generated) |

The always-loaded index is capped, and the cap is a script:

```python
AGENTS_MAX_LINES = 300
AGENTS_MAX_WORDS = 3_000
CURRENT_STATUS_MAX_LINES = 50
```

<sub>`scripts/check_documentation_hygiene.py` — also asserts that every local file linked
from the index exists, and that no bug-report ID is duplicated.</sub>

An index that can grow without limit stops being an index. The budget is what forces detail
down into the document that owns it, and the "must not contain" list is as specific as the
boundaries table: no shipped-feature narratives, no PR or commit history, no dated eval
results, no resolved incidents.

**Where the guard deliberately does not run.** It gates pull requests into `dev` and nothing
else — not `dev` → `main`, not pushes to `main`, not deploys. That is a decision, not a gap:
the release path must be able to ship over a documentation-policy violation when the owner
accepts it knowingly. A guard that can block a production fix on a line-count budget will be
disabled the first time it does, and then it protects nothing.

## Five ADRs, and what they are for

| | |
|---|---|
| ADR-0001 | Temporal-first, agent-heavy v1 |
| ADR-0002 | No dedicated `ClarificationWorkflow` in v1 |
| ADR-0003 | Telegram Agent Work Chat is a mirror, not a queue |
| ADR-0004 | Agents use typed tools, not raw SQL writes |
| ADR-0005 | Telegram user registration |

Five is the right number. An ADR per feature is a changelog wearing a costume; these are the
five decisions that anything else in the system can be checked against. ADR-0002 is the
useful shape — it records a workflow that was *considered and rejected*, so the next design
that starts to reinvent it meets the reasoning instead of the empty space where it would have
gone.

Specs and plans are treated the same way. They are **historical evidence** and are not
rewritten to match what the code became; a deviation is recorded as an erratum inside the
spec rather than edited away. A design document edited to match the implementation is a
document that can no longer tell you anything you could not get from the code.

## What this is actually worth

Three documents, one script, five ADRs, and a rule about the second occurrence of a defect
class. None of it is exotic. What it buys is that a change made eighteen months in still has
to answer the same questions as a change made in week one — and that the answers are checked
by something other than the memory of the person making it.

---

[← engineering process](08-engineering-process.md) · [next: roadmap →](10-roadmap.md)
