from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
import sqlglot
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.db.effects.readonly_sql import (
    READONLY_VIEW_DEFS,
    READONLY_VIEWS,
    ReadonlySqlError,
    run_user_scoped_readonly_sql,
    validate_readonly_sql,
)
from app.db.session import AsyncSessionLocal
from app.domain_values import DomainAgentName, Intent
from app.models.activity import Activity
from app.models.food import Meal, RecipeBatch
from tests.db.effects._helpers import create_agent_run, create_user
from tests.db.factories import (
    add_seeded_meal,
    estimated_row,
    saved_batch_row,
    store_meal_composition,
)


def _projected_columns(select_sql: str) -> frozenset[str]:
    """The output column names of one view definition, or an empty set if unreadable.

    This derivation lives in test support because nothing on the execution path parses a
    view definition: ``_scoped_query`` interpolates each ``select_sql`` into a CTE verbatim,
    and ``validate_readonly_sql`` parses the *model's* statement while allow-listing view
    names. It used to sit in ``readonly_sql`` itself, where it cost every importer of the
    read-only-SQL security boundary ~2.5 ms of ``sqlglot`` parsing for a mapping the boundary
    never consulted. The input is still ``READONLY_VIEW_DEFS`` — the very tuple the views are
    built from — so the anti-drift guarantee is unchanged by the move.

    An unreadable definition returns empty rather than raising, so the failure surfaces in
    ``test_readonly_view_columns_is_derived_and_drops_the_gram_mirror`` by name rather than
    as a collection error with no view in it.

    ``read="postgres"`` is the dialect these definitions are written in and the one
    ``validate_readonly_sql`` reads model statements with. ``alias_or_name`` is the name the
    model sees: a qualified projection (``w.id``, ``a.title``) under its bare name.
    """
    try:
        parsed = sqlglot.parse_one(select_sql, read="postgres")
    except SqlglotError:
        return frozenset()
    return frozenset(str(projection.alias_or_name) for projection in parsed.expressions)


# The column surface each view exposes to the model, derived from the same definitions the
# views are built from so it cannot drift from them.
READONLY_VIEW_COLUMNS: dict[str, frozenset[str]] = {
    v.name: _projected_columns(v.select_sql) for v in READONLY_VIEW_DEFS
}


class _FakeResult:
    def keys(self) -> list[str]:
        return []

    def all(self) -> list[tuple[object, ...]]:
        return []


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.params: list[dict[str, object] | None] = []

    async def execute(
        self, statement: object, params: dict[str, object] | None = None
    ) -> _FakeResult:
        self.statements.append(str(statement))
        self.params.append(params)
        return _FakeResult()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; DROP TABLE meals;",
        "DELETE FROM query_meals",
        "UPDATE query_meals SET calories = 0",
        "INSERT INTO query_meals VALUES (1)",
        "SELECT * FROM meals",
        "SELECT content FROM journal_entries",  # base table, not the view
        "SELECT * FROM query_meals, users",
        "SELECT * FROM query_meals JOIN users ON true",
        "SELECT * FROM public.users",
        'SELECT * FROM "users"',
        "WITH u AS (SELECT * FROM users) SELECT * FROM u",
        "WITH users AS (SELECT * FROM users) SELECT * FROM users",
        "SELECT * FROM (SELECT * FROM users) u",
        "SELECT dangerous_function()",
        # Typed-node functions outside the analytical allow-list: sqlglot parses
        # these as typed nodes (not exp.Anonymous), so they must be gated by
        # canonical name, not only via the Anonymous path.
        "SELECT version()",
        "SELECT current_user",
        "SELECT current_database()",
        "SELECT generate_series(1, 1000000)",
        "SELECT md5('x') FROM query_meals",
        # Lexical-scope escapes: a same-named CTE in an INNER scope must NOT
        # whitelist a base-table reference in an OUTER scope (the global-cte-name
        # differential). All of these bind to base tables at runtime.
        "SELECT * FROM meals CROSS JOIN (WITH meals AS (SELECT 1 AS x) SELECT x FROM meals) z",
        "SELECT * FROM users CROSS JOIN (WITH users AS (SELECT 1 AS x) SELECT x FROM users) z",
        (
            "SELECT title FROM meals WHERE "
            "(SELECT x FROM (WITH meals AS (SELECT 1 AS x) SELECT x FROM meals) z LIMIT 1) = 1"
        ),
        "WITH x AS (SELECT * FROM meals) SELECT * FROM x",
        "SELECT id FROM query_meals UNION SELECT id FROM meals",
        "SELECT (SELECT count(id) FROM agent_memories) FROM query_meals",
        # Recursive CTEs are rejected outright (unbounded; not needed by the agent).
        "WITH RECURSIVE t AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM t) SELECT n FROM t",
    ],
)
def test_rejects_unsafe(sql: str) -> None:
    with pytest.raises(ReadonlySqlError):
        validate_readonly_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 FROM query_meals FOR UPDATE",
        "SELECT id FROM (SELECT id FROM query_meals FOR SHARE) AS m",
        "SELECT 1 WHERE EXISTS (SELECT 1 FROM query_meals FOR SHARE)",
    ],
    ids=["top_level", "subquery", "exists_body"],
)
def test_rejects_a_row_locking_clause_in_any_position(sql: str) -> None:
    """BR-351: a locking clause is refused by the parser, not left to the read-only transaction.

    Mutation: drop the `exp.Lock` rejection from `validate_readonly_sql`; every row passes."""
    with pytest.raises(ReadonlySqlError, match="row-locking clause not allowed"):
        validate_readonly_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT title, calories FROM query_meals WHERE calories > 500 LIMIT 10",
        (
            "WITH high AS (SELECT title, calories FROM query_meals WHERE calories > 500) "
            "SELECT * FROM high LIMIT 10"
        ),
        "SELECT count(*) FROM query_meals",
        "WITH meals AS (SELECT * FROM query_meals) SELECT * FROM meals",
        (
            "SELECT m.title FROM query_meals m "
            "JOIN query_activities a ON a.activity_date = m.meal_date"
        ),
        "SELECT emotion, COUNT(*) FROM query_journal_entries GROUP BY emotion",
        "SELECT STDDEV(intensity) FROM query_journal_entries",
        ("SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY intensity) FROM query_cbt_records"),
        (
            "SELECT t.name, COUNT(*) FROM query_note_tags nt "
            "JOIN query_tags t ON t.id = nt.tag_id GROUP BY t.name"
        ),
        # Review item 9: the analytical_sql.md example of its day used CURRENT_DATE and was
        # rejected, so current_date joined the allow-list. The example now writes dates as
        # literals (BR-285), but a model may still use the function and it must still pass.
        "SELECT SUM(calories) FROM query_meals WHERE meal_date = CURRENT_DATE - 1",
        ("SELECT COUNT(*) FROM query_journal_entries WHERE occurred_on >= CURRENT_DATE - 7"),
        # Boolean connectors (BR-232). sqlglot 30.x redeclared And/Or as
        # `class And(Expression, Connector, Func)` (25.x had `class And(Connector)`), so the
        # exp.Func walk began matching them and rejected every multi-predicate statement
        # with "function not allowed: and". This file previously contained no statement with
        # an AND or an OR anywhere, which is exactly why 62 green tests missed it.
        "SELECT COUNT(*) FROM query_meals WHERE calories > 100 AND calories < 900",
        "SELECT COUNT(*) FROM query_meals WHERE calories > 100 OR calories < 900",
        (
            "SELECT COUNT(*) FROM query_note_tags nt "
            "JOIN query_tags t ON nt.tag_id = t.id AND t.name = 'focus'"
        ),
        (
            "SELECT COUNT(*) FROM query_meals "
            "WHERE calories IS NOT NULL AND meal_date >= CURRENT_DATE - 30"
        ),
        (
            "SELECT title FROM query_meals "
            "WHERE (calories > 100 AND protein_g > 10) OR (calories < 50 AND fat_g < 5)"
        ),
        # Connectors outside WHERE: HAVING, and inside a CTE body.
        (
            "SELECT emotion, COUNT(*) FROM query_journal_entries "
            "WHERE intensity > 3 AND emotion IS NOT NULL "
            "GROUP BY emotion HAVING COUNT(*) > 1 AND SUM(intensity) > 10"
        ),
        (
            "WITH busy AS (SELECT id FROM query_activities "
            "WHERE duration_minutes > 30 AND focus_level > 2) SELECT COUNT(*) FROM busy"
        ),
        # Other operator forms that ride the same walk. sqlglot models these as plain
        # operator nodes today; if a later release moves one under exp.Func the way it
        # moved the connectors, the gate would start refusing it and these cases fail.
        "SELECT calories + protein_g * 2 FROM query_meals",
        "SELECT title || raw_input FROM query_meals",
        "SELECT title FROM query_meals WHERE NOT (calories > 100)",
        "SELECT title FROM query_meals WHERE title IN ('a', 'b') AND raw_input LIKE 'x%'",
        # XOR is the third exempted connector. The infix form `a XOR b` does not parse in
        # the postgres dialect, but the call form does and this change newly admits it; it
        # re-serializes as its AND/NOT/OR expansion, not as a call.
        "SELECT title FROM query_meals WHERE xor(calories > 100, protein_g > 10)",
    ],
)
def test_accepts_safe_reads_over_views(sql: str) -> None:
    validate_readonly_sql(sql)


