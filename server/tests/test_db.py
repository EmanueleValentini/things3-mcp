import pytest

from things3_mcp.db import SchemaError, ThingsDB


def titles(rows):
    return [row["title"] for row in rows]


def test_schema_check_passes(db):
    counts = db.check_schema()
    assert counts["projects"] == 2
    assert counts["headings"] == 2


def test_schema_check_reports_missing_columns(db, db_path):
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE TMChecklistItem")
    conn.commit()
    conn.close()
    with pytest.raises(SchemaError, match="TMChecklistItem"):
        db.check_schema()


def test_inbox_only_holds_unfiled_todos(db):
    assert titles(db.inbox()) == ["Idea sparsa"]


def test_today_excludes_future_and_inbox(db):
    assert titles(db.today()) == ["Cosa di oggi"]


def test_upcoming_only_future(db):
    assert titles(db.upcoming()) == ["Cosa futura"]


def test_someday_and_logbook_and_trash(db):
    assert titles(db.someday()) == ["Un giorno"]
    assert titles(db.logbook()) == ["Fatto"]
    assert titles(db.trash()) == ["Cestinato"]


def test_completed_and_trashed_stay_out_of_open_lists(db):
    open_titles = titles(db.anytime(limit=100))
    assert "Fatto" not in open_titles
    assert "Cestinato" not in open_titles


def test_area_is_inherited_from_the_parent_project(db):
    todo = db.get("todo-claimed")
    assert todo["area"] == "Agents"
    assert todo["project"] == "Refactor auth"
    assert todo["heading"] == "Phase 1"


def test_tags_come_through(db):
    assert set(db.get("todo-claimed")["tags"]) == {"agent", "wip", "agent:claude"}


def test_project_tree_groups_by_heading(db):
    tree = db.project_tree("proj-stream")
    assert [h["title"] for h in tree["headings"]] == ["Phase 1", "Phase 2"]
    assert titles(tree["headings"][0]["todos"]) == ["Read the code", "Write the tests"]
    assert titles(tree["todos"]) == ["Ship it"]


def test_project_tree_rejects_unknown_uuid(db):
    with pytest.raises(LookupError):
        db.project_tree("nope")


def test_checklist(db):
    assert db.checklist("todo-free") == [{"title": "primo passo", "done": False}]


def test_search_by_text_matches_notes(db):
    assert titles(db.search(query="idraulico")) == ["Chiamare l'idraulico"]
    assert titles(db.search(query="123")) == ["Chiamare l'idraulico"]


def test_search_filters_combine(db):
    assert titles(db.search(tag="wip", area="Agents")) == ["Read the code"]
    assert db.search(tag="wip", area="Casa") == []


def test_search_can_reach_completed_items(db):
    assert titles(db.search(status="completed")) == ["Fatto"]


def test_projects_filtered_by_area(db):
    assert titles(db.projects(area="Agents")) == ["Refactor auth"]


def test_missing_database_is_reported_clearly(config, tmp_path):
    config.db_path = tmp_path / "absent.sqlite"
    with pytest.raises(Exception, match="not found"):
        ThingsDB(config).areas()
