# 10 · Guards

[← back to the overview](../README.md)

A test proves a thing works. A guard proves a *class of thing* cannot silently stop working —
and it is the only kind of check that survives the author forgetting why it was written.

**29 guard test files, 9,085 lines. Fifteen CI jobs across three workflows, every
pull-request-blocking one path-filtered — asserted by a test rather than by convention. Three
hooks registered by the repository itself.** The generic half of the tooling — the bug
ledger, documentation budgets, the design trail, plan lint, commit attribution — moved out in
October 2026 to `stayfixed`, a separately published harness CLI pinned at an exact version
and hash; what stays in the tree is specific to this project.

One rule organizes all of it: **a guard is added at the seam, not at the symptom**, and each
one names the incident that created it. None of the guards below is speculative — every row
has a defect behind it.

## Four things worth guarding

| | Guard | What it makes impossible | What created it |
|---|---|---|---|
| **The model** | `capability_guard_rejection` | An action or effect tool outside the resolved plan | [chapter 02](02-agent-architecture.md) — the whole design |
| | `resolved_plan_scope_mismatch` | A *plan* that arrived widened, before the guard above ever runs | The gap in plan-then-guard |
| | decision / empty-actions guards | A decision that authorizes nothing being written as if it did | BR-027 |
| | `KcalMacroGuard`, explicit-unit, read guards | Domain-specific nonsense: impossible macros, a unit the user never gave | One defect each |
| | ownership guard (`require_owned`) | An effect tool touching a row that belongs to another user | Made shared so one fix covers every tool |
| **The code** | workflow determinism (AST) | `asyncio.wait` inside Temporal workflow code | BR-064 |
| | read-only surface snapshot | A view added to the analytical surface without a reviewed decision | The RLS policy would be silently invalid |
| | analytical-SQL drift | The prompt documenting a view or function the validator rejects | Two live bugs at once |
| | migration head | Two heads merging into an unrunnable chain — checked on each pull request *and* again on `dev` after every merge | Two pull requests, each single-headed on its own merge ref, forking the graph once both landed |
| | workflow-expression scan | A workflow file GitHub refuses to load, which runs zero jobs and reports nothing | BR-211: a broken `ci-cd.yml` leaves every later pull request with no checks at all, so the scan runs from a *different* workflow |
| | self-hosted runner guard | A job that a pull request can trigger running on the runner that sits on the production machine | A computed `runs-on` once slipped past a substring check; computed labels now fail closed unless audited |
| | `pyright` over `scripts/` | An undefined name in the hook layer | A half-written edit that made a hook exit 2 and broke every tool call on the machine |
| **The documents** | `stayfixed docs check` | An always-loaded index growing without limit; a link to a file that does not exist | [chapter 09](09-governance.md) |
| | `stayfixed bugs check` | An entry that does not parse, a stale index, a `BR-nnn` cited in code with no entry | The ledger split |
| | `scripts/debt_ledger.py check` | A debt entry pointing at a moved file, or still waiting on blockers that have all closed | Debt harvested from PR bodies after the fact, instead of filed where it was found |
| | `stayfixed docs trail --check` | A generated design trail drifting from the documents it lists | A stale override silently marking unshipped work as delivered |
| **Me** | `stayfixed commit check` | An AI or tool attribution trailer reaching history | A policy that is worthless if it depends on remembering |
| | eval-scope `PreToolUse` hook | An unscoped, over-wide, or production-pointed paid model run | An advisory version was read straight past, at real cost |
| | `local_ci_checks.py --hook` | Pushing with a CI-blocking check stale; `git add` of a directory holding untracked files | A red PR found too late; a sibling session's work published by a directory add — twice in one session |
| | hosted-fallback refusal | Pull-request CI silently billing hosted minutes because the local runner pool is offline | One day, 34 pull-request runs fell back to hosted runners: about 720 billed minutes |

## The one that reads best in full

Twenty-eight lines, and it closes a class of defect that no forward-running test can see:

```python
def test_workflow_modules_do_not_use_asyncio_wait() -> None:
    violations: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "asyncio"
                    and node.func.attr == "wait"):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == [], (
        "Temporal workflow code must use workflow.wait(), not asyncio.wait(): "
        + ", ".join(violations))
```

`asyncio.wait` in a Temporal workflow does not fail. It warns, and then it becomes a **replay
failure later** — after the history exists, on a workflow nobody is looking at, attributable
to nothing. A unit test cannot catch that, because the code under test runs correctly the
first time. Parsing the module and refusing the call is the only check that fires before the
history is written. [BR-064](EVIDENCE.md#7-four-defects-unabridged) is the entry.

## A guard that pins prose against code

QueryAgent's prompt documents, in English, which `query_*` views and SQL functions the model
may use. `validate_readonly_sql` is the runtime allow-list. Nothing kept the two in sync, and
two defects came out of that gap at once: a validator that **rejected the prompt's own worked
example**, and a column the prompt documented that the view never selected.

The guard parses the prompt and asserts every documented view and function is a subset of what
the validator allows — and runs the prompt's worked example through the real validator. A
prompt is a program's input; it is checked like one.

## A snapshot that has to be widened deliberately

```python
_APPROVED_READONLY_TABLES = frozenset({"meals", "activities", "workouts", "tasks", ...})

def test_rls_tables_match_approved_snapshot() -> None: ...
def test_every_rls_table_has_user_id_column() -> None:
    # The RLS policy is `user_id = current_setting('app.user_id', true)::uuid`,
    # so each allow-listed base table MUST have a user_id column or the policy is invalid.
```

The first test makes widening the analytical surface a deliberate act with a diff. The second
is the one that matters: a table reachable through a view but lacking `user_id` gets an RLS
policy that **cannot be true**, which is a cross-tenant read presented as a working feature.
The guard turns that from a review question into a failing test.

## CI is path-gated, and the local mirror knows what CI will skip

Every pull-request-blocking job is gated on a path filter — `test_every_pr_blocking_ci_job_is_path_gated`
is what keeps that true — so a documentation change does not run mypy and a frontend change
does not run the Python suite. That is ordinary. What is not ordinary is the mirror.

`scripts/local_ci_checks.py` is **4,422 lines**, and it reproduces CI's filters rather than
approximating them:

- `--run` runs the CI-blocking checks, **skipping any whose inputs have not changed since they
  last passed and any this branch cannot reach** — and it *names both sets* rather than
  skipping silently. A check that vanishes without saying so is worse than one that runs.
- `--changed` is the inner loop: only the tests reachable from what changed — through the
  import graph for Python, through the tests that name a document, workflow or script
  otherwise. It falls back to the whole suite whenever it cannot reason — a `conftest.py`, an
  unparsable module, a path no test names — and **never records a pass**, because a static
  import graph cannot see a dynamic import.
- The unit lane runs under a `DATABASE_URL` nothing listens on, because CI's unit job has no
  database and a test that quietly reaches the local one passes here and fails there.

**And the mirror has its own guard: 264 tests, 8,688 lines** over the whole mirror script,
including a pair that pins the local check list against CI's actual job and filter definitions. That pair is the interesting part.

`test_every_ci_blocking_check_is_mirrored_locally` is the obvious direction. Its converse,
`test_local_checks_do_not_invent_checks_ci_does_not_run`, is the one people forget: the
Postgres tier is *deliberately absent* from the CI mirror, because CI does not run it on a pull
request, and mirroring it there would report it as CI-blocking when it is a repository policy.
It lives in a separate policy tier with tests of its own asserting exactly that separation.

A guard that overstates its own coverage is the failure mode this whole chapter is about, so
the mirror is guarded against it in both directions.

CI makes one narrower bet of its own. A pull request whose every changed file is a contract
document, a hand-mirrored TypeScript source, an infra file or harness configuration runs only
the tests that read those files, not the whole suite. A static selector is trusted there
because it is audited: every full unit run records each file a test opens and fails if the
selector's answer for that file would have left a reader out.

## Guards that fire when the decision is made, not when the code is written

CI checks a change after it is written. Some decisions are made and paid for before that, and
a guard placed at the wrong moment cannot help. Three hooks are registered by the repository
itself, and two are worth reading.

**Before a paid model run.** A `PreToolUse` hook watches for the eval entry points
(`app.evals.gate`, `app.evals.run`, `app.evals.probe`) at the moment the command is about to
launch. It began as advice: it printed the scoping rule and **never denied**. Then a
dispatched subagent read straight past that advice and ran a blanket `--agent <domain> --k 5`
at real cost — so it now denies. It refuses a run that is unscoped, widened to several agents
without a scope file, above the `k` cap of the entry point it names (counting the CLI's own
default when the flag is absent — reading only the spelled-out flag once let the most
expensive shape through), or pointed at a database it cannot prove is local.

What survived from the first version is the restraint, stated in its docstring: it fires only
on a real invocation, and stays silent for the free structural modes and for a run already
scoped to explicit cases against a local database — *because this repository already removed
an always-on hook of the same kind for being noisy*. A guard that fires on ordinary work gets
disabled, and then it protects nothing. Denying narrowly is not the same as denying often.

**At session start.** An environment fingerprint reports lockfile drift, host load, and stale
test-database DDL. It exists because three separate failures on one long run cost hours and
produced wrong conclusions, each because the environment silently differed from CI:

| what had drifted | what it cost |
|---|---|
| 98 of 222 packages off the lockfile | 11 test failures misattributed to code across three investigations; one commissioned a fix for a defect that did not exist |
| 12 orphaned processes at ~680% CPU on a 10-core host | every timing measurement taken while they ran; killing them made the unit suite 45% faster with no config change |
| 164 stale test databases stamped at head with old DDL | 182 of 183 database failures |

The rule that made it mandatory is in its header: finding *one* drifted package and fixing only
that one, without asking what else had drifted, **is the actual failure mode**. So it always
reports the full count and the full list, never the first mismatch. And it never blocks — a
`SessionStart` hook that exits non-zero can kill every prompt in the session, so it reports and
exits 0 whatever it finds.

**Local convenience, authoritative gate.** A `prepare-commit-msg` hook strips attribution
trailers before the message is even presented — chosen over `commit-msg` deliberately, because
`git commit --no-verify` bypasses that one and not this one. It is still only convenience. The
authoritative check runs in CI in two halves: one over every pull request's whole
`base..head` range, including a hotfix based on `main`, and a separate workflow watching
direct pushes to `dev` and `main`. The second half exists because the main pipeline
restricts `push` to `main`, which would leave a commit pushed straight to `dev` with no run
at all — and once it is there it sits below the base of every later pull-request range and
is never revisited. It once watched every branch; feature-branch pushes were 237 of 281 push
runs in a fortnight and pure duplication, since their commits cannot reach a permanent branch
except through a checked pull request, so they were dropped. A test asserts both halves
together, in both directions.

## Where the guards stop

Every guard here has a list of what it does not catch, written down next to it rather than
discovered later. The defect ledger's is eight items long. The sharpest is not about the tool at
all — it is a gap in **CI's own path filters**: an identifier added under `scripts/`,
`clients/`, `infra/`, `.github/`, `frontend/` or the repository root reaches the local check
but not the CI one, so it merges green and surfaces on somebody else's pull request. Cause, consequence and fix are
recorded; the fix is a path filter that has not been written yet.

Documentation hygiene does not validate `#fragment` anchors. And moving the attribution check
into the shared harness CLI narrowed what it refuses: it now judges only `-by:` trailers in
the message's closing block, naming a known product or a vendor's own mail domain, so several
forms the old in-repository script rejected now pass. That was accepted as a trade, and the list of forms that pass is written in
the workflow beside the step rather than discovered later.

Naming a blind spot costs one sentence. Leaving it unnamed converts it, eventually, into
somebody's afternoon.

---

[← governance](09-governance.md) · [next: roadmap →](11-roadmap.md)