@pytest.mark.parametrize(
    ("sql", "rejected_name"),
    [
        # Typed node on the right branch of an AND ...
        ("SELECT 1 FROM query_meals WHERE calories > 1 AND md5(title) = 'x'", "md5"),
        # ... and on the left branch of an OR (postgres canonicalizes version() to
        # current_version, which is why this asserts the canonical name).
        (
            "SELECT 1 FROM query_meals WHERE version() = 'x' OR calories > 1",
            "current_version",
        ),
        # exp.Anonymous (unrecognized name) behind a connector.
        (
            "SELECT 1 FROM query_meals "
            "WHERE calories > 1 AND pg_read_file('/etc/passwd') IS NOT NULL",
            "pg_read_file",
        ),
        # Two connector levels deep, inside a parenthesised branch.
        (
            "SELECT 1 FROM query_meals "
            "WHERE (calories > 1 AND (title = 'a' OR md5(title) = 'x')) OR calories < 5",
            "md5",
        ),
        # Behind a connector inside a CTE body.
        (
            "WITH x AS (SELECT id FROM query_meals "
            "WHERE calories > 1 AND md5(title) = 'x') SELECT COUNT(*) FROM x",
            "md5",
        ),
        # Inside the XOR call form, which is exempted like the other two connectors.
        (
            "SELECT 1 FROM query_meals WHERE xor(calories > 1, md5(title) = 'x')",
            "md5",
        ),
    ],
)
def test_disallowed_function_behind_a_boolean_connector_is_still_rejected(
    sql: str, rejected_name: str
) -> None:
    """Exempting the connectors must not stop the walk descending past them.

    ``match`` is load-bearing rather than decoration: before the connector fix every one
    of these statements raised too — for the connector itself ("function not allowed:
    and"). A bare ``pytest.raises(ReadonlySqlError)`` would have passed for the wrong
    reason and proved nothing about whether the operand is still name-gated.
    """
    with pytest.raises(ReadonlySqlError, match=f"function not allowed: {rejected_name}"):
        validate_readonly_sql(sql)


def test_only_the_boolean_connectors_are_exempt_from_the_function_gate() -> None:
    """Pin exactly which classes the ``exp.Connector`` exemption covers.

    The gate skips ``exp.Connector`` nodes because sqlglot models AND/OR/XOR as operators
    that merely happen to also inherit ``exp.Func`` since 30.x. Should a later sqlglot move
    a genuinely callable node under ``Connector``, that call would stop being name-gated and
    the security boundary would widen with no other test failing. This is the test that
    fails instead, naming the class that moved.

    The assertion is equality, so it fires on a reclassification in *either* direction — on
    sqlglot 25.x the set is ``{"Xor"}`` alone, because ``And``/``Or`` were not yet ``Func``
    subclasses. A downgrade is as much a reason to re-read the gate as an upgrade is; the
    version actually installed is pinned in ``uv.lock`` and CI installs with ``--locked``.

    All three members are also exercised through SQL above: the infix ``a XOR b`` does not
    parse in the postgres dialect, but the call form ``xor(a, b)`` does, and it is in both
    the accept and the reject corpora. This check is the structural complement to those,
    not a stand-in for a case that could not be written.
    """
    import sqlglot.dialects  # noqa: F401  # dialects can define further exp.Func subclasses

    def _descendants(root: type) -> set[type]:
        seen: set[type] = set()
        stack = [root]
        sub: type
        while stack:
            for sub in stack.pop().__subclasses__():
                if sub not in seen:
                    seen.add(sub)
                    stack.append(sub)
        return seen

    exempt = {c.__name__ for c in _descendants(exp.Func) if issubclass(c, exp.Connector)}
    assert exempt == {"And", "Or", "Xor"}, (
        "sqlglot reclassified an exp.Connector/exp.Func node; re-read the function gate in "
        f"validate_readonly_sql before accepting this set: {sorted(exempt)}"
    )


def test_connector_nodes_always_serialize_as_operators() -> None:
    """Why exempting the node type is safe where allow-listing the *name* would not be.

    ``validate_readonly_sql`` returns the re-serialized tree, and that string is what
    executes. sqlglot parses even an explicit ``"and"(1, 2)`` call into an ``exp.And``,
    which can only ever render back as the ``AND`` operator — so an exempted node cannot
    smuggle a call onto the execution path. Adding "and"/"or" to ``_ALLOWED_FUNCTIONS``
    instead would have let an ``exp.Anonymous`` that merely happens to be named "and"
    through the gate.

    ``Xor`` is the reason this asserts "renders as boolean operators" and not "renders as
    its own operator": the call form expands into ``AND``/``NOT``/``OR`` rather than back
    into an ``XOR``. The property the gate relies on is that no exempted node emits a
    call, which holds for the expansion too.
    """
    assert validate_readonly_sql('SELECT "and"(1, 2) FROM query_meals') == (
        "SELECT 1 AND 2 FROM query_meals"
    )
    assert validate_readonly_sql("SELECT xor(1, 2) FROM query_meals") == (
        "SELECT (1 AND (NOT 2)) OR ((NOT 1) AND 2) FROM query_meals"
    )


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        # BR-233: CASE and EXISTS are SQL syntax that sqlglot models as exp.Func subclasses
        # (exp.Case, the exp.If node of each WHEN branch, exp.Exists); before the fix every
        # one of these was refused as "function not allowed: case" / ": exists".
        (
            "SELECT CASE WHEN calories > 500 THEN 'high' ELSE 'low' END, COUNT(*) "
            "FROM query_meals GROUP BY 1",
            "SELECT CASE WHEN calories > 500 THEN 'high' ELSE 'low' END, COUNT(*) "
            "FROM query_meals GROUP BY 1",
        ),
        (
            "SELECT SUM(CASE WHEN calories > 500 THEN 1 ELSE 0 END) FROM query_meals",
            "SELECT SUM(CASE WHEN calories > 500 THEN 1 ELSE 0 END) FROM query_meals",
        ),
        (
            "SELECT CASE calories WHEN 0 THEN 'none' END FROM query_meals",
            "SELECT CASE calories WHEN 0 THEN 'none' END FROM query_meals",
        ),
        (
            "SELECT title FROM query_notes WHERE EXISTS ("
            "SELECT 1 FROM query_note_tags nt WHERE nt.note_id = query_notes.id)",
            "SELECT title FROM query_notes WHERE EXISTS("
            "SELECT 1 FROM query_note_tags AS nt WHERE nt.note_id = query_notes.id)",
        ),
        (
            "SELECT title FROM query_notes WHERE NOT EXISTS ("
            "SELECT 1 FROM query_note_tags nt WHERE nt.note_id = query_notes.id)",
            "SELECT title FROM query_notes WHERE NOT EXISTS("
            "SELECT 1 FROM query_note_tags AS nt WHERE nt.note_id = query_notes.id)",
        ),
    ],
)
def test_case_and_exists_syntax_is_accepted(sql: str, expected: str) -> None:
    """The returned string is what executes, so it is pinned exactly: still syntax, no call."""
    assert validate_readonly_sql(sql) == expected


