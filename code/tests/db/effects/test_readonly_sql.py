from __future__ import annotations

import uuid
from typing import Any, cast

import pytest

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
from app.models.food import Meal
from tests.db.effects._helpers import create_agent_run, create_user


class _FakeMappings:
    def all(self) -> list[dict[str, object]]:
        return []


class _FakeResult:
    def mappings(self) -> _FakeMappings:
        return _FakeMappings()


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
        # Pre-existing live bug (review item 9): the analytical_sql.md example itself
        # is rejected today — current_date joins the allow-list in this slice.
        "SELECT SUM(calories) FROM query_meals WHERE meal_date = CURRENT_DATE - 1",
        ("SELECT COUNT(*) FROM query_journal_entries WHERE occurred_on >= CURRENT_DATE - 7"),
    ],
)
def test_accepts_safe_reads_over_views(sql: str) -> None:
    validate_readonly_sql(sql)


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
        "query_activities",
        "query_workouts",
        "query_tasks",
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
    assert "portion_weight_g" in query_meals  # G1 compatibility until Task 15

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


def test_rls_tables_derived_from_view_defs() -> None:
    from app.db.effects.readonly_sql import READONLY_VIEWS, RLS_TABLES

    assert RLS_TABLES == (
        "meals",
        "activities",
        "workouts",
        "tasks",
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
    assert len(READONLY_VIEWS) == 13


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
