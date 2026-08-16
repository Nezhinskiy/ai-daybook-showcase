# Evidence

[← back to the overview](../README.md)

Output, not description. Every block below is something a command printed, pasted verbatim.
Measured at commit `85d65d2d`, 2026-08-17, on a clean tree.

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
    8146
$ grep -rhoE "^\s*(it|test)\(" frontend/src | wc -l
     735
$ git ls-files tests | grep '\.py$' | tr '\n' '\0' | xargs -0 cat | wc -l
  302080
$ git ls-files src  | grep '\.py$' | tr '\n' '\0' | xargs -0 cat | wc -l
  169657
$ grep -cE "^class [A-Za-z]+\(Evaluator\)" src/app/evals/evaluators.py
57
$ grep -hcE "^  - " src/app/agents/skills/*/evals/dataset.yaml | awk '{s+=$1} END {print s}'
341
$ grep -rh '@workflow.defn' src/app/workflows/ | wc -l
      20
$ ls -1 alembic/versions/*.py | wc -l
      97
$ ls -1 docs/superpowers/specs/*.md docs/superpowers/plans/*.md | wc -l
     227
$ ls -1 docs/bugs/BR-*.md | wc -l
     141
```

The default lane, in full:

```console
$ python -m pytest -m "not integration" -n 8 -q
........................................................................ [100%]
8434 passed, 3 skipped in 83.86s (0:01:23)
```

8,146 is the count of test *functions* in tracked files; 8,434 is what pytest **collects**
after parametrization, in the lane that excludes the Postgres- and Temporal-backed tiers.
Those two numbers are different things and are reported as different things.

Two counting rules, each of which produced a wrong number here once:

- Count over **tracked** files with a POSIX class, not `\s`. `git grep -E` does not implement
  `\s` — it is a GNU extension — and silently undercounts by roughly 300.
- Measure at a **pinned commit**, never in a worktree. Branch-local files move a headline.

Per-agent eval cases:

```console
$ for f in src/app/agents/skills/*/evals/dataset.yaml; do
    echo "$(basename $(dirname $(dirname $f))) $(grep -cE '^  - ' $f)"; done | sort -k2 -rn
router_agent 92
food_agent 58
planning_agent 34
query_agent 29
activity_agent 26
raw_events_analyzer_agent 25
journal_agent 24
inventory_agent 21
faq_agent 14
raw_events_agent 9
profile_agent 9
```

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
    "reuse_recent_tasks", "memory", "interactive_questions"
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

`resolve_plan` rehydrates that into typed objects and composes the prompt:

```console
action_kinds:       ('create_calendar_event', 'update_calendar_event', 'create_agent_memory',
                     'update_agent_memory', 'deactivate_agent_memory', 'ask_user')
allowed_effect_tools: frozenset({'create_calendar_event', 'update_calendar_event',
                     'create_agent_memory', 'update_agent_memory',
                     'deactivate_agent_memory', 'ask_user'})
read_tools:         ['search_calendar_events', 'search_tasks', 'search_agent_memories']
context_blocks:     ['time', 'replied_to', 'predecessor_handoff', 'language',
                     'recent_tasks', 'agent_memories', 'conversation']
skill:              13,952 characters
```

Note what is **not** in that list. No `log_meal`. No `run_readonly_sql`. No `search_meals`.
The model deciding this request cannot see them, is not offered them, and — per §3 — cannot
reach them if it names them anyway.

**After the decision.** EXECUTE returns typed actions; each action's adapter turns them into
`PlannedToolCall(tool_name, input)` — which is what §3 checks. A surviving call dispatches to
the typed effect tool, which validates its input against a Pydantic contract, **forces
`user_id` from the request scope rather than accepting it from the model**, writes, and
records a `change_log` entry on any update. 836 such calls have executed in production.

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
```

A non-`None` return is `FAILED_TERMINAL` for the whole decision. Nothing is written, so
"no partial writes" is a property of the structure and not of a rollback path.

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
extra skill fragment  -> plan_skill_fragments:…,memory,interactive_questions,memory:
                         expected_skill_fragments:…,memory,interactive_questions