@pytest.mark.parametrize(
    ("sql", "rejected"),
    [
        # Exempting the CASE/EXISTS nodes must not stop the walk descending into them:
        # every operand position stays name-gated (the WHEN condition, THEN, ELSE, the
        # simple-CASE operand, and the EXISTS subquery's projection and predicate).
        (
            "SELECT CASE WHEN md5(title) = 'y' THEN 1 END FROM query_meals",
            "function not allowed: md5",
        ),
        (
            "SELECT CASE WHEN calories > 1 THEN md5(title) END FROM query_meals",
            "function not allowed: md5",
        ),
        (
            "SELECT CASE WHEN calories > 1 THEN 'a' ELSE md5(title) END FROM query_meals",
            "function not allowed: md5",
        ),
        (
            "SELECT CASE md5(title) WHEN 'y' THEN 1 END FROM query_meals",
            "function not allowed: md5",
        ),
        (
            "SELECT 1 FROM query_meals WHERE EXISTS (SELECT md5(title) FROM query_meals)",
            "function not allowed: md5",
        ),
        (
            "SELECT 1 FROM query_meals "
            "WHERE NOT EXISTS (SELECT 1 FROM query_meals WHERE md5(title) = 'y')",
            "function not allowed: md5",
        ),
        # The table gate runs before the function walk, so an EXISTS subquery stays scoped.
        (
            "SELECT 1 FROM query_meals WHERE EXISTS (SELECT 1 FROM meals)",
            "table not in the allowed view set: meals",
        ),
        # The exemption is for the subquery predicate only: the call form over a
        # non-query operand is not EXISTS syntax and stays gated by name.
        ('SELECT "exists"(1) FROM query_meals', "function not allowed: exists"),
        # A second argument is not EXISTS syntax either: sqlglot keeps it as `expression` and
        # drops it on serialization, so admitting it would run less than was validated.
        (
            "SELECT exists((SELECT 1 FROM query_meals), 2) FROM query_meals",
            "function not allowed: exists",
        ),
        # A call spelled "case" parses into a malformed exp.Case whose re-serialization
        # raises TypeError inside sqlglot; it must surface as a rejection, not a crash.
        ('SELECT "case"(1, 2) FROM query_meals', "unserializable statement"),
    ],
)
def test_case_and_exists_operands_stay_gated(sql: str, rejected: str) -> None:
    with pytest.raises(ReadonlySqlError, match=rejected):
        validate_readonly_sql(sql)


def test_if_call_form_serializes_as_case_syntax() -> None:
    """The exp.If exemption cannot put a call on the execution path.

    exp.If is exempt because it is the node of every CASE WHEN branch. Its call forms
    (``if(...)``, ``iif(...)``) parse into the same node, which the postgres dialect can
    only render back as CASE syntax, so exempting the node type admits no function.
    """
    assert validate_readonly_sql('SELECT "if"(calories > 1, 1, 0) FROM query_meals') == (
        "SELECT CASE WHEN calories > 1 THEN 1 ELSE 0 END FROM query_meals"
    )
    assert validate_readonly_sql("SELECT iif(calories > 1, 1, 0) FROM query_meals") == (
        "SELECT CASE WHEN calories > 1 THEN 1 ELSE 0 END FROM query_meals"
    )


def test_rejects_qualified_even_for_allowlisted_view_name() -> None:
    # `_reject_qualified` must run before the scope check: an attacker-controlled
    # schema on an otherwise allow-listed name (public.query_meals) would resolve
    # to a source named `query_meals` and slip past the name allow-list otherwise.
    with pytest.raises(ReadonlySqlError):
        validate_readonly_sql("SELECT * FROM public.query_meals")


def test_fails_closed_when_scope_resolution_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.db.effects.readonly_sql as mod

    def _boom(_tree: object) -> object:
        raise RuntimeError("synthetic resolver failure")

    monkeypatch.setattr(mod, "traverse_scope", _boom)
    with pytest.raises(ReadonlySqlError, match="unresolvable statement"):
        validate_readonly_sql("SELECT title FROM query_meals")


def test_allowlist_covers_expected_views() -> None:
    assert {
        "query_meals",
        "query_meal_recipe_batches",
        "query_recipe_batches",
        "query_activities",
        "query_workouts",
        "query_tasks",
        "query_calendar_events",
        "query_purchases",
        "query_journal_entries",
        "query_journal_entry_emotions",
        "query_cbt_records",
        "query_journal_themes",
        "query_journal_entry_themes",
        "query_notes",
        "query_tags",
        "query_note_tags",
        "query_task_tags",
    } <= set(READONLY_VIEWS)


def test_query_meals_exposes_native_food_quantity_but_no_provenance_documents() -> None:
    query_meals = READONLY_VIEWS["query_meals"]
    for column in ("portion_quantity_value", "portion_quantity_unit"):
        assert column in query_meals
    # The dropped gram mirror is gone from the view, and from the capability prose that
    # lists its columns: nothing writes it, so an analytical query over it reads NULL for
    # every meal this release records.
    assert "portion_weight_g" not in query_meals

    # QueryAgent answers with scalar analytics. Document columns would let one guarded
    # `SELECT *` stream up to MAX_LIMIT provenance blobs — attachment ids, provider product
    # names and URLs, calculation inputs — straight into the decision prompt.
    for document_column in (
        "composition",
        "items",
        "nutrition_provenance",
        "product_code_issue",
        "catalog_disposition",
    ):
        assert document_column not in query_meals


_ANALYTICAL_SQL_DOC = (
    Path(__file__).parents[3] / "src/app/agents/skills/query_agent/capabilities/analytical_sql.md"
)


def _documented_view_columns(doc: str, *, view: str) -> frozenset[str]:
    """Column names the ``analytical_sql`` capability prose lists for one view.

    The prose lists them as a markdown bullet whose body may wrap onto indented
    continuation lines::

        - `query_meals`: id, title, raw_input, calories,
          portion_quantity_value, portion_quantity_unit

    A view with no bullet raises rather than returning an empty set: a view the prose
    never lists is a view the model is never taught to query, which is a failure of the
    guidance and not a vacuous pass.
    """
    lines = doc.splitlines()
    prefix = f"- `{view}`:"
    for index, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        body = [line[len(prefix) :]]
        for continuation in lines[index + 1 :]:
            if not continuation.startswith("  ") or continuation.lstrip().startswith("- "):
                break
            body.append(continuation)
        return frozenset(column.strip() for column in " ".join(body).split(",") if column.strip())
    raise AssertionError(f"analytical_sql.md documents no column list for {view}")


@pytest.mark.parametrize("view", sorted(READONLY_VIEWS))
def test_the_analytical_sql_guidance_lists_exactly_the_columns_the_view_exposes(
    view: str,
) -> None:
    """Prompt drift is a user-visible failure, not a documentation nit.

    A column named in the capability prose but absent from the guarded view produces SQL
    the validator rejects at execution; a column in the view but absent from the prose is
    one the model never reaches for. Neither is visible to a source-position scan, and
    neither survives review reliably — three releases of column churn drifted this list.
    So the prose is pinned against ``READONLY_VIEW_COLUMNS``, which is derived from the
    very definitions the views are built from.
    """
    doc = _ANALYTICAL_SQL_DOC.read_text(encoding="utf-8")

    assert _documented_view_columns(doc, view=view) == READONLY_VIEW_COLUMNS[view]


