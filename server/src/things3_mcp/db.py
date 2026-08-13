"""Read-only access to the Things 3 sqlite database.

Everything that knows about the (undocumented) Things schema lives here, so an
app update that changes it breaks one file rather than the whole server.

The database is opened with ``mode=ro`` and never ``immutable=1``: immutable
skips the WAL, which silently returns data from before the last few edits.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .config import Config
from .dates import decode_date, decode_timestamp, today_upper_bound
from .models import (
    START_ANYTIME,
    START_INBOX,
    START_NAMES,
    START_SOMEDAY,
    STATUS_CANCELED,
    STATUS_COMPLETED,
    STATUS_NAMES,
    STATUS_OPEN,
    TYPE_HEADING,
    TYPE_NAMES,
    TYPE_PROJECT,
    TYPE_TODO,
    compact,
)

REQUIRED_COLUMNS = {
    "TMTask": {
        "uuid",
        "type",
        "status",
        "trashed",
        "title",
        "notes",
        "start",
        "startDate",
        "deadline",
        "area",
        "project",
        "heading",
        "index",
        "stopDate",
        "creationDate",
        "userModificationDate",
    },
    "TMArea": {"uuid", "title", "index"},
    "TMTag": {"uuid", "title"},
    "TMTaskTag": {"tasks", "tags"},
    "TMChecklistItem": {"uuid", "title", "status", "index", "task"},
}


class SchemaError(RuntimeError):
    """The database is readable but does not look like the schema we expect."""


class DatabaseUnavailable(RuntimeError):
    """The database could not be found or opened."""


_TASK_SELECT = """
SELECT
    t.uuid                AS uuid,
    t.title               AS title,
    t.type                AS type,
    t.status              AS status,
    t.notes               AS notes,
    t.start               AS start,
    t.startDate           AS startDate,
    t.deadline            AS deadline,
    t.stopDate            AS stopDate,
    t.creationDate        AS creationDate,
    t.userModificationDate AS modificationDate,
    t."index"             AS "index",
    -- A to-do filed under a heading has project NULL: its project is reached
    -- through the heading, so both are coalesced here.
    COALESCE(t.project, h.project) AS project_uuid,
    COALESCE(p.title, h_p.title)   AS project_title,
    t.heading             AS heading_uuid,
    h.title               AS heading_title,
    COALESCE(t.area, p.area, h_p.area) AS area_uuid,
    COALESCE(a.title, p_a.title, h_a.title) AS area_title,
    t.checklistItemsCount AS checklist_total,
    t.openChecklistItemsCount AS checklist_open,
    (SELECT group_concat(tag.title, char(31))
       FROM TMTaskTag tt JOIN TMTag tag ON tag.uuid = tt.tags
      WHERE tt.tasks = t.uuid) AS tags
