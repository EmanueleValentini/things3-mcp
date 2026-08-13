"""A synthetic database with the same shape as Things', so tests never touch
the user's real data or the app."""

from __future__ import annotations

import sqlite3

import pytest

from things3_mcp.config import Config
from things3_mcp.dates import encode_date
from things3_mcp.db import ThingsDB
from things3_mcp.permissions import Guard
from things3_mcp.services import Services

SCHEMA = """
CREATE TABLE TMTask (
    uuid TEXT PRIMARY KEY, leavesTombstone INTEGER, creationDate REAL,
    userModificationDate REAL, type INTEGER, status INTEGER, stopDate REAL,
    trashed INTEGER DEFAULT 0, title TEXT, notes TEXT, start INTEGER,
    startDate INTEGER, startBucket INTEGER, deadline INTEGER, "index" INTEGER,
    todayIndex INTEGER, area TEXT, project TEXT, heading TEXT,
    checklistItemsCount INTEGER DEFAULT 0, openChecklistItemsCount INTEGER DEFAULT 0
);
CREATE TABLE TMArea (uuid TEXT PRIMARY KEY, title TEXT, visible INTEGER, "index" INTEGER);
CREATE TABLE TMTag (uuid TEXT PRIMARY KEY, title TEXT, parent TEXT, "index" INTEGER);
CREATE TABLE TMTaskTag (tasks TEXT, tags TEXT);
CREATE TABLE TMChecklistItem (
    uuid TEXT PRIMARY KEY, title TEXT, status INTEGER, "index" INTEGER, task TEXT
);
"""

AGENTS_AREA_UUID = "area-agents"
PERSONAL_AREA_UUID = "area-personal"


def _task(cur, uuid, title, **kwargs):
    row = {
        "uuid": uuid,
        "title": title,
        "type": 0,
        "status": 0,
        "trashed": 0,
        "start": 1,
        "index": 0,
        "creationDate": 1786600000.0,
        "userModificationDate": 1786600000.0,
        "notes": None,
        "startDate": None,
        "deadline": None,
        "stopDate": None,
        "area": None,
        "project": None,
        "heading": None,
        "todayIndex": 0,
        "startBucket": 0,
        "checklistItemsCount": 0,
        "openChecklistItemsCount": 0,
    }
    row.update(kwargs)
    columns = ", ".join(f'"{k}"' for k in row)
    cur.execute(
        f"INSERT INTO TMTask ({columns}) VALUES ({', '.join('?' * len(row))})",
        tuple(row.values()),
    )


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "main.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    cur = conn.cursor()

    cur.execute(
        'INSERT INTO TMArea (uuid, title, visible, "index") VALUES (?, ?, 1, 0)',
        (AGENTS_AREA_UUID, "Agents"),
    )
    cur.execute(
        'INSERT INTO TMArea (uuid, title, visible, "index") VALUES (?, ?, 1, 1)',
        (PERSONAL_AREA_UUID, "Casa"),
    )
    for uuid, title in (
        ("tag-agent", "agent"),
        ("tag-wip", "wip"),
        ("tag-owner", "agent:claude"),
    ):
        cur.execute(
            'INSERT INTO TMTag (uuid, title, "index") VALUES (?, ?, 0)', (uuid, title)
        )

    # An agent work stream with two phases.
    _task(cur, "proj-stream", "Refactor auth", type=1, area=AGENTS_AREA_UUID)
    _task(cur, "head-1", "Phase 1", type=2, project="proj-stream", index=0)
    _task(cur, "head-2", "Phase 2", type=2, project="proj-stream", index=1)
    # Things stores a to-do filed under a heading with project NULL: the link to
    # the project runs through the heading. Verified against a live database.
    _task(cur, "todo-claimed", "Read the code", heading="head-1", index=0)
    _task(cur, "todo-free", "Write the tests", heading="head-1", index=1)
    _task(cur, "todo-loose", "Ship it", project="proj-stream", index=2)
    for task_uuid in ("proj-stream", "todo-claimed", "todo-free", "todo-loose"):
        cur.execute("INSERT INTO TMTaskTag VALUES (?, ?)", (task_uuid, "tag-agent"))
    cur.execute("INSERT INTO TMTaskTag VALUES (?, ?)", ("todo-claimed", "tag-wip"))
    cur.execute("INSERT INTO TMTaskTag VALUES (?, ?)", ("todo-claimed", "tag-owner"))

    # The user's own items, outside the agents area.
    _task(cur, "proj-personal", "Trasloco", type=1, area=PERSONAL_AREA_UUID)
    _task(cur, "todo-personal", "Chiamare l'idraulico", project="proj-personal", notes="numero: 123")
    _task(cur, "todo-inbox", "Idea sparsa", start=0)
    _task(cur, "todo-today", "Cosa di oggi", startDate=encode_date("2020-01-01"))
    _task(cur, "todo-future", "Cosa futura", startDate=encode_date("2099-01-01"))
    _task(cur, "todo-someday", "Un giorno", start=2)
    _task(cur, "todo-done", "Fatto", status=3, stopDate=1786600500.0)
    _task(cur, "todo-trashed", "Cestinato", trashed=1)

    cur.execute(
        'INSERT INTO TMChecklistItem (uuid, title, status, "index", task)'
        " VALUES ('cl-1', 'primo passo', 0, 0, 'todo-free')"
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def config(db_path):
    return Config(
        db_path=db_path,
        auth_token="test-token",
        write_scope="confirm-outside",
        agents_area="Agents",
        agent_id="claude",
    )


@pytest.fixture
def db(config):
    return ThingsDB(config)


@pytest.fixture
def guard(config, db):
    return Guard(config, db)


class RefusingWriter:
    """Fails the test if a guarded tool writes without confirmation."""

    def __init__(self):
        self.calls = []

    def send(self, *args, **kwargs):
        raise AssertionError("write attempted without confirmation")

    def create(self, *args, **kwargs):
        raise AssertionError("write attempted without confirmation")

    def update(self, uuid, kind, attributes):
        self.calls.append((uuid, kind, attributes))
        return {"uuid": uuid, "applied": attributes}


@pytest.fixture
def services(config, db, guard):
    return Services(config=config, db=db, writer=RefusingWriter(), guard=guard)