def test_the_guidance_warns_about_every_unit_qualified_value_column() -> None:
    """A `*_quantity_value` beside a `*_quantity_unit` is not summable, and must say so.

    G2 replaced the gram scalars with value/unit pairs, so `portion_quantity_value` now
    holds grams for a solid and millilitres for a drink. The view exposes both columns and
    nothing at the SQL layer stops `SUM(portion_quantity_value)` — it returns a number that
    adds the two dimensions together, and QueryAgent reports it as a total. The prose is the
    only place that can say so, and `run_readonly_sql` answers from the prose alone.

    Derived from the view surface rather than pinned to one sentence: the assertion holds for
    the next unit-qualified pair too, which is the shape `fooddimensions02` adds more of.
    """
    doc = _ANALYTICAL_SQL_DOC.read_text(encoding="utf-8")

    unqualified: list[str] = []
    for view, columns in sorted(READONLY_VIEW_COLUMNS.items()):
        for column in sorted(columns):
            if not column.endswith("_quantity_value"):
                continue
            unit_column = column.removesuffix("_value") + "_unit"
            if unit_column not in columns:
                continue
            # Keyed on `view.column`, not on the bare column name. Searching for the name
            # alone would let one view's paragraph satisfy every other view exposing a
            # same-named pair — and a second such pair is precisely what this test exists to
            # catch, so the bare-name version would miss the only case it is written for.
            qualified = f"{view}.{column}"
            paragraphs = [
                block
                for block in doc.split("\n\n")
                if qualified in block and not block.startswith("- ")
            ]
            warned = any(
                "meaningless" in block and unit_column in block and "SUM(" in block
                for block in paragraphs
            )
            if not warned:
                unqualified.append(f"{view}.{column} (unit in {unit_column})")

    assert unqualified == [], (
        "the analytical_sql guidance exposes a value column whose dimension lives in a "
        "sibling unit column without warning that summing it mixes dimensions: "
        + ", ".join(unqualified)
    )


def test_readonly_view_columns_is_derived_and_drops_the_gram_mirror() -> None:
    """The equality above is satisfiable by leaving a dropped column in *both* places.

    ``portion_weight_g`` is one of the twelve Release A columns Release B drops. Nothing
    writes it any more, and the CTE no longer projects it, so the model must not be taught
    that it exists. The derived surface — not the prose, and not the raw SELECT text — is
    where that is decided.

    The emptiness check is the other half of ``_projected_columns`` returning empty rather
    than raising: a definition sqlglot cannot read must not take the security boundary down
    at import, so it fails here instead, and by name rather than as a puzzling column diff.
    """
    assert set(READONLY_VIEW_COLUMNS) == set(READONLY_VIEWS)
    unreadable = sorted(name for name, columns in READONLY_VIEW_COLUMNS.items() if not columns)
    assert not unreadable, f"view definitions the parser could not read: {unreadable}"
    assert "portion_weight_g" not in READONLY_VIEW_COLUMNS["query_meals"]
    assert {"portion_quantity_value", "portion_quantity_unit"} <= READONLY_VIEW_COLUMNS[
        "query_meals"
    ]


def test_query_meals_names_no_batch_and_the_link_views_carry_it() -> None:
    """Which batches a meal was eaten from is a set of links, not one meal column (BR-285).

    ``query_meals.recipe_batch_id`` answered for a meal eaten from one batch alone and read
    NULL for a batch eaten with bread or beside a second batch, so a count over it missed
    exactly the meals the owner asks about. The link view carries every link with the batch's
    portion in that meal, and the batch view carries the titles the answer names.
    """
    assert "recipe_batch_id" not in READONLY_VIEW_COLUMNS["query_meals"]
    assert READONLY_VIEW_COLUMNS["query_meal_recipe_batches"] == {
        "meal_id",
        "recipe_batch_id",
        "link_kind",
        "portion_quantity_value",
        "portion_quantity_unit",
        "created_at",
    }
    assert READONLY_VIEW_COLUMNS["query_recipe_batches"] == {
        "id",
        "title",
        "cooked_at",
        "total_quantity_value",
        "total_quantity_unit",
        "calories",
        "protein_g",
        "fat_g",
        "carbs_g",
        "created_at",
    }


def test_rls_tables_derived_from_view_defs() -> None:
    from app.db.effects.readonly_sql import READONLY_VIEWS, RLS_TABLES

    assert RLS_TABLES == (
        "meals",
        "meal_recipe_batches",
        "recipe_batches",
        "activities",
        "workouts",
        "tasks",
        "calendar_events",
        "purchases",
        "journal_entries",
        "journal_entry_emotions",
        "cbt_records",
        "journal_themes",
        "journal_entry_themes",
        "notes",
        "tags",
        "note_tags",
        "task_tags",
    )
    # Base tables are de-duplicated (a table may back more than one view).
    assert len(RLS_TABLES) == len(set(RLS_TABLES))
    assert len(READONLY_VIEWS) == 17


async def test_default_limit_is_applied_when_limit_is_omitted() -> None:
    session = _RecordingSession()
    await run_user_scoped_readonly_sql(
        cast(Any, session),
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        sql="SELECT title FROM query_meals",
    )
    assert session.statements[-1].rstrip().endswith("LIMIT 50")


async def test_excessive_limit_is_clamped_to_max() -> None:
    session = _RecordingSession()
    await run_user_scoped_readonly_sql(
        cast(Any, session),
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        sql="SELECT title FROM query_meals",
        limit=10_000,
    )
    assert session.statements[-1].rstrip().endswith("LIMIT 100")


async def test_execution_guard_and_timeout_are_set_before_user_query() -> None:
    session = _RecordingSession()
    await run_user_scoped_readonly_sql(
        cast(Any, session),
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        sql="SELECT title FROM query_meals",
    )
    assert session.statements[0] == "SET TRANSACTION READ ONLY"
    assert "statement_timeout" in session.statements[1]
    assert session.statements[-1].startswith("WITH query_meals AS")


async def test_sets_app_user_id_guc_before_user_query() -> None:
    user_id = uuid.UUID("00000000-0000-0000-0000-000000000009")
    session = _RecordingSession()
    await run_user_scoped_readonly_sql(
        cast(Any, session), user_id=user_id, sql="SELECT title FROM query_meals"
    )
    assert session.statements[0] == "SET TRANSACTION READ ONLY"
    assert "statement_timeout" in session.statements[1]
    assert "set_config('app.user_id'" in session.statements[2]
    assert session.params[2] == {"uid": str(user_id)}
    assert session.statements[-1].startswith("WITH query_meals AS")


async def test_query_runs_against_scoped_view_surface() -> None:
    user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    session = _RecordingSession()
    await run_user_scoped_readonly_sql(
        cast(Any, session), user_id=user_id, sql="SELECT title FROM query_meals"
    )
    rendered = session.statements[-1]
    assert "query_meals AS (" in rendered
    assert f"FROM meals WHERE user_id = '{user_id}'" in rendered
    assert "SELECT * FROM (SELECT title FROM query_meals)" in rendered


pytestmark_integration = pytest.mark.integration


@pytest.mark.db
@pytestmark_integration
async def test_run_scopes_to_user() -> None:
    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    other = await create_user()
    async with AsyncSessionLocal() as session:
        session.add(
            Meal(
                user_id=me,
                title="my-meal",
                raw_input="my-meal",
                calories=100,
                protein_g=5,
                fat_g=3,
                carbs_g=10,
            )
        )
        session.add(
            Meal(
                user_id=other,
                title="other-meal",
                raw_input="other-meal",
                calories=100,
                protein_g=5,
                fat_g=3,
                carbs_g=10,
            )
        )
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session, user_id=me, sql="SELECT title FROM query_meals", limit=50
        )
    titles = {r["title"] for r in rows}
    assert "my-meal" in titles
    assert "other-meal" not in titles


@pytest.mark.db
@pytestmark_integration
async def test_multi_predicate_statement_executes_end_to_end() -> None:
    """A boolean-connector statement must survive the whole path, not just the validator.

    ``validate_readonly_sql`` returns a *re-serialized* tree, which ``_scoped_query`` then
    wraps in the per-user view CTEs before Postgres sees it. The unit cases around BR-232
    prove only that the parser gate stops refusing AND/OR; this one proves the SQL that
    comes out the far side still runs, and still filters on both predicates.
    """
    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    async with AsyncSessionLocal() as session:
        for title, calories in (("in-band", 500), ("too-low", 50), ("too-high", 2000)):
            session.add(
                Meal(
                    user_id=me,
                    title=title,
                    raw_input=title,
                    calories=calories,
                    protein_g=5,
                    fat_g=3,
                    carbs_g=10,
                )
            )
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql=(
                "SELECT title FROM query_meals "
                "WHERE calories > 100 AND calories < 900 AND title IS NOT NULL"
            ),
            limit=50,
        )
    assert {r["title"] for r in rows} == {"in-band"}