FROM TMTask t
LEFT JOIN TMTask p    ON p.uuid = t.project
LEFT JOIN TMTask h    ON h.uuid = t.heading
LEFT JOIN TMTask h_p  ON h_p.uuid = h.project
LEFT JOIN TMArea a    ON a.uuid = t.area
LEFT JOIN TMArea p_a  ON p_a.uuid = p.area
LEFT JOIN TMArea h_a  ON h_a.uuid = h_p.area
"""


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    tags = row["tags"].split(chr(31)) if "tags" in keys and row["tags"] else []
    item = {
        "uuid": row["uuid"],
        "title": row["title"],
        "type": TYPE_NAMES.get(row["type"], str(row["type"])),
        "status": STATUS_NAMES.get(row["status"], str(row["status"])),
        "notes": row["notes"] or None,
        "when": START_NAMES.get(row["start"]),
        "start_date": decode_date(row["startDate"]),
        "deadline": decode_date(row["deadline"]),
        "completed_at": decode_timestamp(row["stopDate"]),
        "created_at": decode_timestamp(row["creationDate"]),
        "modified_at": decode_timestamp(row["modificationDate"]),
        "project": row["project_title"],
        "project_uuid": row["project_uuid"],
        "heading": row["heading_title"],
        "heading_uuid": row["heading_uuid"],
        "area": row["area_title"],
        "area_uuid": row["area_uuid"],
        "tags": tags,
    }
    # Projects carry a -1 open count; only real checklists are reported.
    total, open_count = row["checklist_total"] or 0, row["checklist_open"] or 0
    if total > 0 and open_count >= 0:
        item["checklist"] = f"{total - open_count}/{total}"
    return compact(item)


class ThingsDB:
    def __init__(self, config: Config):
        self.config = config
        self._temp_dir: tempfile.TemporaryDirectory | None = None

    # -- connection -----------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        path = self.config.db_path
        if path is None or not Path(path).exists():
            raise DatabaseUnavailable(
                "Things database not found. Is Things 3 installed and has it been "
                "opened at least once? Set THINGS_DB_PATH to override."
            )
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            conn = sqlite3.connect(f"file:{self._snapshot(path)}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _snapshot(self, path: Path) -> Path:
        """Copy the database plus its WAL sidecars somewhere we can open."""
        if self._temp_dir is None:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="things3-mcp-")
        target_dir = Path(self._temp_dir.name)
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(path) + suffix)
            if source.exists():
                shutil.copy2(source, target_dir / (path.name + suffix))
        return target_dir / path.name

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(sql, tuple(params)).fetchall()

    # -- health ---------------------------------------------------------

    def check_schema(self) -> dict[str, Any]:
        """Verify the tables and columns the read layer depends on."""
        missing: dict[str, list[str]] = {}
        with self._connect() as conn:
            for table, expected in REQUIRED_COLUMNS.items():
                rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                present = {row["name"] for row in rows}
                if not present:
                    missing[table] = ["<table missing>"]
                elif gap := expected - present:
                    missing[table] = sorted(gap)
        if missing:
            raise SchemaError(
                "Things database schema differs from what this server expects "
                f"(missing: {missing}). The app may have been updated; reads are "
                "unreliable until db.py is adjusted."
            )
        counts = self.query(
            "SELECT type, count(*) AS n FROM TMTask WHERE trashed = 0 GROUP BY type"
        )
        return {
            "todos": next((r["n"] for r in counts if r["type"] == TYPE_TODO), 0),
            "projects": next((r["n"] for r in counts if r["type"] == TYPE_PROJECT), 0),
            "headings": next((r["n"] for r in counts if r["type"] == TYPE_HEADING), 0),
        }

    # -- lists ----------------------------------------------------------

    def _tasks(
        self,
        where: str,
        params: Iterable[Any] = (),
        order: str = 't."index"',
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        sql = f"{_TASK_SELECT} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?"
        rows = self.query(sql, (*params, limit, offset))
        return [_row_to_item(row) for row in rows]

    def inbox(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._tasks(
            't.trashed = 0 AND t.status = ? AND t.type = ? AND t.start = ?',
            (STATUS_OPEN, TYPE_TODO, START_INBOX),
            limit=limit,
            offset=offset,
        )

    def today(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._tasks(
            "t.trashed = 0 AND t.status = ? AND t.type IN (?, ?) "
            "AND t.start != ? AND t.startDate IS NOT NULL AND t.startDate <= ?",
            (STATUS_OPEN, TYPE_TODO, TYPE_PROJECT, START_INBOX, today_upper_bound()),
            order='t.todayIndex, t."index"',
            limit=limit,
            offset=offset,
        )

    def upcoming(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._tasks(
            "t.trashed = 0 AND t.status = ? AND t.type IN (?, ?) AND ("
            "  (t.startDate IS NOT NULL AND t.startDate > ?)"
            "  OR (t.startDate IS NULL AND t.deadline IS NOT NULL)"
            ")",
            (STATUS_OPEN, TYPE_TODO, TYPE_PROJECT, today_upper_bound()),
            order="COALESCE(t.startDate, t.deadline)",
            limit=limit,
            offset=offset,
        )

    def anytime(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._tasks(
            "t.trashed = 0 AND t.status = ? AND t.type IN (?, ?) "
            "AND t.start = ? AND (t.startDate IS NULL OR t.startDate <= ?)",
            (STATUS_OPEN, TYPE_TODO, TYPE_PROJECT, START_ANYTIME, today_upper_bound()),
            limit=limit,
            offset=offset,
        )

    def someday(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._tasks(
            "t.trashed = 0 AND t.status = ? AND t.type IN (?, ?) "
            "AND t.start = ? AND t.startDate IS NULL",
            (STATUS_OPEN, TYPE_TODO, TYPE_PROJECT, START_SOMEDAY),
            limit=limit,
            offset=offset,
        )

    def logbook(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._tasks(
            "t.trashed = 0 AND t.status != ? AND t.type IN (?, ?)",
            (STATUS_OPEN, TYPE_TODO, TYPE_PROJECT),
            order="t.stopDate DESC",
            limit=limit,
            offset=offset,
        )

    def trash(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._tasks(
            "t.trashed = 1 AND t.type IN (?, ?)",
            (TYPE_TODO, TYPE_PROJECT),
            order="t.userModificationDate DESC",
            limit=limit,
            offset=offset,
        )

    def projects(
        self,
        area: str | None = None,
        include_completed: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = "t.trashed = 0 AND t.type = ?"
        params: list[Any] = [TYPE_PROJECT]
        if not include_completed:
            where += " AND t.status = ?"
            params.append(STATUS_OPEN)
        if area:
            where += " AND (a.title = ? COLLATE NOCASE OR t.area = ?)"
            params += [area, area]
        return self._tasks(where, params, limit=limit, offset=offset)

    def areas(self) -> list[dict[str, Any]]:
        rows = self.query('SELECT uuid, title FROM TMArea ORDER BY "index"')
        return [{"uuid": r["uuid"], "title": r["title"]} for r in rows]

    def area_by_title(self, title: str) -> dict[str, Any] | None:
        rows = self.query(
            "SELECT uuid, title FROM TMArea WHERE title = ? COLLATE NOCASE LIMIT 1",
            (title,),
        )
        return {"uuid": rows[0]["uuid"], "title": rows[0]["title"]} if rows else None

    def tags(self) -> list[dict[str, Any]]:
        rows = self.query(
            "SELECT tag.uuid, tag.title, parent.title AS parent,"
            " (SELECT count(*) FROM TMTaskTag tt WHERE tt.tags = tag.uuid) AS uses"
            " FROM TMTag tag LEFT JOIN TMTag parent ON parent.uuid = tag.parent"
            ' ORDER BY tag."index"'
        )
        return [compact(dict(r)) for r in rows]

    # -- single items ---------------------------------------------------

    def get(self, uuid: str) -> dict[str, Any] | None:
        rows = self.query(f"{_TASK_SELECT} WHERE t.uuid = ?", (uuid,))
        return _row_to_item(rows[0]) if rows else None

    def checklist(self, task_uuid: str) -> list[dict[str, Any]]:
        rows = self.query(
            'SELECT title, status FROM TMChecklistItem WHERE task = ? ORDER BY "index"',
            (task_uuid,),
        )
        return [
            {"title": r["title"], "done": r["status"] == STATUS_COMPLETED} for r in rows
        ]

    def children(
        self, project_uuid: str, include_completed: bool = False
    ) -> list[dict[str, Any]]:
        """Todos of a project, including those filed under its headings."""
        where = (
            "t.trashed = 0 AND t.type = ? AND (t.project = ? OR t.heading IN"
            " (SELECT uuid FROM TMTask WHERE project = ?))"
        )
        params: list[Any] = [TYPE_TODO, project_uuid, project_uuid]
        if not include_completed:
            where += " AND t.status = ?"
            params.append(STATUS_OPEN)
        return self._tasks(where, params, limit=500)

    def headings(self, project_uuid: str) -> list[dict[str, Any]]:
        rows = self.query(
            f"{_TASK_SELECT} WHERE t.trashed = 0 AND t.type = ? AND t.project = ?"
            ' ORDER BY t."index"',
            (TYPE_HEADING, project_uuid),
        )
        return [{"uuid": r["uuid"], "title": r["title"]} for r in rows]

    def project_tree(
        self, project_uuid: str, include_completed: bool = False
    ) -> dict[str, Any]:
        """A project with its headings and todos grouped in display order."""
        project = self.get(project_uuid)
        if project is None:
            raise LookupError(f"No item with uuid {project_uuid}")
        todos = self.children(project_uuid, include_completed=include_completed)
        by_heading: dict[str | None, list[dict[str, Any]]] = {}
        for todo in todos:
            by_heading.setdefault(todo.get("heading_uuid"), []).append(todo)
        project["todos"] = by_heading.get(None, [])
        project["headings"] = [
            {**heading, "todos": by_heading.get(heading["uuid"], [])}
            for heading in self.headings(project_uuid)
        ]
        return compact(project)

    # -- search ---------------------------------------------------------

    def search(
        self,
        query: str | None = None,
        tag: str | None = None,
        area: str | None = None,
        project: str | None = None,
        status: str = "open",
        type_: str | None = None,
        deadline_before: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = ["t.trashed = 0"]
        params: list[Any] = []
        if status == "open":
            where.append("t.status = ?")
            params.append(STATUS_OPEN)
        elif status in ("completed", "canceled"):
            where.append("t.status = ?")
            params.append(STATUS_COMPLETED if status == "completed" else STATUS_CANCELED)
        if type_ in ("todo", "project", "heading"):
            where.append("t.type = ?")
            params.append({"todo": TYPE_TODO, "project": TYPE_PROJECT, "heading": TYPE_HEADING}[type_])
        if query:
            where.append("(t.title LIKE ? COLLATE NOCASE OR t.notes LIKE ? COLLATE NOCASE)")
            params += [f"%{query}%", f"%{query}%"]
        if tag:
            where.append(
                "EXISTS (SELECT 1 FROM TMTaskTag tt JOIN TMTag g ON g.uuid = tt.tags"
                " WHERE tt.tasks = t.uuid AND g.title = ? COLLATE NOCASE)"
            )
            params.append(tag)
        if area:
            where.append(
                "(a.title = ? COLLATE NOCASE OR p_a.title = ? COLLATE NOCASE"
                " OR h_a.title = ? COLLATE NOCASE)"
            )
            params += [area, area, area]
        if project:
            where.append("(p.title = ? COLLATE NOCASE OR t.project = ?)")
            params += [project, project]
        if deadline_before is not None:
            where.append("t.deadline IS NOT NULL AND t.deadline <= ?")
            params.append(deadline_before)
        return self._tasks(
            " AND ".join(where),
            params,
            order="t.userModificationDate DESC",
            limit=limit,
            offset=offset,
        )
