"""Parser-based safety envelope for QueryAgent's ``run_readonly_sql`` tool.

The model produces free-form SQL. This module is the security boundary that must
guarantee the statement can only run as a single user-scoped read over the
read-only ``query_*`` views — never a raw base table, write, multi-statement,
qualified identifier, or unknown function.

Validation is AST-based (via ``sqlglot``), not regex/string: regex allow-lists are
trivially bypassable through comma joins, aliases, quoted/schema-qualified
identifiers, subqueries, and CTE bodies. We parse, reject anything that is not a
single read, then walk every lexical scope (via ``sqlglot.optimizer.scope.traverse_scope``) so
each table reference is checked against the CTE names visible in *its* scope —
only genuine base-table reads survive as ``exp.Table`` sources and each must be one
of the read-only views. A same-named CTE in an inner scope can no longer
whitelist a base-table reference in an outer scope. Recursive CTEs and
schema-qualified identifiers are rejected outright. Every function node is
name-gated against a small
analytical allow-list: we walk all ``exp.Func`` nodes (the base class covering both
sqlglot's typed function nodes — e.g. ``exp.Count``, ``exp.Cast`` — and the
``exp.Anonymous`` fallback for unrecognized names) and reject any whose canonical
name is not allow-listed, so functions like ``version()`` or ``pg_read_file(...)``
never pass regardless of how sqlglot models them.

Parser validation is necessary but not sufficient. The execution path layers, as
defense in depth: scope-aware parser allow-list + user-scoped view CTEs (column
projection) + a dedicated read-only DB role under Row-Level Security keyed on
``app.user_id`` (row scoping) + read-only transaction guard + statement timeout +
bounded row limits. RLS is enforced once the ``e7f8a9b0c1d2`` migration has run and
``Settings.readonly_database_url`` points at the low-privilege role; if the DSN is set
before the migration, the role simply lacks SELECT and reads fail closed. With no DSN
the tool runs under the main role and the parser is the sole barrier.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
# Fallback per-statement timeout (ms) when no caller/settings value is supplied.
# The live default is settings-configurable via Settings.readonly_sql_statement_timeout_ms.
STATEMENT_TIMEOUT_MS = 2000
READONLY_TRANSACTION_SQL = "SET TRANSACTION READ ONLY"

# Every function node is gated against this allow-list by canonical name (see
# ``_function_name``). sqlglot models recognized SQL functions as typed nodes (e.g.
# ``exp.Count``, ``exp.Cast``, ``exp.TimestampTrunc``) whose canonical name comes from
# ``sql_name()``, and unrecognized names as ``exp.Anonymous`` whose name is ``.this``.
# Names below are the lowercased canonical forms: ``date_trunc`` canonicalizes to
# ``timestamp_trunc`` and ``now()`` to ``current_timestamp``, so both canonical forms
# are listed. The plain ``date_trunc``/``now`` aliases are kept as harmless analytical
# synonyms in case a dialect surfaces them verbatim.
_ALLOWED_FUNCTIONS = {
    "count",
    "sum",
    "avg",
    "min",
    "max",
    "round",
    "abs",
    "coalesce",
    "date_trunc",
    "timestamp_trunc",
    "extract",
    "now",
    "current_timestamp",
    "lower",
    "upper",
    "length",
    "cast",
    # J1-f (spec §7): deliberate analytics extension alongside the journal views.
    "stddev",
    "percentile_cont",
    # Date-window predicates ("за последнюю неделю") — the skill's own example used
    # CURRENT_DATE and was rejected; fixed here (review item 9).
    "current_date",
}


class ReadonlySqlError(ValueError):
    """Raised when a model-supplied SQL statement is not a safe user-scoped read."""


READONLY_ROLE = "daybook_readonly"


@dataclass(frozen=True)
class ReadonlyView:
    """One user-scoped projection over a base table. Single source of truth for
    both the validator's view surface and the read-only role's grant/RLS surface."""

    name: str
    base_table: str
    select_sql: str


# Each view's column list is exercised against the live schema by
# test_all_view_definitions_execute (a real SELECT per view), which fails if a column drifts.
READONLY_VIEW_DEFS: tuple[ReadonlyView, ...] = (
    ReadonlyView(
        "query_meals",
        "meals",
        # Scalar analytics columns only: document columns would let one guarded
        # ``SELECT *`` stream MAX_LIMIT provenance blobs into the decision prompt.
        "SELECT id, title, raw_input, calories, protein_g, fat_g, carbs_g, "
        "recipe_batch_id, portion_quantity_value, portion_quantity_unit, portion_weight_g, "
        "nutrition_confidence, eaten_at, meal_date, created_at "
        "FROM meals WHERE user_id = :user_id AND deleted_at IS NULL",
    ),
    ReadonlyView(
        "query_activities",
        "activities",
        "SELECT id, category, title, raw_input, started_at, ended_at, activity_date, "
        "duration_minutes, focus_level, created_at FROM activities "
        "WHERE user_id = :user_id AND deleted_at IS NULL",
    ),
    ReadonlyView(
        "query_workouts",
        "workouts",
        # Workout is a 1-1 subtype of activity: title/raw_input/started_at/ended_at/
        # duration_minutes live on the parent activities row, so this view JOINs it.
        # The exposed column set is unchanged, so the model-facing schema stays stable.
        # a.user_id = w.user_id is a defense-in-depth guard: it prevents a cross-user
        # anomaly where a Workout row references another user's Activity via activity_id.
        # a.deleted_at IS NULL: a soft-deleted activity must hide its workout from analytics.
        "SELECT w.id, w.workout_type, a.title, a.raw_input, a.started_at, a.ended_at, "
        "a.duration_minutes, w.created_at "
        "FROM workouts w JOIN activities a ON w.activity_id = a.id AND a.user_id = w.user_id "
        "WHERE w.user_id = :user_id AND a.deleted_at IS NULL",
    ),
    ReadonlyView(
        "query_tasks",
        "tasks",
        "SELECT id, title, description, task_type, status, due_at, created_at "
        "FROM tasks WHERE user_id = :user_id AND deleted_at IS NULL",
    ),
    ReadonlyView(
        "query_journal_entries",
        "journal_entries",
        "SELECT id, entry_type, content, raw_input, emotion, emotion_raw, intensity, "
        "occurred_at, occurred_on, occurred_at_precision, segment_index, created_at "
        "FROM journal_entries WHERE user_id = :user_id AND deleted_at IS NULL",
    ),
    ReadonlyView(
        "query_journal_entry_emotions",
        "journal_entry_emotions",
        # Junction with a denormalized user_id; the parent JOIN hides emotions of
        # soft-deleted entries and e.user_id = je.user_id is the query_workouts
        # defense-in-depth guard against a corrupted cross-user link.
        "SELECT je.entry_id, je.emotion, je.intensity, je.is_primary, je.created_at "
        "FROM journal_entry_emotions je "
        "JOIN journal_entries e ON je.entry_id = e.id AND e.user_id = je.user_id "
        "WHERE je.user_id = :user_id AND e.deleted_at IS NULL",
    ),
    ReadonlyView(
        "query_cbt_records",
        "cbt_records",
        # Deletion semantics are transitive (spec §11): a soft-deleted anchor entry
        # hides its quad; e.user_id = c.user_id is the query_workouts guard.
        "SELECT c.id, c.journal_entry_id, c.kind, c.status, c.situation, c.thought, "
        "c.emotion, c.emotion_raw, c.intensity, c.reaction, c.distortions, "
        "c.evidence_for, c.evidence_against, c.reframe, c.intensity_after, c.created_at "
        "FROM cbt_records c "
        "JOIN journal_entries e ON c.journal_entry_id = e.id AND e.user_id = c.user_id "
        "WHERE c.user_id = :user_id AND c.deleted_at IS NULL AND e.deleted_at IS NULL",
    ),
    ReadonlyView(
        "query_journal_themes",
        "journal_themes",
        "SELECT id, name, status, first_seen_at, last_seen_at, merged_into_theme_id, "
        "created_at FROM journal_themes "
        "WHERE user_id = :user_id AND deleted_at IS NULL",
    ),
    ReadonlyView(
        "query_journal_entry_themes",
        "journal_entry_themes",
        # Junction views JOIN BOTH sides: a deleted entry OR theme hides the link,
        # and both joins carry the user-consistency guard (review items 7/8).
        "SELECT jt.entry_id, jt.theme_id, jt.created_at "
        "FROM journal_entry_themes jt "
        "JOIN journal_entries e ON jt.entry_id = e.id AND e.user_id = jt.user_id "
        "JOIN journal_themes th ON jt.theme_id = th.id AND th.user_id = jt.user_id "
        "WHERE jt.user_id = :user_id "
        "AND e.deleted_at IS NULL AND th.deleted_at IS NULL",
    ),
    ReadonlyView(
        "query_notes",
        "notes",
        "SELECT id, content, url, raw_input, created_at "
        "FROM notes WHERE user_id = :user_id AND deleted_at IS NULL",
    ),
    ReadonlyView(
        "query_tags",
        "tags",
        "SELECT id, name, created_at FROM tags WHERE user_id = :user_id AND deleted_at IS NULL",
    ),
    ReadonlyView(
        "query_note_tags",
        "note_tags",
        "SELECT nt.note_id, nt.tag_id, nt.created_at FROM note_tags nt "
        "JOIN notes n ON nt.note_id = n.id AND n.user_id = nt.user_id "
        "JOIN tags tg ON nt.tag_id = tg.id AND tg.user_id = nt.user_id "
        "WHERE nt.user_id = :user_id "
        "AND n.deleted_at IS NULL AND tg.deleted_at IS NULL",
    ),
    ReadonlyView(
        "query_task_tags",
        "task_tags",
        "SELECT tt.task_id, tt.tag_id, tt.created_at FROM task_tags tt "
        "JOIN tasks t ON tt.task_id = t.id AND t.user_id = tt.user_id "
        "JOIN tags tg ON tt.tag_id = tg.id AND tg.user_id = tt.user_id "
        "WHERE tt.user_id = :user_id "
        "AND t.deleted_at IS NULL AND tg.deleted_at IS NULL",
    ),
)

# Derived surfaces — never hand-maintained in parallel.
READONLY_VIEWS: dict[str, str] = {v.name: v.select_sql for v in READONLY_VIEW_DEFS}
# Base tables in declaration order, de-duplicated (a table may back >1 view).
RLS_TABLES: tuple[str, ...] = tuple(dict.fromkeys(v.base_table for v in READONLY_VIEW_DEFS))

_WRITE_OR_ADMIN = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
)


def _function_name(func: exp.Func) -> str:
    """Return the lowercased canonical name of a function node.

    ``exp.Anonymous`` carries the raw (unrecognized) name in ``.this``; every other
    ``exp.Func`` subclass exposes its canonical name via ``sql_name()`` — for
    ``exp.Anonymous`` that method returns the literal ``"ANONYMOUS"``, so it must be
    handled first.
    """
    if isinstance(func, exp.Anonymous):
        return func.this.lower() if isinstance(func.this, str) else ""
    return func.sql_name().lower()


def _reject_qualified(tree: exp.Expression) -> None:
    """No schema/catalog-qualified table identifiers anywhere in the tree.

    Independent of scope resolution: `public.meals`, `pg_catalog.pg_class`, etc.
    are rejected up front so unqualified-only names are all that reach the
    scope-based allow-list below.
    """
    for table in tree.find_all(exp.Table):
        if table.catalog or table.db:
            raise ReadonlySqlError(f"qualified table reference not allowed: {table.sql()}")


def _validate_physical_table(table: exp.Table) -> None:
    if table.name.lower() not in READONLY_VIEWS:
        raise ReadonlySqlError(f"table not in the allowed view set: {table.name}")


def validate_readonly_sql(sql: str) -> str:
    """Validate ``sql`` is a single user-scoped read; return the normalized SQL.

    Rejects (raising ``ReadonlySqlError``): empty / multi-statement input, any
    write or admin command, non-SELECT top nodes, ``SELECT ... INTO``, references
    to base tables outside the view allow-list, schema/catalog-qualified or quoted
    identifiers resolving to disallowed tables, and any function (typed or anonymous)
    whose canonical name is outside the analytical allow-list.
    """
    stripped = sql.strip()
    if not stripped:
        raise ReadonlySqlError("empty statement")
    try:
        statements = [s for s in sqlglot.parse(stripped, read="postgres") if s is not None]
    except Exception as exc:
        raise ReadonlySqlError(f"unparseable statement: {exc}") from exc
    if len(statements) != 1:
        raise ReadonlySqlError("exactly one statement is allowed")
    tree = statements[0]

    if isinstance(tree, _WRITE_OR_ADMIN):
        raise ReadonlySqlError("only SELECT / WITH ... SELECT is allowed")
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery, exp.With)):
        raise ReadonlySqlError("only SELECT / WITH ... SELECT is allowed")
    if tree.find(exp.Into) is not None:
        raise ReadonlySqlError("SELECT ... INTO is not allowed")

    # Reject recursive CTEs outright: the agent never needs them and they are an
    # unbounded-work vector. `exp.With(recursive=True)` carries the flag.
    if any(with_node.args.get("recursive") for with_node in tree.find_all(exp.With)):
        raise ReadonlySqlError("recursive CTE not allowed")

    # No schema/catalog-qualified identifiers (cheap, scope-independent guard).
    _reject_qualified(tree)

    # Scope-aware base-table allow-list. `traverse_scope` resolves CTE references
    # to sub-scopes, so a name only counts as a CTE in the scope where it is
    # actually visible. Every genuine PHYSICAL table survives as an `exp.Table`
    # in `scope.sources` and must be one of the read-only views. This is
    # the fix for the global-cte-name differential: an inner `WITH meals AS (...)`
    # no longer whitelists an outer `FROM meals` (which binds to the base table).
    try:
        scopes = traverse_scope(tree)
    except Exception as exc:  # fail closed on anything sqlglot cannot resolve
        raise ReadonlySqlError(f"unresolvable statement: {exc}") from exc
    for scope in scopes:
        for source in scope.sources.values():
            if isinstance(source, exp.Table):
                _validate_physical_table(source)

    # Gate every function node — typed (``exp.Count`` etc.) and ``exp.Anonymous``
    # alike — by canonical name. ``exp.Func`` is the base class covering both, so a
    # single walk closes the gap where typed nodes (``version()``, ``current_user``,
    # ``generate_series(...)``, ``md5(...)``) previously bypassed the allow-list.
    for func in tree.find_all(exp.Func):
        fname = _function_name(func)
        if fname not in _ALLOWED_FUNCTIONS:
            raise ReadonlySqlError(f"function not allowed: {fname}")

    return tree.sql(dialect="postgres")


def _bounded_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, int(limit)))


def _scoped_query(statement: str, *, user_id: uuid.UUID, limit: int) -> str:
    # Render every scoped CTE each time so any referenced view is defined, then wrap
    # the validated user statement in a bounded outer SELECT. A validated statement
    # may itself redefine one of these names as a CTE; that is safe — every injected
    # CTE is scoped to the same user_id literal, so the worst case is
    # a user reading their own data through a differently-shaped view, never another
    # user's rows or a base table.
    user_literal = str(uuid.UUID(str(user_id)))
    ctes = []
    for name, view_sql in READONLY_VIEWS.items():
        scoped_sql = view_sql.replace(":user_id", f"'{user_literal}'")
        ctes.append(f"{name} AS ({scoped_sql})")
    return f"WITH {', '.join(ctes)} SELECT * FROM ({statement}) AS _scoped LIMIT {limit}"


async def run_user_scoped_readonly_sql(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    sql: str,
    limit: int | None = None,
    statement_timeout_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Validate, scope, and execute a model-supplied read-only SQL statement.

    Defense in depth, in order: AST validation, ``SET TRANSACTION READ ONLY``,
    ``statement_timeout``, user-scoped view CTEs, and a bounded outer row limit.

    ``statement_timeout_ms`` defaults to ``Settings.readonly_sql_statement_timeout_ms``
    (settings-configurable, 2s default) when not supplied by the caller.
    """
    if statement_timeout_ms is None:
        from app.core.config import get_settings

        statement_timeout_ms = get_settings().readonly_sql_statement_timeout_ms
    statement = validate_readonly_sql(sql)
    bounded = _bounded_limit(limit)
    wrapped = _scoped_query(statement, user_id=user_id, limit=bounded)
    await session.execute(text(READONLY_TRANSACTION_SQL))
    await session.execute(text(f"SET LOCAL statement_timeout = {statement_timeout_ms}"))
    # Bind the RLS key for this transaction. Under the dedicated read-only role,
    # the RLS policy `user_id = current_setting('app.user_id', true)::uuid` filters
    # every base-table read to this user — the row-level layer beneath the parser
    # and the user-scoped view CTEs. is_local=true scopes it to this transaction.
    await session.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user_id)},
    )
    result = await session.execute(text(wrapped))
    return [dict(row) for row in result.mappings().all()]