@pytest.mark.db
@pytestmark_integration
async def test_case_and_exists_statements_execute_scoped_end_to_end() -> None:
    """BR-233: CASE and EXISTS survive the scoped wrapper, and the subquery stays scoped.

    The validator returns a re-serialized tree that ``_scoped_query`` wraps in the per-user
    view CTEs, so an EXISTS subquery reads the same scoped ``query_meals`` as the outer
    query. The other user's 5000 kcal meal is what proves it: were the subquery to see it,
    the ``NOT EXISTS`` statement would return no rows.
    """
    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    other, _other_run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    async with AsyncSessionLocal() as session:
        for owner, title, calories in (
            (me, "light", 50),
            (me, "medium", 500),
            (me, "heavy", 2000),
            (other, "someone-else", 5000),
        ):
            session.add(
                Meal(
                    user_id=owner,
                    title=title,
                    raw_input=title,
                    calories=calories,
                    protein_g=5,
                    fat_g=3,
                    carbs_g=10,
                )
            )
        await session.commit()

    async def run(sql: str) -> list[dict[str, Any]]:
        async with AsyncSessionLocal() as session, session.begin():
            return await run_user_scoped_readonly_sql(session, user_id=me, sql=sql, limit=50)

    banded = await run(
        "SELECT CASE WHEN calories > 500 THEN 'high' ELSE 'low' END AS band, COUNT(*) AS n "
        "FROM query_meals GROUP BY 1"
    )
    assert {r["band"]: r["n"] for r in banded} == {"high": 1, "low": 2}

    correlated = await run(
        "SELECT title FROM query_meals WHERE EXISTS ("
        "SELECT 1 FROM query_meals h WHERE h.id = query_meals.id AND h.calories > 1000)"
    )
    assert {r["title"] for r in correlated} == {"heavy"}

    scoped = await run(
        "SELECT title FROM query_meals "
        "WHERE NOT EXISTS (SELECT 1 FROM query_meals h WHERE h.calories > 4000)"
    )
    assert {r["title"] for r in scoped} == {"light", "medium", "heavy"}


@pytest.mark.db
@pytestmark_integration
async def test_query_workouts_view_joins_parent_activity() -> None:
    # Regression: workouts became a 1-1 activity subtype, so title/started_at/etc.
    # live on the parent activity. The query_workouts view must JOIN activities;
    # otherwise model SQL selecting `title` from it raises UndefinedColumn.
    from datetime import UTC, datetime

    from tests.db.factories import add_workout

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    async with AsyncSessionLocal() as session:
        add_workout(
            session,
            user_id=me,
            workout_type="run",
            title="утренний бег",
            raw_input="пробежал 5 км",
            started_at=datetime(2026, 6, 1, 8, tzinfo=UTC),
        )
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql="SELECT title, workout_type FROM query_workouts",
            limit=50,
        )
    assert len(rows) == 1
    assert rows[0]["title"] == "утренний бег"
    assert rows[0]["workout_type"] == "run"


@pytest.mark.db
@pytestmark_integration
async def test_rls_contains_base_table_read_under_readonly_role() -> None:
    """Even a raw base-table read (parser bypassed) sees only the current user.

    Requires READONLY_DATABASE_URL pointing at the migrated DB (RLS applied) with
    the daybook_readonly role provisioned. Skips otherwise.
    """
    from sqlalchemy import text

    from app.db.session import get_readonly_sessionmaker

    maker = get_readonly_sessionmaker()
    if maker is None:
        pytest.skip("READONLY_DATABASE_URL not configured")

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    other = await create_user()
    async with AsyncSessionLocal() as session:
        session.add(
            Meal(
                user_id=me,
                title="my-meal",
                raw_input="my-meal",
                calories=100,
                protein_g=5,
                fat_g=3,
                carbs_g=10,
            )
        )
        session.add(
            Meal(
                user_id=other,
                title="other-meal",
                raw_input="other-meal",
                calories=100,
                protein_g=5,
                fat_g=3,
                carbs_g=10,
            )
        )
        await session.commit()

    async with maker() as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(
            text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(me)}
        )
        # Raw base-table read — what a parser bypass would attempt. RLS must scope it.
        rows = (await session.execute(text("SELECT title FROM meals"))).mappings().all()
    titles = {r["title"] for r in rows}
    assert "my-meal" in titles
    assert "other-meal" not in titles

    # A table the read-only role was never granted is unreadable regardless of RLS.
    with pytest.raises(Exception):  # noqa: B017 — asyncpg/psycopg raises InsufficientPrivilege
        async with maker() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(me)}
            )
            await session.execute(text("SELECT id FROM users"))


@pytest.mark.db
@pytestmark_integration
async def test_query_activities_exposes_ended_at() -> None:
    """query_activities must include ended_at in its projected column set."""
    from datetime import UTC, datetime

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    async with AsyncSessionLocal() as session:
        session.add(
            Activity(
                user_id=me,
                category="exercise",
                title="morning run",
                raw_input="ran 5 km",
                started_at=datetime(2026, 6, 1, 7, tzinfo=UTC),
                ended_at=datetime(2026, 6, 1, 8, tzinfo=UTC),
            )
        )
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql="SELECT id, started_at, ended_at FROM query_activities",
            limit=50,
        )
    assert len(rows) >= 1
    matching = [r for r in rows if r["started_at"] is not None]
    assert len(matching) == 1
    assert "ended_at" in matching[0]
    assert matching[0]["ended_at"] is not None


@pytest.mark.db
@pytestmark_integration
async def test_query_activities_cooking_row_ended_at_started_at_null() -> None:
    """Cooking rows appear in query_activities with ended_at set and started_at NULL.

    Cooking activities use ended_at (completion time) and leave started_at NULL,
    so the view must project ended_at and must NOT filter out rows where started_at
    is NULL.
    """
    from datetime import UTC, datetime

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    ended = datetime(2026, 6, 1, 19, 30, tzinfo=UTC)
    async with AsyncSessionLocal() as session:
        session.add(
            Activity(
                user_id=me,
                category="cooking",
                title="pasta bolognese",
                raw_input="cooked pasta",
                started_at=None,
                ended_at=ended,
            )
        )
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql="SELECT title, category, started_at, ended_at FROM query_activities",
            limit=50,
        )
    cooking = [r for r in rows if r["title"] == "pasta bolognese"]
    assert len(cooking) == 1, "cooking row must appear in query_activities"
    assert cooking[0]["started_at"] is None
    assert cooking[0]["ended_at"] is not None


@pytest.mark.db
@pytestmark_integration
async def test_query_meals_excludes_soft_deleted() -> None:
    """Soft-deleted meals must not appear in query_meals."""
    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    async with AsyncSessionLocal() as session:
        live_meal = Meal(
            user_id=me,
            title="live-meal",
            raw_input="live-meal",
            calories=100,
            protein_g=5,
            fat_g=3,
            carbs_g=10,
        )
        deleted_meal = Meal(
            user_id=me,
            title="deleted-meal",
            raw_input="deleted-meal",
            calories=200,
            protein_g=8,
            fat_g=4,
            carbs_g=20,
        )
        session.add(live_meal)
        session.add(deleted_meal)
        await session.flush()
        from datetime import UTC, datetime

        deleted_meal.deleted_at = datetime.now(UTC)
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session, user_id=me, sql="SELECT title FROM query_meals", limit=50
        )
    titles = {r["title"] for r in rows}
    assert "live-meal" in titles
    assert "deleted-meal" not in titles, "soft-deleted meal must be excluded from query_meals"


