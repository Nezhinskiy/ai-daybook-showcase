# Evidence

[← back to the overview](../README.md)

Output, not description. Every block below is something a command printed, pasted verbatim.
Measured at commit `4fc9ea5e`, 2026-10-26, on a clean tree. One section is older:
[§8](#8-production) was read from the production database on 2026-08-17 and was not re-read
at this pin.

**Contents** — [counts](#1-the-counts-and-the-commands-that-produced-them) ·
[one request end to end](#2-one-request-end-to-end) ·
[the guard, exercised](#3-the-guard-exercised) ·
[the plan-scope check, exercised](#4-the-plan-scope-check-exercised) ·
[the SQL validator, exercised](#5-the-sql-validator-exercised) ·
[a defect the evals could not see](#6-a-production-defect-the-eval-suite-could-not-see) ·
[four defects unabridged](#7-four-defects-unabridged) ·
[production](#8-production) ·
[the current strict gate](#9-the-current-strict-gate)

---

## 1. The counts, and the commands that produced them

```console
$ git ls-files tests | grep '\.py$' | tr '\n' '\0' | xargs -0 grep -hoE '^[[:space:]]*(async )?def test_' | wc -l
   15186
$ grep -rhoE "^\s*(it|test)\(" frontend/src | wc -l
    1073
$ git ls-files tests | grep '\.py$' | tr '\n' '\0' | xargs -0 cat | wc -l
  566279
$ git ls-files src  | grep '\.py$' | tr '\n' '\0' | xargs -0 cat | wc -l
  267796
$ git ls-files src/app/evals/evaluators | grep '\.py$' | tr '\n' '\0' | xargs -0 grep -hcE "^class [A-Za-z]+\(Evaluator\)" | awk '{s+=$1} END {print s}'
68
$ grep -hcE "^  - " src/app/agents/skills/*/evals/dataset.yaml | awk '{s+=$1} END {print s}'
566
$ grep -rh '@workflow.defn' src/app/workflows/ | wc -l
      24
$ ls -1 alembic/versions/*.py | wc -l
     143
$ ls -1 docs/specs/*.md docs/plans/*.md | wc -l
     305
$ ls -1 docs/bugs/BR-*.md | wc -l
     436
$ ls -1 docs/debt/TD-*.md | wc -l
     469
```

Two of these commands differ from the previous revision of this page, because the files moved,
not because the counting did:

- **Evaluators.** `src/app/evals/evaluators.py` became the package `src/app/evals/evaluators/`;
  the same regex, summed over the package, gives 57 at the previous pin, so the two are comparable.
- **Specs and plans.** They moved from `docs/superpowers/{specs,plans}` to `docs/{specs,plans}`;
  the old command prints `0` at this pin.

The two ledgers, by status (read from each entry's frontmatter):

```console
$ for f in docs/bugs/BR-*.md; do awk '/^---$/{n++; next} n==1 && /^status:/{print $2; exit}' "$f"; done | sort | uniq -c | sort -rn
 321 fixed
  84 open
  19 partial
   6 void
   6 rejected
$ for f in docs/debt/TD-*.md; do awk '/^---$/{n++; next} n==1 && /^status:/{print $2; exit}' "$f"; done | sort | uniq -c | sort -rn
 278 open
 172 done
  19 dropped
```

The default lane, in full:

```console
$ python3 scripts/pytest_in_tree.py -m "not integration" -n 8 -q -p no:cacheprovider
........................................................................ [100%]
17581 passed, 3 skipped in 595.99s (0:09:55)
```

<sub>Two launcher lines that name local paths and the core-budget queue position are omitted.</sub>

`scripts/pytest_in_tree.py` is the repository's own wrapper for running a suite against one
tree: a venv synced to that tree's lockfile, the tree's `src` first on the path, and a
`DATABASE_URL` nothing listens on, as in CI's unit job. `-p no:cacheprovider` only keeps the
run from writing a cache into the tree. The run waited about two minutes in the machine's
core-budget queue and shared the machine with other heavy jobs, so its wall time **is not
comparable** with the 84 s the previous revision of this page published. The pass count is.

15,186 is the count of test *functions* in tracked files; 17,581 is what pytest **collects**
after parametrization, in the lane that excludes the Postgres- and Temporal-backed tiers.
Those two numbers are different things and are reported as different things.

Two counting rules, each of which produced a wrong number here once:

- Count over **tracked** files with a POSIX class, not `\s`. `git grep -E` does not implement
  `\s` — it is a GNU extension — and silently undercounts by roughly 300.
- Measure at a **pinned commit** on a clean tree, never on a working branch. Branch-local files
  move a headline.

Per-agent eval cases:

```console
$ for f in src/app/agents/skills/*/evals/dataset.yaml; do
    echo "$(basename $(dirname $(dirname $f))) $(grep -cE '^  - ' $f)"; done | sort -k2 -rn
food_agent 163
router_agent 138
query_agent 56
planning_agent 44
activity_agent 39
inventory_agent 31
raw_events_analyzer_agent 28
journal_agent 25
faq_agent 17
profile_agent 16
raw_events_agent 9
```

Against the previous pin:

| Agent | `85d65d2d` | `4fc9ea5e` |
|---|---|---|
| food_agent | 58 | 163 |
| router_agent | 92 | 138 |
| query_agent | 29 | 56 |
| planning_agent | 34 | 44 |
| activity_agent | 26 | 39 |
| inventory_agent | 21 | 31 |
| raw_events_analyzer_agent | 25 | 28 |
| journal_agent | 24 | 25 |
| faq_agent | 14 | 17 |
| profile_agent | 9 | 16 |
| raw_events_agent | 9 | 9 |
| **total** | **341** | **566** |

---

## 2. One request, end to end

The user forwards a meeting invite. The router assigns it
`planning_agent` / `calendar_event_log`. From that point, **no model is involved** until the
single EXECUTE decision — the bundle below is computed by `expand_intent`, which is pure code.

```console
expand_intent(Intent("calendar_event_log"), has_media=False).model_dump(mode="json")
{
  "domain": "planning_agent",
  "intent": "calendar_event_log",
  "skill_fragments": [
    "planning_agent/SKILL.md", "log_calendar_event", "correct_planning",
    "reuse_recent_tasks", "memory", "interactive_questions", "memory_offer"
  ],
  "allowed_action_kinds": [
    "create_calendar_event", "update_calendar_event",
    "create_agent_memory", "update_agent_memory", "deactivate_agent_memory", "ask_user"
  ],
  "allowed_effect_tools": [
    "create_calendar_event", "update_calendar_event",
    "create_agent_memory", "update_agent_memory", "deactivate_agent_memory", "ask_user"
  ],
  "read_tools": ["search_calendar_events", "search_tasks", "search_agent_memories"],
  "context_blocks": [
    "time", "replied_to", "predecessor_handoff", "language",
    "recent_tasks", "agent_memories", "conversation"
  ]
}
```

`ask_user` is last in both lists because no bundle names it: `expand_intent` appends the
universal actions (today only `ask_user`) to every plan, unless the bundle opts out.

`resolve_plan` rehydrates that into typed objects and composes the prompt:

```console
action_kinds:       ('create_calendar_event', 'update_calendar_event', 'create_agent_memory',
                     'update_agent_memory', 'deactivate_agent_memory', 'ask_user')
allowed_effect_tools: frozenset({'create_calendar_event', 'create_agent_memory',
                     'deactivate_agent_memory', 'update_calendar_event',
                     'update_agent_memory', 'ask_user'})
read_tools:         ['search_calendar_events', 'search_tasks', 'search_agent_memories']
context_blocks:     ['time', 'replied_to', 'predecessor_handoff', 'language',
                     'recent_tasks', 'agent_memories', 'conversation']
skill:              12,613 characters
```

<sub>`frozenset` print order depends on hashing; the six members are what the line shows.</sub>

Note what is **not** in that list. No `log_meal`. No `run_readonly_sql`. No
`search_recent_meals`.
The model deciding this request cannot see them, is not offered them, and — per §3 — cannot
reach them if it names them anyway.

**After the decision.** EXECUTE returns typed actions; each action's adapter turns them into
`PlannedToolCall(tool_name, input)` — which is what §3 checks. A surviving call dispatches to
the typed effect tool, which validates its input against a Pydantic contract, **forces
`user_id` from the request scope rather than accepting it from the model**, writes, and
records a `change_log` entry on any update. 836 such calls had executed in production by the
2026-08-17 read in [§8](#8-production).

One real decision payload appears in [§8](#8-production) — captured from the trace that
became BR-027. Full inbound-to-row captures are not published here, because a real trace
carries a real person's message, and no production record content appears anywhere in this
repository.

---

## 3. The guard, exercised

[`guard.py`](../code/src/app/agents/common/guard.py) run against the resolved bundle above:

```console
in-bundle action + in-bundle tool      -> None
out-of-bundle action                   -> disallowed_action:log_meal
in-bundle action, out-of-bundle tool   -> disallowed_effect_tool:run_readonly_sql
universal action (ask_user)            -> None
no actions at all                      -> empty_actions
ask_user on raw_event_log (opted out)  -> disallowed_action:ask_user
```

A non-`None` return is `FAILED_TERMINAL` for the whole decision. Nothing is written, so
"no partial writes" is a property of the structure and not of a rollback path.

The fourth and sixth lines are the same action against two plans. The guard has no allow-list
of its own: it admits exactly the action kinds the resolved plan carries. `ask_user` passes on
the calendar plan because `expand_intent` put it there, and it is refused on `raw_event_log`,
one of the two raw-events bundles that opt out of the universal actions.

Third case first: the action was legitimate and the *tool* was not. Two barriers, because a
single one keyed on action kind would let a valid action carry an invalid call.

---

## 4. The plan-scope check, exercised

Between plan and guard sits a third thing the architecture chapter used to omit:
`resolved_plan_scope_mismatch` re-derives the canonical plan from the intent and compares it
against the plan actually in hand, field by field.

```console
untampered            -> None
wrong intent          -> plan_domain:food_agent:expected_domain:planning_agent
dropped context block -> plan_context_blocks:time,replied_to,predecessor_handoff,language,
                         recent_tasks,conversation:expected_context_blocks:time,replied_to,
                         predecessor_handoff,language,recent_tasks,agent_memories,conversation
extra skill fragment  -> plan_skill_fragments:…,interactive_questions,memory_offer,memory:
                         expected_skill_fragments:…,interactive_questions,memory_offer
extra effect tool     -> plan_serialized_mismatch
extra read tool       -> raised KeyError: 'search_meals'
```

And one more line from the same run, with a read tool that does exist, FoodAgent's:

```console
extra read tool (registered) -> plan_read_tools:search_calendar_events,search_tasks,
                                search_agent_memories,search_recent_meals:expected_read_tools:
                                search_calendar_events,search_tasks,search_agent_memories
```

The effect-tool line and the two read-tool lines are the interesting ones.

**`extra effect tool` → `plan_serialized_mismatch`.** No specific check caught it. Appending
`log_meal` to the serialized plan's `allowed_effect_tools` does not change the *resolved*
effect-tool set, because resolution derives that set from the resolved actions rather than
from the list. Only the closing `model_dump` comparison — the one that exists for drift no
specific check anticipated — sees the difference. The fallback is load-bearing, not
decorative, and this is what proves it.

**`extra read tool` → `KeyError`.** `search_meals` is not a read tool in any domain. Read
tools are rehydrated from one global index, so a name that does not exist cannot be
rehydrated at all, and this fails closed one layer earlier, by exception rather than by
verdict. Honest limitation: for an unknown name that path returns a stack trace, not a
diagnosable mismatch string. A real read tool from another domain does rehydrate, and the
specific read-tool check then names it, as the extra line shows.

---

## 5. The SQL validator, exercised

[`readonly_sql.py`](../code/src/app/db/effects/readonly_sql.py), the first of the three
layers described in [chapter 04](04-security.md):

```console
PASS   select date_trunc('week', started_at) as wk, sum(duration_min)
       from query_activities group by 1 order by 1
REJECT select 1; drop table meals
       → exactly one statement is allowed
REJECT update query_meals set kcal = 0
       → only SELECT / WITH ... SELECT is allowed
REJECT select * from meals
       → table not in the allowed view set: meals
REJECT select pg_read_file('/etc/passwd')
       → function not allowed: pg_read_file
REJECT select version()
       → function not allowed: current_version
REJECT select * from pg_catalog.pg_user
       → qualified table reference not allowed: pg_catalog.pg_user
REJECT SELECT/*x*/ * FROM  "meals"
       → table not in the allowed view set: meals
REJECT select * from query_meals m join users u on u.id = m.user_id
       → table not in the allowed view set: users
```

Three of those are the reason this is an AST walk and not a regex. `SELECT/*x*/` puts a
comment where a pattern expects whitespace. `"meals"` quotes the identifier. `pg_catalog.`
qualifies it. All three defeat a pattern match and none of them survive a parse.

`select version()` shows the subtlety that made the allow-list work at all: sqlglot
canonicalizes `version()` to `current_version`, so the rejection names the canonical form, not
what was typed. Keying an allow-list off the typed text would have compared the wrong string.

The model only ever sees `query_*` views. Those views project columns and carry the user
scope; `users` is not among them, which is why the join in the last line is refused rather
than merely returning nothing.

---

## 6. A production defect the eval suite could not see

**BR-022.** The best single illustration of what the eval apparatus is for, including its
failure.

**Symptom.** A calendar event on production whose stored `raw_input` was 335 characters
against a 1,220-character inbound message.

**What happened.** The user forwarded a Google Meet invite: header, date, timezone, video
link, dial-in numbers, then — after a blank line — a block of ten interview questions. The
router emitted one `planning_agent` / `calendar_event_log` route whose `fragment` was the
335-character header alone. The question block was dropped and routed nowhere.

**Where it was not.** No code truncates anything: `_build_prompt` passes the text whole, and
`create_calendar_event` faithfully persists what it is given
(`raw_input=input.raw_input or context.fragment`). Principle 7 — *preserve the user's raw
input* — was honored by the agent and defeated upstream by the router. The router prompt
defined a fragment as the "verbatim slice" for a domain and never said that supporting detail
attached to an item (links, dial-ins, agendas, quoted blocks) belongs to that item's slice
even when it states no action of its own.

**Why it stayed invisible.** `ExpectedRoutes`, the evaluator guarding router behavior, compares
`(agent, intent)` and nothing else. Fragment text was written down in `dataset.yaml` and never
asserted. Every eval passed, continuously, while the router silently shortened fragments.

**Measurement.** Isolated probe against the unmodified prompt: **0/5**. After a "leave no text
behind" rule plus a worked example: **5/5**, fragment length equal to full message length.

**Structural fix.** A new `RouteFragmentContains` evaluator asserting fragment *coverage*,
whitespace- and case-insensitive so re-wrapping still passes while a dropped block fails, plus
the `routes_forwarded_invite_keeps_appendix` golden case. The next regression of this shape is
caught by the gate rather than by noticing a short string in production.

**The part worth more than the fix.** The same regeneration invalidated an earlier flake
attribution. `splits_food_and_activity` had been recorded as 65/66 with the failure
"root-caused to a transient host-login token race … re-verified 5/5 clean." A baseline probe
on the untouched prompt scored **3/5**. The attribution was wrong. The split was always
correct; bare «сходил в зал» was coin-flipping between `workout_log` and `activity_log`
because the prompt never said whether visiting a training venue is itself a workout. Stating
the rule, and re-probing each side of the widened boundary at 5/5, fixed it — pinned by
`routes_bare_gym_visit_as_workout`.

Two lessons, both kept: a passing suite is evidence about what it asserts and nothing more,
and "transient" is a conclusion that requires a controlled baseline, not a re-run.

---

## 7. Four defects, unabridged

436 entries at this pin; four that show different muscles. Each carries the symptom, the evidence that
localized it, the exact seam, and the fix.

### BR-064 — a determinism violation in workflow code

- **Found:** 2026-07-28, repository cleanup audit · **Severity:** high · **Status:** fixed
- **Seam:** `src/app/workflows/main_message_routing.py`

The concurrent route scheduler called `asyncio.wait` inside sandboxed Temporal workflow code.
Temporal warns rather than fails, and the warning can become a **replay failure** later —
after the history exists, when the workflow is no longer replayable and the failure is not
attributable to the change that caused it.

Fixed with a deterministic task list under `workflow.wait(..., return_when=FIRST_COMPLETED)`,
an **AST guard scoped to workflow modules**, and a replay of the recorded histories. The guard
is the part that matters: this class of defect is invisible to any test that only runs
forward.

### BR-021 — an orphaned event loop leaked one Postgres connection per agent run

- **Found:** 2026-07-09, production incident (`FATAL: remaining connection slots are
  reserved…`, recurring after two prior fixes) · **Severity:** high · **Status:** fixed
- **Seam:** `src/app/agents/common/graph.py`, `src/app/agents/router/graph.py`

Every agent decision called PydanticAI's `Agent.run_sync`. Its loop resolution mints a **new**
event loop when the thread has none, and `run_until_complete` never closes it. On Temporal
worker threads the ambient loop is always `None` — each surrounding sync activity runs
`asyncio.run`, which resets the thread's loop on exit — so **every decision minted a fresh
loop**. Any DB-touching read tool executed during that decision resolved a session on that
loop, registering a per-loop engine in a module-level registry that nothing disposed. The loop
then became unreachable while the registry kept the engine, and its pooled connections, alive
forever.

Arithmetic that localized it: ~14 orphaned idle connections per day, against a daily agent-run
count of 15/11/19/9/15/17 over six days. One per run, exactly. It reached 69 idle connections
in five days on a 100-slot shared instance.

The pre-existing guard could not see it. `test_activities_never_use_bare_asyncio_run` scans
`src/app/activities/**` for a literal `asyncio.run(`; here the loop is created *inside a
third-party library*, called from `src/app/agents/**`. The eval harness had already met the
same behavior and cleaned up after it — production had no equivalent.

Fixed by routing both decision paths through the same throwaway-loop-plus-dispose helper every
worker activity already used, guarded by
`test_agent_code_never_calls_pydantic_ai_run_sync`. Defense in depth: an idle session timeout,
and a connection census printed before each backup so the next near-ceiling event
self-diagnoses.

The transferable lesson is in the memory note this produced: **a mocked seam hides the
library's contract.** The stub for `run_sync` was faithful to its signature and silent about
its loop behavior.

### BR-053 — a privacy allow-list bypassed by cross-browser attribution

- **Found:** 2026-07-24, whole-application audit; independently reproduced · **Severity:**
  high · **Status:** fixed
- **Seam:** `clients/aw_pusher/{activitywatch,daybook_pusher,pipeline}.py`

The screen-time connector flattens every `aw-watcher-web-*` stream into one event list and
drops the source browser identity. Attribution then takes the first web event overlapping the
window block's start — without checking it belongs to the **active window's** browser. The
privacy filter trusts that attributed domain when deciding whether a window title may leave
the device.

The two-browser probe: an active Firefox window titled `Private Firefox title`, and an
overlapping Chrome tab on allow-listed `youtube.com`.

```text
{'app': 'Firefox', 'domain': 'youtube.com', 'title': 'Private Firefox title', ...}
```

The title left the device because a *different browser* was on an allow-listed domain. With
only the matching Firefox event present, the same title is correctly stripped — so the bug
reproduces only when two browser buckets overlap, which the single-web-stream test suite by
construction could not produce.

Fixed by carrying browser provenance through discovery, fetch, orchestration, and attribution,
and by failing closed everywhere the provenance is ambiguous: a uniquely identified browser
may contribute one overlapping domain; two conflicting domains resolve to *no* domain and
explicitly suppress the raw-URL fallback; the shared `chrome` token is rejected as
non-identifying. Absent a permitted fallback or an independent app allow, the emitted `title`
is `None`.

This one is a boundary, not a bug: the connector runs on the user's own machine, and the thing
being decided is what is allowed to leave it.

### BR-127 — a test that was passing by winning a coin flip

- **Found:** 2026-08-15, investigating a reported ~1-in-5 flake · **Severity:** medium ·
  **Status:** fixed (PR #266)
- **Seam:** `tests/workflows/test_interactive_question_callback.py` and
  `tests/workflows/test_main_message_interactive_reply.py`

Included because the finding is not the flake. The finding is that the assertion was wrong,
and that fixing the flake by relaxing a timeout would have preserved the error.

Both tests assert `timeout.type == TimeoutType.SCHEDULE_TO_CLOSE` on a handoff activity no
worker ever claims. The call passes `schedule_to_close_timeout` and leaves
`schedule_to_start_timeout` unset — so Temporal **derives the missing one from the budget**
and the scheduled event carries `sts = stc = 2s` for a 2 s injected budget. With no worker,
both deadlines expire on the same instant, and which one the server blames is a tie-break,
not a contract. It is not sensitive to the budget's size: `schedule_to_start ==
schedule_to_close` holds by construction at any value, including the two-minute production
constant.

Measured, at a 2 s injected budget: the time-skipping test server reported `SCHEDULE_TO_CLOSE`
or `SCHEDULE_TO_START` at random — **7 of 10** single-test runs failed the assertion on a
loaded host — while the real server reported `SCHEDULE_TO_START` **5 of 5**. The test was
passing by winning a coin flip, on the side production never lands on.

**Then the harder question: what did the assertion actually prove?** Its own comment claimed
it distinguished three regressions. Each was injected and measured:

| injected regression | old assertion |
|---|---|
| drop `schedule_to_close_timeout` (per-attempt bound only) | not caught cleanly — the workflow hangs forever |
| budget ignored (production constant instead of the injected value) | **passes**, only ~40 s slower |
| unbounded retry replaced by a single attempt | **passes** — byte-identical failure |

Two of the three it named were invisible to it. With no worker no attempt ever runs, so the
retry state is `TIMEOUT` whatever the retry policy is; "distinguishes an exhausted retry
policy" was never true in that scenario.

**It also corrected an earlier conclusion of mine.** These two tests had been recorded as an
environmental flake, on the strength of a stashed-baseline A/B that reproduced them on
untouched `dev`. That A/B was run correctly and proves exactly one thing — the change under
test did not cause it — which is not the same as "the host did". The question I had not asked
was whether it fails on a *quiet* machine. It does. The private note on flake attribution now
carries that correction above the technique it corrects.


---

## 8. Production

Small numbers, stated as they are. This is a personal system, not a product with traction;
at the pinned commit, production has one live user, its owner.

**Read from the production database on 2026-08-17; not re-read at this pin.** Window
2026-06-19 → 2026-08-16. Every production figure in this section, and in
[chapter 07](07-operations.md#what-it-actually-does-measured), is from that read.

| | |
|---|---|
| Registered users / who ever messaged / sustained (≥5 active days) | 14 / 13 / **4** |
| Active days | 51 |
| Inbound messages | 538 |
| Agent runs | 592 — 545 succeeded, 30 needs-user, 17 terminal (6 guard, 1 decision timeout, 1 read-tool cap, 1 materialization failure, 1 backfilled orphan, 7 with no error recorded) |
| Effect-tool calls | 836 |
| Records written | 317 meals · 259 activities · 210 episodes · 225 audited corrections |
| Automated raw events ingested | 2,670 |

Reply latency, inbound message to first sent reply:

```console
n    384
p50  16.0 s
p90  57.3 s
p95  79.9 s
```

Slow, and known why: at the time of the read the interactive path ran on a subscription-backed
CLI provider chosen for cost, not latency, and a mixed message pays for a router decision plus
one decision per domain, sequentially. Production has since moved its decision roles to the
metered Claude API key pool ([chapter 07](07-operations.md#cost-control)); latency has not been
re-measured for this page since. [Chapter 07](07-operations.md#what-it-actually-does-measured) carries
what would fix it and why it has not been prioritized for a logging tool.

**How often the guard fires**, split by which barrier. This groups on the structured fields
rather than searching the JSON as text, so the zero below is "no row carries that reason", not
"the substring did not appear":

```console
$ select coalesce(output->>'error','(none)'), coalesce(output->>'reason','(none)'), count(*)
    from agent_runs group by 1,2 order by 3 desc;

(none)                         | (none)                                       | 583
capability_guard_rejected      | empty_actions                                |   6
decision_timeout               | turn exceeded its 180s budget                |   1
decision_materialization_failed| lower_priority_source_selected               |   1
tool_rounds_exceeded           | read-tool invocation cap exceeded during turn |   1
```

Every `capability_guard_rejected` row carries `empty_actions`. `disallowed_action` and
`disallowed_effect_tool` — the two **scope** barriers — appear on no row at all: zero out of
592. The **empty-plan** barrier fired six times, five on FoodAgent and one on ActivityAgent,
none since 2026-07-15.

What that query does and does not establish: it is exhaustive over `agent_runs`, so no
rejection *recorded by an agent run* is missed. It cannot speak for a decision that never
reached `record_agent_run` — BR-032 was exactly that failure mode, and its one backfilled
orphan is in the terminal counts above.

That last date is not a coincidence. The sixth rejection, run `7ffed4e1`, **is** the trace
recorded as BR-027. The user answered FoodAgent's own clarifying question with a
counter-question. The model behaved correctly: it searched known nutrition, found nothing, and
answered from general knowledge — `{"assistant_message": "Из горячих сэндвичей Меркадоны
обычно бывают: … Какой из них твой?", "actions": []}`. The decision schema had no way to
express "just talk", so a helpful answer arrived with zero actions, and the guard did exactly
what it says: `empty_actions` → `FAILED_TERMINAL`, the model's text discarded, a generic
failure message sent instead.

The fix was not to loosen the guard. `finalize_node` now coerces a **question-shaped**
message-only decision onto the universal `ask_user` path, on any plan that carries it — the
model's own text reaches the user and the run ends `needs_user`, exactly as if it had emitted
`ask_user` itself. The
barrier is unchanged; what changed is that the model was given a legitimate way to say the
thing it was trying to say.

So the honest reading of these numbers: the guard's scope barriers are a backstop against a
decision no correct model has yet produced, which means **production traffic is not what
validates them**. The tests are:
[`test_common_guard.py`](../code/tests/agents/common/test_common_guard.py), and a snapshot
corpus that pins the serialized bundle of **all 29 intents in both media states — 58
snapshots** at this pin — so a silently widened plan fails a unit test instead of waiting for a model to
exploit it.

That snapshot test is also where the counting discipline shows up in the code. Its own comment
states the limit of what it proves:

> Pins the serialized `CapabilityPlan` […] It does NOT serialize `Action.codec_projection`;
> those are recovered at resolve time […] So this proves "identical `CapabilityPlan`", not
> "identical resolved plan including codec projections".

The uncovered part is named because a reader would otherwise assume it was covered.

---

## 9. The current strict gate

[Chapter 06](06-quality.md#a-recorded-run-knows-when-it-went-stale) argues that averaging
snapshots taken on different dates against different dataset versions is meaningless. That
argument only earns its keep if what is current is published instead, including when what is
current is less than one would like.

**At the pinned commit, `4fc9ea5e`, no agent has a current strict gate.** Every `--k 5`,
threshold 1.0 artifact in the repository was recorded on 2026-08-01 on
`codex_app_server:gpt-5.6-terra`, and every one now reads `stale`. The previous revision of this
page published eight of them as current, 245 cases and 1,225 case-runs at 1.00. Nothing has been
retracted and nothing has been re-run. The files are still on disk and still say 1.00. The agents
moved instead. The router went from skill 1.25.2 to 1.41.1 and from 92 cases to 138. The status
page now refuses those files as evidence about the current code. This is the mechanism doing its
job, and it is why this section opens with a negative.

What is current is a screen, run on the production lane.

**Production now calls the Claude API directly.** The committed production configuration puts
the decision, vision and summarizer roles on `anthropic`, a pool of Claude API keys, with the
subscription-backed `claude_cli` as each role's fallback when the pool cannot serve. The decision
model is `claude-sonnet-5-5` at effort `low`. The switch required a k=1 eval baseline per agent
on that provider. It did not require a strict gate.

**Eight agents are fresh on `anthropic:claude-sonnet-5-5`: a k=1 screen at threshold 0.00, run
2026-10-26.** The cases changed for the release were run twice more:

| Agent | Cases | k | Threshold | Pass rate | Attempts passed | Skill |
|---|---|---|---|---|---|---|
| query | 56 | 1..3 | 0.0 | 0.98 | 99 / 100 | 1.14.0 |
| planning | 44 | 1..3 | 0.0 | 1.00 | 50 / 50 | 1.14.0 |
| inventory | 31 | 1..3 | 0.0 | 1.00 | 33 / 33 | 1.11.0 |
| raw_events_analyzer | 28 | 1 | 0.0 | 0.96 | 27 / 28 | 1.16.2 |
| journal | 25 | 1 | 0.0 | 1.00 | 25 / 25 | 1.8.0 |
| faq | 17 | 1 | 0.0 | 1.00 | 17 / 17 | 1.3.1 |
| profile | 16 | 1..3 | 0.0 | 1.00 | 22 / 22 | 1.6.0 |
| raw_events | 9 | 1 | 0.0 | 1.00 | 9 / 9 | 1.2.1 |

226 cases, 284 attempts, 282 passed, $2.98 of recorded API spend. `1..3` is how the status page
writes an artifact whose cases were not all run the same number of times: every case once, some
three times. `k` is the minimum, so nothing beyond one attempt is guaranteed for any case.

The two misses are one attempt each:

- `query_agent` / `mvp_query_typo_kakao`: the agent appended a "no nutrition goal set" line to a
  plain day-total question, which its skill forbids. This is BR-432, open, measured earlier at
  about one turn in ten on the subscription lane.
- `raw_events_analyzer_agent` / `screen_multi_segment_work_merges_into_one_ru_summary_episode`:
  0 of 1. The previous anthropic screen of the same skill version (2026-10-17) scored 1.00.

The strict check, run read-only against these artifacts, refuses all eight and says why. Here is
one line from it, verbatim:

```text
INELIGIBLE agent=journal_agent model=anthropic:claude-sonnet-5-5 pass_rate=1.0000 cases=25/25 k=1 floor=1.0000 invocation_threshold=0.0000
- k too low: recorded 1, required at least 5
```

`query_agent` and `raw_events_analyzer_agent` are also refused for the case below the floor. The
old router artifact from the previous revision of this page is refused on identity before
anything else:

```text
INELIGIBLE agent=router_agent model=codex_app_server:gpt-5.6-terra pass_rate=1.0000 cases=92/138 k=5 floor=1.0000 invocation_threshold=1.0000
- identity sub-hashes are required for eligibility: harness_hash, agent_runtime_hash, agent_domain_code_hash, skill_content_hash, dataset_cases_hash, evaluator_contract_hash, evaluator_dependencies_hash
- dataset hash mismatch
- skill version mismatch: recorded '1.25.2', current '1.41.1'
- content hash mismatch
- evaluation contract hash mismatch
- case_count mismatch: recorded 92, current 138
(20 per-case assertion-key lines omitted)
```

One artifact, whole, so the freshness claim can be checked rather than taken on trust:

```json
{
  "agent":                       "journal_agent",
  "skill_version":               "1.8.0",
  "content_hash":                "sha256:d262227c3ad820890c24733c3283754fe7d404785bce87e1cc3d233a610e45bc",
  "dataset_hash":                "sha256:ce2c32be8c5f2d7622b949db761586ddf7c4d570b560fdb5c62ce0341b597722",
  "evaluation_contract_hash":    "sha256:f6e2d26e06d8a26d390f6f94a7db2429370f3c577b97ac72639a7d86efadd9c8",
  "harness_hash":                "sha256:85b61f9f0689e7350418655eafd369c30bc4b2a9365a77fe9c1088fdfbd53b72",
  "agent_runtime_hash":          "sha256:ca13858ccda7937fed3ee018a5505fb6e6fa12d88cafb975ee56695e96cebfec",
  "agent_domain_code_hash":      "sha256:d96c1dfd2e45aff2ffb5eba152fd854a58bcb4c12da855dde3293cdc86d4f13f",
  "skill_content_hash":          "sha256:0d0165cf9551f8215b928cdf4b62157bcb7497f64445972c27096425467331d2",
  "dataset_cases_hash":          "sha256:1e16c973977767385fc5a41f2f21c7fff13c37514fdefd214216b9d8e0b243b7",
  "evaluator_contract_hash":     "sha256:ce31331c4ad3ec9b84eb92066a273b871b7c7e005eb79f033f6f57ec7c170676",
  "evaluator_dependencies_hash": "sha256:dd450fd047de5f2f11b95126b1694805b503f99656daacd2f7f7230e48d93662",
  "execution_profile_digest":    "sha256:8c1d969ce13aee5e2360e009801139e077ae05c2db5ca191e4ce1eb4374c0fae",
  "case_count":                  25,
  "model":                       "anthropic:claude-sonnet-5-5",
  "k":                           1,
  "threshold":                   0.0,
  "ran_at":                      "2026-10-26T03:57:21Z",
  "pass_rate":                   1.0
}
```

The seven hashes between `evaluation_contract_hash` and `execution_profile_digest` are what the
freshness verdict now compares; [chapter 06](06-quality.md#a-recorded-run-knows-when-it-went-stale)
says how.

### Three things this does not say

**It is not a strict gate.** A k=1 screen at threshold 0.00 is a different instrument from k=5
at a floor of 1.0, and it is labelled as one. Reporting the 1.00 rows without that distinction
would be the exact move [chapter 06](06-quality.md) refuses. On `anthropic` every attempt is
billed per token, and the scope guard refuses a single run above `--k 4`. Five attempts are
reached by accumulating runs (1 + 1 + 3), and every attempt counts. This screen stopped at one
attempt for most cases and at three for the changed ones. The eval harness's default provider
is still `claude_cli` until a planned flip, and the CI job that would run real-model evals is
switched off for cost. Until a k=5 run lands on the production lane, the
honest summary is "screened, not gated".

**Three agents are not in it, FoodAgent among them, and it is the hardest one.** `activity_agent`,
`router_agent` and `food_agent` have no fresh row on any provider. Their newest anthropic screens
(2026-10-17) read `stale: prompt+dataset`. All three own canonical conversation fixtures, and the
gate's run-level guard refuses them under the default read mode, so re-running them needs a
coordinated environment rather than one more command. FoodAgent now has 163 cases. Its last screen,
148 cases against a skill version that has since moved, scored 0.97 (246 of 252 attempts). Five
of the six cases that missed are on the ledger under three open entries (BR-402, BR-403,
BR-404). BR-073, which the previous revision cited as open, was fixed on 2026-09-01. The case
went from 0.40 to 1.00 at k=5 after a prompt change, with its assertions unchanged.

**Fresh is a claim about inputs, not about the world.** The verdict now covers code as well as
prompts and data: the agent's own code, the shared agent runtime, the eval harness, and the
evaluators and their dependencies. An agent nobody touched therefore goes stale when a shared
module moves. What it still cannot see is a provider changing the model behind a stable name.
The execution profile is recorded but deliberately not compared. That is a real limit of
hash-based freshness, and it is why the evidence is re-run when an agent changes rather than
treated as permanent.

---

[← back to the overview](../README.md)