extra effect tool     -> plan_serialized_mismatch
extra read tool       -> raised KeyError: 'search_meals'
```

The last two are the interesting ones.

**`extra effect tool` → `plan_serialized_mismatch`.** No specific check caught it. Appending
`log_meal` to the serialized plan's `allowed_effect_tools` does not change the *resolved*
effect-tool set, because resolution derives that set from the resolved actions rather than
from the list. Only the closing `model_dump` comparison — the one that exists for drift no
specific check anticipated — sees the difference. The fallback is load-bearing, not
decorative, and this is what proves it.

**`extra read tool` → `KeyError`.** A read tool that is not registered for the domain cannot
be rehydrated at all, so this fails closed one layer earlier, by exception rather than by
verdict. Honest limitation: that path returns a stack trace, not a diagnosable mismatch
string.

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

141 entries; four that show different muscles. Each carries the symptom, the evidence that
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

Small numbers, stated as they are. This is a personal system with real users, not a product
with traction.

Read from the production database on **2026-08-17**; window 2026-06-19 → 2026-08-16.

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

Slow, and known why: the interactive path runs on a subscription-backed CLI provider chosen
for cost, not latency, and a mixed message pays for a router decision plus one decision per
domain, sequentially. [Chapter 07](07-operations.md#what-it-actually-does-measured) carries
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
message-only decision onto the universal `ask_user` path — the model's own text reaches the
user and the run ends `needs_user`, exactly as if it had emitted `ask_user` itself. The
barrier is unchanged; what changed is that the model was given a legitimate way to say the
thing it was trying to say.

So the honest reading of these numbers: the guard's scope barriers are a backstop against a
decision no correct model has yet produced, which means **production traffic is not what
validates them**. The tests are:
[`test_common_guard.py`](../code/tests/agents/common/test_common_guard.py), and a snapshot
corpus that pins the serialized bundle of **all 28 intents in both media states — 56
snapshots** — so a silently widened plan fails a unit test instead of waiting for a model to
exploit it.

That snapshot test is also where the counting discipline shows up in the code. Its own comment
states the limit of what it proves:

> Pins the serialized `CapabilityPlan` […] It does NOT serialize `Action.codec_projection`;
> those are recovered at resolve time […] So this proves "identical `CapabilityPlan`", not
> "identical resolved plan including codec projections".

The uncovered part is named because a reader would otherwise assume it was covered.

---

[← back to the overview](../README.md)

---

## 9. The current strict gate

[Chapter 06](06-quality.md#a-recorded-run-knows-when-it-went-stale) argues that averaging
snapshots taken on different dates against different dataset versions is meaningless. That
argument only earns its keep if a single current run is published instead. Here it is.

**Eight agents, `--k 5`, `--threshold 1.0`, pass rate 1.00** — 245 cases, **1,225 case-runs**,
run 2026-08-01 and still reported `fresh` by the hash mechanism at the pinned commit.

| Agent | Cases | k | Threshold | Pass | Skill |
|---|---|---|---|---|---|
| router | 92 | 5 | 1.0 | 1.00 | 1.25.2 |
| planning | 34 | 5 | 1.0 | 1.00 | 1.8.12 |
| activity | 26 | 5 | 1.0 | 1.00 | 2.12.4 |
| raw_events_analyzer | 25 | 5 | 1.0 | 1.00 | 1.13.0 |
| journal | 24 | 5 | 1.0 | 1.00 | 1.4.0 |
| inventory | 21 | 5 | 1.0 | 1.00 | 1.4.2 |
| faq | 14 | 5 | 1.0 | 1.00 | 1.2.0 |
| raw_events | 9 | 5 | 1.0 | 1.00 | 1.1.0 |

**It was ten agents three days ago.** The previous revision of this page published ten,
283 cases, 1,415 case-runs. `query_agent` and `profile_agent` have since dropped off it —
not because a run failed, but because their prompts moved and the freshness verdict followed.
Nothing was re-run and no result was retracted; the same two artifacts still sit on disk
reporting 1.00, and they simply stopped counting as evidence about the current code. That is
the mechanism working, and it is the reason this section is a table of eight rather than a
sentence about a matrix.

One artifact, whole, so the freshness claim is checkable rather than asserted:

```json
{ "agent": "router_agent", "skill_version": "1.25.2",
  "content_hash":             "sha256:1cae093f1685b1156d6f99cf77062396f416e7453bddffcae4f99c4b5424ffef",
  "dataset_hash":             "sha256:a06aedf7589ab878817d000f7b2094857a54dbb5805f9b9d9a9b1b88c7cf515c",
  "evaluation_contract_hash": "sha256:1e4d77a99341a373211f316d28e38b4dd13d1e0a2b7c7f0e7be7ab8ade232652",
  "execution_profile_digest": "sha256:e45d900fe72915ce74265c5ccde87bab6b11dfdb215581813b9496e5f2978cb9",
  "case_count": 92, "model": "codex_app_server:gpt-5.6-terra", "k": 5,
  "threshold": 1.0, "ran_at": "2026-08-01T09:04:48Z", "pass_rate": 1.0 }
```

### Three things this does not say

**It is not the production provider.** This gate ran on `codex_app_server:gpt-5.6-terra`, the
secondary lane, chosen because real-model runs are the project's largest discretionary spend
and the subscription-backed production lane is rate-limited rather than metered. On the
production lane — `claude_cli:claude-sonnet-5` — the current runs are **k=1 screening at
threshold 0.00**, not a strict gate:

| Agent | Pass (k=1 screen, 2026-08-06) | | Agent | Pass |
|---|---|---|---|---|
| faq · inventory · journal · raw_events · raw_events_analyzer | 1.00 | | router | 0.99 |
| planning | 0.97 | | activity | 0.92 |

<sub>`profile_agent` and `query_agent` also screened 1.00 on that date and have since gone
stale; `food_agent` screened 0.89 and is covered below.</sub>

A k=1 screen is a different instrument from a k=5 gate at threshold 1.0 and is labelled as
one. Reporting the 1.00 figures without that distinction would be the exact move
[chapter 06](06-quality.md) refuses.

**FoodAgent is excluded, and it is the hardest agent.** Every FoodAgent cell reads
`stale: prompt+dataset` — its skill has moved well past what any recorded run tested — so
none of its 58 cases are in the 245 above. Its most recent
production-lane screen scored **0.89 at k=1** against a skill version that no longer exists.
Two of its cases are on record as not reliably green at k=1 — BR-073, open.

**Fresh is a claim about inputs, not about the world.** The verdict compares the skill and
dataset hashes; a provider that has changed its model behind a stable name will not move
either. That is a real limit of hash-based freshness and the reason the gate re-runs on agent
change rather than on a schedule.