@pytest.mark.db
@pytestmark_integration
async def test_query_activities_excludes_soft_deleted() -> None:
    """Soft-deleted activities must not appear in query_activities."""
    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    async with AsyncSessionLocal() as session:
        live_act = Activity(
            user_id=me,
            category="exercise",
            title="live-activity",
            raw_input="live-activity",
        )
        deleted_act = Activity(
            user_id=me,
            category="exercise",
            title="deleted-activity",
            raw_input="deleted-activity",
        )
        session.add(live_act)
        session.add(deleted_act)
        await session.flush()
        from datetime import UTC, datetime

        deleted_act.deleted_at = datetime.now(UTC)
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session, user_id=me, sql="SELECT title FROM query_activities", limit=50
        )
    titles = {r["title"] for r in rows}
    assert "live-activity" in titles
    assert "deleted-activity" not in titles, (
        "soft-deleted activity must be excluded from query_activities"
    )


@pytest.mark.db
@pytestmark_integration
async def test_query_workouts_excludes_soft_deleted_parent_activity() -> None:
    """A workout whose parent activity is soft-deleted must not appear in query_workouts."""
    from decimal import Decimal

    from tests.db.factories import add_workout

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    async with AsyncSessionLocal() as session:
        add_workout(
            session,
            user_id=me,
            workout_type="run",
            title="deleted-parent-workout",
            raw_input="deleted parent",
            duration_minutes=Decimal("30"),
        )
        await session.commit()

    # Soft-delete the parent activity.
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        from app.models.activity import Activity

        act = await session.scalar(
            select(Activity).where(
                Activity.user_id == me,
                Activity.title == "deleted-parent-workout",
            )
        )
        assert act is not None
        from datetime import UTC, datetime

        act.deleted_at = datetime.now(UTC)
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql="SELECT title, workout_type FROM query_workouts",
            limit=50,
        )
    titles = {r["title"] for r in rows}
    assert "deleted-parent-workout" not in titles, (
        "workout with soft-deleted parent activity must be excluded from query_workouts"
    )


@pytest.mark.db
@pytestmark_integration
async def test_query_workouts_does_not_expose_other_users_activity() -> None:
    """query_workouts must not return a row when the joined activity belongs to a
    different user (defense-in-depth: a.user_id = w.user_id guard).

    Set up: attacker user A owns a Workout whose activity_id points to victim user B's
    Activity.  Running query_workouts for A must yield zero rows.
    """
    from decimal import Decimal

    attacker, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    victim = await create_user()

    # Seed a legitimate Activity owned by the victim.
    async with AsyncSessionLocal() as session:
        victim_activity = Activity(
            user_id=victim,
            category="exercise",
            title="victim's run",
            raw_input="victim run",
            duration_minutes=Decimal("30"),
        )
        session.add(victim_activity)
        await session.flush()
        victim_activity_id = victim_activity.id
        await session.commit()

    # Seed the attacker's workout but point activity_id at the victim's activity.
    # We bypass add_workout() intentionally to create the cross-user anomaly.
    from app.models.activity import Workout

    async with AsyncSessionLocal() as session:
        # The attacker needs a placeholder activity of their own for the FK to stay
        # valid on the workouts.activity_id column (which references activities.id).
        # We instead create the Workout pointing at the victim's activity_id directly.
        attacker_workout = Workout(
            user_id=attacker,
            activity_id=victim_activity_id,
            workout_type="run",
        )
        session.add(attacker_workout)
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session,
            user_id=attacker,
            sql="SELECT id, workout_type FROM query_workouts",
            limit=50,
        )
    # Without the a.user_id = w.user_id guard the JOIN would pull in the victim's
    # activity and expose it to the attacker.  With the guard the row is excluded.
    assert rows == [], "query_workouts must not expose an activity owned by a different user"


# --- J1-f: journal/notes read-only views ---------------------------------------


@pytest.mark.db
@pytestmark_integration
async def test_query_journal_entries_excludes_soft_deleted() -> None:
    """Soft-deleted journal entries must not appear in query_journal_entries."""
    from datetime import UTC, datetime

    from app.models.journal import JournalEntry

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    occurred = datetime(2026, 6, 1, 9, tzinfo=UTC)
    async with AsyncSessionLocal() as session:
        live_entry = JournalEntry(
            user_id=me,
            entry_type="reflection",
            content="live entry",
            occurred_at=occurred,
            occurred_on=occurred.date(),
        )
        deleted_entry = JournalEntry(
            user_id=me,
            entry_type="reflection",
            content="deleted entry",
            occurred_at=occurred,
            occurred_on=occurred.date(),
        )
        session.add_all([live_entry, deleted_entry])
        await session.flush()
        deleted_entry.deleted_at = datetime.now(UTC)
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session, user_id=me, sql="SELECT content FROM query_journal_entries", limit=50
        )
    contents = {r["content"] for r in rows}
    assert "live entry" in contents
    assert "deleted entry" not in contents


@pytest.mark.db
@pytestmark_integration
async def test_query_cbt_records_hides_deleted_anchor() -> None:
    """A CBT record whose anchor journal entry is soft-deleted must be hidden
    (deletion semantics are transitive — spec §11)."""
    from datetime import UTC, datetime

    from app.models.journal import CbtRecord, JournalEntry

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    occurred = datetime(2026, 6, 1, 9, tzinfo=UTC)
    async with AsyncSessionLocal() as session:
        entry = JournalEntry(
            user_id=me,
            entry_type="reflection",
            content="anchor entry",
            occurred_at=occurred,
            occurred_on=occurred.date(),
        )
        session.add(entry)
        await session.flush()
        record = CbtRecord(
            user_id=me,
            journal_entry_id=entry.id,
            kind="quick",
            status="open",
            situation="situation",
            thought="thought",
        )
        session.add(record)
        await session.flush()
        entry.deleted_at = datetime.now(UTC)
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session, user_id=me, sql="SELECT id FROM query_cbt_records", limit=50
        )
    assert rows == [], "cbt record with soft-deleted anchor entry must be hidden"


@pytest.mark.db
@pytestmark_integration
async def test_query_journal_entry_themes_hides_deleted_entry_links() -> None:
    """A theme link whose entry is soft-deleted must be hidden."""
    from datetime import UTC, datetime

    from app.models.journal import JournalEntry, JournalEntryTheme, JournalTheme

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    occurred = datetime(2026, 6, 1, 9, tzinfo=UTC)
    async with AsyncSessionLocal() as session:
        entry = JournalEntry(
            user_id=me,
            entry_type="reflection",
            content="entry",
            occurred_at=occurred,
            occurred_on=occurred.date(),
        )
        theme = JournalTheme(user_id=me, name="work-stress")
        session.add_all([entry, theme])
        await session.flush()
        link = JournalEntryTheme(entry_id=entry.id, theme_id=theme.id, user_id=me)
        session.add(link)
        await session.flush()
        entry.deleted_at = datetime.now(UTC)
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql="SELECT entry_id FROM query_journal_entry_themes",
            limit=50,
        )
    assert rows == [], "theme link with soft-deleted entry must be hidden"


@pytest.mark.db
@pytestmark_integration
async def test_query_note_tags_hides_deleted_tag() -> None:
    """A note-tag link whose tag is soft-deleted must be hidden."""
    from datetime import UTC, datetime

    from app.models.notes import Note, NoteTag, Tag

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    async with AsyncSessionLocal() as session:
        note = Note(user_id=me, content="a note")
        tag = Tag(user_id=me, name="reading")
        session.add_all([note, tag])
        await session.flush()
        link = NoteTag(note_id=note.id, tag_id=tag.id, user_id=me)
        session.add(link)
        await session.flush()
        tag.deleted_at = datetime.now(UTC)
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session, user_id=me, sql="SELECT note_id FROM query_note_tags", limit=50
        )
    assert rows == [], "note-tag link with soft-deleted tag must be hidden"


@pytest.mark.db
@pytestmark_integration
async def test_query_notes_scopes_to_user() -> None:
    """query_notes must only return the querying user's notes."""
    from app.models.notes import Note

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    other = await create_user()
    async with AsyncSessionLocal() as session:
        session.add(Note(user_id=me, content="my note"))
        session.add(Note(user_id=other, content="other note"))
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session, user_id=me, sql="SELECT content FROM query_notes", limit=50
        )
    contents = {r["content"] for r in rows}
    assert "my note" in contents
    assert "other note" not in contents


