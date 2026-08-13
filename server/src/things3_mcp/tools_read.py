"""Read-only tools. All of these hit sqlite directly and never touch the app."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from .dates import encode_date
from .services import Services


def register(server: MCPServer, services: Services) -> None:
    db = services.db

    @server.tool()
    def list_inbox(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Open to-dos sitting in the Things Inbox (not yet filed anywhere)."""
        return db.inbox(limit=limit, offset=offset)

    @server.tool()
    def list_today(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Everything scheduled for Today, in the order shown in the app."""
        return db.today(limit=limit, offset=offset)

    @server.tool()
    def list_upcoming(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Items scheduled for a future date, or with a deadline but no date."""
        return db.upcoming(limit=limit, offset=offset)

    @server.tool()
    def list_anytime(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """The Anytime list: available work with no future start date."""
        return db.anytime(limit=limit, offset=offset)

    @server.tool()
    def list_someday(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """The Someday list: parked items with no date."""
        return db.someday(limit=limit, offset=offset)

    @server.tool()
    def list_logbook(limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
        """Recently completed or canceled items, newest first."""
        return db.logbook(limit=limit, offset=offset)

    @server.tool()
    def list_trash(limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
        """Items currently in the Things trash."""
        return db.trash(limit=limit, offset=offset)

    @server.tool()
    def list_projects(
        area: str | None = None,
        include_completed: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Projects, optionally restricted to one area by title or uuid."""
        return db.projects(
            area=area, include_completed=include_completed, limit=limit, offset=offset
        )

    @server.tool()
    def list_areas() -> list[dict[str, Any]]:
        """All areas of responsibility, in app order."""
        return db.areas()

    @server.tool()
    def list_tags() -> list[dict[str, Any]]:
        """All tags with their parent tag and how many items use them."""
        return db.tags()

    @server.tool()
    def get_item(uuid: str, include_completed: bool = False) -> dict[str, Any]:
        """Full detail for one to-do or project.

        For a project this returns its headings and the to-dos grouped under
        each one; for a to-do it returns the checklist. Use this before editing
        something so you know its current state.
        """
        item = db.get(uuid)
        if item is None:
            raise LookupError(f"No item with uuid {uuid}")
        if item.get("type") == "project":
            return db.project_tree(uuid, include_completed=include_completed)
        checklist = db.checklist(uuid)
        if checklist:
            item["checklist_items"] = checklist
        return item

    @server.tool()
    def search(
        query: str | None = None,
        tag: str | None = None,
        area: str | None = None,
        project: str | None = None,
        status: str = "open",
        type: str | None = None,
        deadline_before: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Search to-dos and projects by text, tag, area, project or deadline.

        `query` matches title and notes. `status` is open, completed, canceled
        or any. `type` is todo, project or heading. `deadline_before` is an
        ISO date (YYYY-MM-DD). Filters combine with AND.
        """
        return db.search(
            query=query,
            tag=tag,
            area=area,
            project=project,
            status=status,
            type_=type,
            deadline_before=encode_date(deadline_before) | 0x7F if deadline_before else None,
            limit=limit,
            offset=offset,
        )

    @server.tool()
    def get_selection() -> list[dict[str, Any]]:
        """What the user currently has selected in the Things window.

        Useful when the user says "this task" without naming it. Requires
        automation permission and launches Things if it is not running.
        """
        from . import applescript

        return applescript.selected_todos()