@pytest.mark.db
@pytestmark_integration
@pytest.mark.parametrize("view", READONLY_VIEW_DEFS, ids=[v.name for v in READONLY_VIEW_DEFS])
async def test_all_view_definitions_execute(view: Any) -> None:
    """Every declared view's column list must be valid against the live schema.

    No separate column-vs-ORM verification test exists (the module comment
    overstates); this smoke test — parameterized over every READONLY_VIEW_DEFS
    entry — is what actually validates each view's column list against Postgres.
    """
    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session, user_id=me, sql=f"SELECT * FROM {view.name} LIMIT 1", limit=1
        )
    assert isinstance(rows, list)


@pytest.mark.db
@pytestmark_integration
async def test_two_columns_postgres_names_alike_both_reach_the_agent() -> None:
    """Postgres names both aggregates ``sum``; a row keyed by column name kept only the last,
    so a NULL count of 0 replaced a 200 g total and the agent reported a zero weight."""
    from datetime import UTC, datetime

    from app.models.journal import JournalEntry

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    occurred = datetime(2026, 6, 1, 9, tzinfo=UTC)
    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                JournalEntry(
                    user_id=me,
                    entry_type="reflection",
                    content=f"entry {i}",
                    occurred_at=occurred,
                    occurred_on=occurred.date(),
                    intensity=intensity,
                )
                for i, intensity in enumerate([20, 50])
            ]
        )
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql=(
                "SELECT SUM(intensity), SUM(CASE WHEN intensity IS NULL THEN 1 ELSE 0 END) "
                "FROM query_journal_entries"
            ),
            limit=50,
        )
    assert rows == [{"sum": 70, "sum_2": 0}]


@pytest.mark.db
@pytestmark_integration
async def test_stddev_and_percentile_cont_execute() -> None:
    """STDDEV/PERCENTILE_CONT must execute end-to-end against Postgres — validator
    accept-parametrization alone is not execution proof."""
    from datetime import UTC, datetime

    from app.models.journal import JournalEntry

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    occurred = datetime(2026, 6, 1, 9, tzinfo=UTC)
    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                JournalEntry(
                    user_id=me,
                    entry_type="reflection",
                    content=f"entry {i}",
                    occurred_at=occurred,
                    occurred_on=occurred.date(),
                    intensity=intensity,
                )
                for i, intensity in enumerate([20, 50, 80])
            ]
        )
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        stddev_rows = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql="SELECT STDDEV(intensity) AS s FROM query_journal_entries",
            limit=50,
        )
    assert stddev_rows[0]["s"] is not None

    async with AsyncSessionLocal() as session, session.begin():
        percentile_rows = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql=(
                "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY intensity) AS p "
                "FROM query_journal_entries"
            ),
            limit=50,
        )
    assert percentile_rows[0]["p"] is not None


@pytest.mark.db
@pytestmark_integration
async def test_rls_isolates_journal_entries_under_readonly_role() -> None:
    """Cross-user isolation on journal_entries under the dedicated read-only role.

    Requires READONLY_DATABASE_URL pointing at the migrated DB (RLS applied) with
    the daybook_readonly role provisioned. Skips otherwise.
    """
    from datetime import UTC, datetime

    from sqlalchemy import text

    from app.db.session import get_readonly_sessionmaker
    from app.models.journal import JournalEntry

    maker = get_readonly_sessionmaker()
    if maker is None:
        pytest.skip("READONLY_DATABASE_URL not configured")

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    other = await create_user()
    occurred = datetime(2026, 6, 1, 9, tzinfo=UTC)
    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                JournalEntry(
                    user_id=me,
                    entry_type="reflection",
                    content="my entry",
                    occurred_at=occurred,
                    occurred_on=occurred.date(),
                ),
                JournalEntry(
                    user_id=other,
                    entry_type="reflection",
                    content="other entry",
                    occurred_at=occurred,
                    occurred_on=occurred.date(),
                ),
            ]
        )
        await session.commit()

    async with maker() as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(
            text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(me)}
        )
        rows = (await session.execute(text("SELECT content FROM journal_entries"))).mappings().all()
    contents = {r["content"] for r in rows}
    assert "my entry" in contents
    assert "other entry" not in contents


@pytest.mark.db
@pytestmark_integration
async def test_rls_isolates_journal_entry_themes_under_readonly_role() -> None:
    """Cross-user isolation on the journal_entry_themes junction under the
    dedicated read-only role. Requires READONLY_DATABASE_URL; skips otherwise.
    """
    from datetime import UTC, datetime

    from sqlalchemy import text

    from app.db.session import get_readonly_sessionmaker
    from app.models.journal import JournalEntry, JournalEntryTheme, JournalTheme

    maker = get_readonly_sessionmaker()
    if maker is None:
        pytest.skip("READONLY_DATABASE_URL not configured")

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    other = await create_user()
    occurred = datetime(2026, 6, 1, 9, tzinfo=UTC)
    async with AsyncSessionLocal() as session:
        my_entry = JournalEntry(
            user_id=me,
            entry_type="reflection",
            content="my entry",
            occurred_at=occurred,
            occurred_on=occurred.date(),
        )
        other_entry = JournalEntry(
            user_id=other,
            entry_type="reflection",
            content="other entry",
            occurred_at=occurred,
            occurred_on=occurred.date(),
        )
        my_theme = JournalTheme(user_id=me, name="my-theme")
        other_theme = JournalTheme(user_id=other, name="other-theme")
        session.add_all([my_entry, other_entry, my_theme, other_theme])
        await session.flush()
        session.add_all(
            [
                JournalEntryTheme(entry_id=my_entry.id, theme_id=my_theme.id, user_id=me),
                JournalEntryTheme(entry_id=other_entry.id, theme_id=other_theme.id, user_id=other),
            ]
        )
        await session.commit()

    async with maker() as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(
            text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(me)}
        )
        rows = (
            (await session.execute(text("SELECT entry_id FROM journal_entry_themes")))
            .mappings()
            .all()
        )
    entry_ids = {r["entry_id"] for r in rows}
    assert my_entry.id in entry_ids
    assert other_entry.id not in entry_ids


async def _add_batch(session: AsyncSession, user_id: uuid.UUID, title: str) -> RecipeBatch:
    batch = RecipeBatch(
        user_id=user_id,
        title=title,
        raw_input=title,
        total_quantity_value=Decimal("1000"),
        total_quantity_unit="g",
        calories=Decimal("1500"),
        protein_g=Decimal("60"),
        fat_g=Decimal("50"),
        carbs_g=Decimal("200"),
    )
    session.add(batch)
    await session.flush()
    return batch


def _batch_meal(user_id: uuid.UUID, title: str, *, grams: str | None = None) -> Meal:
    return Meal(
        user_id=user_id,
        title=title,
        raw_input=title,
        calories=Decimal("300"),
        protein_g=Decimal("12"),
        fat_g=Decimal("10"),
        carbs_g=Decimal("40"),
        portion_quantity_value=None if grams is None else Decimal(grams),
        portion_quantity_unit=None if grams is None else "g",
    )


async def _seed_whole_meal_from_batch(
    user_id: uuid.UUID, title: str, *, grams: str = "200"
) -> tuple[uuid.UUID, uuid.UUID]:
    """One batch and one meal eaten from it alone; returns ``(batch_id, meal_id)``."""
    async with AsyncSessionLocal() as session:
        batch = await _add_batch(session, user_id, title)
        meal = await add_seeded_meal(
            session, _batch_meal(user_id, title, grams=grams), sole_batch_id=batch.id
        )
        await session.commit()
        return batch.id, meal.id


@pytest.mark.db
@pytestmark_integration
async def test_the_meal_batch_views_scope_to_user() -> None:
    """Both batch views show only the querying user's links and batches."""
    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    other = await create_user()
    my_batch, my_meal = await _seed_whole_meal_from_batch(me, "my-batch")
    await _seed_whole_meal_from_batch(other, "other-batch")

    async with AsyncSessionLocal() as session, session.begin():
        links = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql=(
                "SELECT meal_id, recipe_batch_id, link_kind, portion_quantity_value, "
                "portion_quantity_unit FROM query_meal_recipe_batches"
            ),
            limit=50,
        )
        batches = await run_user_scoped_readonly_sql(
            session, user_id=me, sql="SELECT id, title FROM query_recipe_batches", limit=50
        )

    assert links == [
        {
            "meal_id": my_meal,
            "recipe_batch_id": my_batch,
            "link_kind": "whole_meal",
            "portion_quantity_value": Decimal("200"),
            "portion_quantity_unit": "g",
        }
    ]
    assert batches == [{"id": my_batch, "title": "my-batch"}]


@pytest.mark.db
@pytestmark_integration
async def test_the_meal_batch_views_hide_soft_deleted_meals_and_batches() -> None:
    """A soft-deleted meal or batch hides its link, and a soft-deleted batch its row.

    The link view joins both sides, as every junction view does, so no link names a batch
    ``query_recipe_batches`` cannot title and no deleted meal counts as eaten.
    """
    from datetime import UTC, datetime

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    _live_batch, deleted_meal = await _seed_whole_meal_from_batch(me, "meal-deleted")
    deleted_batch, _meal = await _seed_whole_meal_from_batch(me, "batch-deleted")
    async with AsyncSessionLocal() as session:
        live = await _add_batch(session, me, "live")
        eaten_with_bread = await store_meal_composition(
            session,
            _batch_meal(me, "live with bread"),
            saved_batch_row(live.id, "150"),
            estimated_row("хлеб", "40"),
        )
        await session.execute(
            update(Meal).where(Meal.id == deleted_meal).values(deleted_at=datetime.now(UTC))
        )
        await session.execute(
            update(RecipeBatch)
            .where(RecipeBatch.id == deleted_batch)
            .values(deleted_at=datetime.now(UTC))
        )
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        links = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql=(
                "SELECT meal_id, recipe_batch_id, link_kind, portion_quantity_value "
                "FROM query_meal_recipe_batches"
            ),
            limit=50,
        )
        titles = await run_user_scoped_readonly_sql(
            session, user_id=me, sql="SELECT title FROM query_recipe_batches", limit=50
        )

    assert links == [
        {
            "meal_id": eaten_with_bread.id,
            "recipe_batch_id": live.id,
            "link_kind": "composition",
            "portion_quantity_value": Decimal("150"),
        }
    ]
    # The batch whose only meal was deleted is still a live batch; only the deleted one hides.
    assert {row["title"] for row in titles} == {"meal-deleted", "live"}


@pytest.mark.db
@pytestmark_integration
async def test_the_link_view_hides_a_link_to_another_users_meal_or_batch() -> None:
    """The ``query_workouts`` guard on both joins: a link row stamped with my ``user_id`` but
    naming another user's meal or batch must not surface. No writer produces one (the link's
    owner is the meal's), so this pins the defense in depth, not a reachable state."""
    from app.models.food import MealRecipeBatch

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    other = await create_user()
    their_batch, their_meal = await _seed_whole_meal_from_batch(other, "their-batch")
    async with AsyncSessionLocal() as session:
        my_batch = await _add_batch(session, me, "my-batch")
        my_meal = _batch_meal(me, "my-meal")
        session.add(my_meal)
        await session.flush()
        session.add_all(
            [
                MealRecipeBatch(
                    meal_id=their_meal,
                    recipe_batch_id=my_batch.id,
                    user_id=me,
                    link_kind="composition",
                    portion_quantity_value=Decimal("100"),
                    portion_quantity_unit="g",
                ),
                MealRecipeBatch(
                    meal_id=my_meal.id,
                    recipe_batch_id=their_batch,
                    user_id=me,
                    link_kind="composition",
                    portion_quantity_value=Decimal("100"),
                    portion_quantity_unit="g",
                ),
            ]
        )
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        rows = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql="SELECT meal_id, recipe_batch_id FROM query_meal_recipe_batches",
            limit=50,
        )
    assert rows == []


@pytest.mark.db
@pytestmark_integration
async def test_the_documented_join_answers_eaten_batch_questions() -> None:
    """The owner's week, answered by the join ``analytical_sql.md`` teaches.

    Monday 200 g of bolognese alone, Tuesday 200 g of bolognese with bread, Wednesday 150 g
    of bolognese beside 150 g of rice with vegetables: three meals from batches, 550 g of
    bolognese, bolognese eaten three times and the rice once. Two of the three meals are
    composition links, which ``query_meals.recipe_batch_id`` never named.
    """
    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    async with AsyncSessionLocal() as session:
        bolognese = await _add_batch(session, me, "болоньезе")
        rice = await _add_batch(session, me, "рис с овощами")
        await add_seeded_meal(
            session, _batch_meal(me, "болоньезе", grams="200"), sole_batch_id=bolognese.id
        )
        await store_meal_composition(
            session,
            _batch_meal(me, "болоньезе с хлебом"),
            saved_batch_row(bolognese.id, "200"),
            estimated_row("хлеб", "50"),
        )
        await store_meal_composition(
            session,
            _batch_meal(me, "болоньезе и рис с овощами"),
            saved_batch_row(bolognese.id, "150"),
            saved_batch_row(rice.id, "150"),
        )
        await session.commit()

    async with AsyncSessionLocal() as session, session.begin():
        meals = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql=(
                "SELECT COUNT(DISTINCT l.meal_id) AS meals FROM query_meal_recipe_batches l "
                "JOIN query_meals m ON m.id = l.meal_id"
            ),
            limit=50,
        )
        per_batch = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql=(
                "SELECT b.title, COUNT(*) AS meals, SUM(l.portion_quantity_value) AS amount, "
                "l.portion_quantity_unit FROM query_meal_recipe_batches l "
                "JOIN query_recipe_batches b ON b.id = l.recipe_batch_id "
                "GROUP BY b.title, l.portion_quantity_unit ORDER BY meals DESC"
            ),
            limit=50,
        )

    assert meals == [{"meals": 3}]
    assert per_batch == [
        {"title": "болоньезе", "meals": 3, "amount": Decimal("550"), "portion_quantity_unit": "g"},
        {
            "title": "рис с овощами",
            "meals": 1,
            "amount": Decimal("150"),
            "portion_quantity_unit": "g",
        },
    ]


@pytest.mark.db
@pytestmark_integration
async def test_rls_isolates_meal_batch_links_and_batches_under_readonly_role() -> None:
    """Cross-user isolation on ``meal_recipe_batches`` and ``recipe_batches`` under the
    dedicated read-only role, both on a raw base-table read and through the two views, whose
    joins need ``meals`` and ``recipe_batches`` granted too. Requires READONLY_DATABASE_URL;
    skips otherwise.
    """
    from sqlalchemy import text

    from app.db.session import get_readonly_sessionmaker

    maker = get_readonly_sessionmaker()
    if maker is None:
        pytest.skip("READONLY_DATABASE_URL not configured")

    me, _run_id = await create_agent_run(DomainAgentName.QUERY_AGENT, Intent.QUERY)
    other = await create_user()
    my_batch, my_meal = await _seed_whole_meal_from_batch(me, "my-batch")
    other_batch, other_meal = await _seed_whole_meal_from_batch(other, "other-batch")

    async with maker() as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(
            text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(me)}
        )
        # Raw base-table reads — what a parser bypass would attempt. RLS must scope them.
        link_rows = (
            (
                await session.execute(
                    text("SELECT meal_id, recipe_batch_id FROM meal_recipe_batches")
                )
            )
            .mappings()
            .all()
        )
        batch_rows = (await session.execute(text("SELECT id FROM recipe_batches"))).mappings().all()
    linked_meals = {r["meal_id"] for r in link_rows}
    batch_ids = {r["id"] for r in batch_rows}
    assert my_meal in linked_meals
    assert other_meal not in linked_meals
    assert my_batch in batch_ids
    assert other_batch not in batch_ids

    async with maker() as session, session.begin():
        view_links = await run_user_scoped_readonly_sql(
            session,
            user_id=me,
            sql="SELECT meal_id FROM query_meal_recipe_batches",
            limit=50,
        )
        view_batches = await run_user_scoped_readonly_sql(
            session, user_id=me, sql="SELECT id FROM query_recipe_batches", limit=50
        )
    assert view_links == [{"meal_id": my_meal}]
    assert view_batches == [{"id": my_batch}]
