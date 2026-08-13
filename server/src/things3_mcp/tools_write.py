"""Write tools.

Creates go through `things:///json`; trashing goes through AppleScript.
Destructive operations refuse to act until the caller passes confirmed=true —
see permissions.py for what counts as destructive and why it is enforced here
rather than in a prompt.
"""

from __future__ import annotations

import subprocess
import urllib.parse
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import applescript
from .permissions import confirmation_required
from .services import Services

AGENT_TAG = "agent"


def build_attributes(
    title: str | None = None,
    notes: str | None = None,
    when: str | None = None,
    deadline: str | None = None,
    tags: list[str] | None = None,
    completed: bool | None = None,
    canceled: bool | None = None,
) -> dict[str, Any]:
    """Common attribute block for the Things JSON command.

    `when` accepts today, tomorrow, evening, anytime, someday or an ISO date.
    """
    attributes: dict[str, Any] = {}
    if title is not None:
        attributes["title"] = title
    if notes is not None:
        attributes["notes"] = notes
    if when is not None:
        attributes["when"] = when
    if deadline is not None:
        attributes["deadline"] = deadline
    if tags:
        attributes["tags"] = tags
    if completed is not None:
        attributes["completed"] = completed
    if canceled is not None:
        attributes["canceled"] = canceled
    return attributes


def checklist_block(items: list[str] | None) -> list[dict[str, Any]]:
    return [
        {"type": "checklist-item", "attributes": {"title": item}} for item in items or []
    ]


def todo_block(todo: dict[str, Any], extra_tags: list[str] | None = None) -> dict[str, Any]:
    """One to-do record for a project's `items` array."""
    attributes = build_attributes(
        todo.get("title"),
        todo.get("notes"),
        todo.get("when"),
        todo.get("deadline"),
        [*(extra_tags or []), *(todo.get("tags") or [])],
    )
    if todo.get("checklist"):
        attributes["checklist-items"] = checklist_block(todo["checklist"])
    return {"type": "to-do", "attributes": attributes}


def build_project_items(
    headings: list[str] | None,
    todos: list[dict] | None,
    extra_tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Lay out a project's contents for the Things JSON command.

    Things assigns a to-do to whichever heading precedes it in the array; the
    `heading` attribute that works on `things:///add` is ignored here. So the
    list is built positionally: unfiled to-dos first, then each heading
    immediately followed by the to-dos that belong to it. A to-do naming a
    heading that does not exist stays unfiled rather than landing under an
    unrelated phase.
    """
    headings = headings or []
    todos = todos or []
    known = set(headings)
    grouped: dict[str, list[dict]] = {heading: [] for heading in headings}
    unfiled: list[dict] = []
    for todo in todos:
        heading = todo.get("heading")
        (grouped[heading] if heading in known else unfiled).append(todo)

    items = [todo_block(todo, extra_tags) for todo in unfiled]
    for heading in headings:
        items.append({"type": "heading", "attributes": {"title": heading}})
        items.extend(todo_block(todo, extra_tags) for todo in grouped[heading])
    return items


def register(server: MCPServer, services: Services) -> None:
    db, writer, guard, config = (
        services.db,
        services.writer,
        services.guard,
        services.config,
    )

    def _agent_owned(uuid: str) -> bool:
        """Items the agent layer created: in the agents area and tagged `agent`."""
        item = db.get(uuid)
        return bool(item) and guard.in_agents_area(item) and AGENT_TAG in item.get("tags", [])

    # -- create ---------------------------------------------------------

    @server.tool()
    def create_todo(
        title: str,
        notes: str | None = None,
        project: str | None = None,
        heading: str | None = None,
        area: str | None = None,
        when: str | None = None,
        deadline: str | None = None,
        tags: list[str] | None = None,
        checklist: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a to-do.

        `project` and `area` take a title or a uuid; `heading` takes a heading
        title inside that project. `when` is today, tomorrow, evening, anytime,
        someday or an ISO date. Landing outside the agents area is allowed but
        should be confirmed with the user first.
        """
        guard.check_scope("create_todo", area=area if area else _area_of(project))
        attributes = build_attributes(title, notes, when, deadline, tags)
        if project:
            attributes["list" if not _is_uuid(project) else "list-id"] = project
        elif area:
            attributes["area" if not _is_uuid(area) else "area-id"] = area
        if heading:
            attributes["heading"] = heading
        if checklist:
            attributes["checklist-items"] = checklist_block(checklist)
        item = writer.create([{"type": "to-do", "attributes": attributes}], title)
        guard.audit("create_todo", "ok", uuid=item.get("uuid"), title=title)
        return item

    @server.tool()
    def create_project(
        title: str,
        notes: str | None = None,
        area: str | None = None,
        when: str | None = None,
        deadline: str | None = None,
        tags: list[str] | None = None,
        headings: list[str] | None = None,
        todos: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Create a project, with its headings and to-dos, in one operation.

        `headings` are phase titles in order. Each entry of `todos` is an object
        with `title` and optionally `notes`, `heading`, `when`, `deadline`,
        `tags` and `checklist` (a list of strings). Building the whole tree in
        one call avoids the URL scheme rate limit.
        """
        guard.check_scope("create_project", area=area)
        attributes = build_attributes(title, notes, when, deadline, tags)
        if area:
            attributes["area" if not _is_uuid(area) else "area-id"] = area

        items = build_project_items(headings, todos)
        if items:
            attributes["items"] = items

        project = writer.create([{"type": "project", "attributes": attributes}], title)
        guard.audit("create_project", "ok", uuid=project.get("uuid"), title=title)
        return db.project_tree(project["uuid"])

    # -- non-destructive updates ---------------------------------------

    @server.tool()
    def update_item(
        uuid: str,
        title: str | None = None,
        when: str | None = None,
        deadline: str | None = None,
        add_tags: list[str] | None = None,
        project: str | None = None,
        heading: str | None = None,
        area: str | None = None,
    ) -> dict[str, Any]:
        """Change an existing to-do or project without destroying anything.

        Only the fields you pass are touched; tags are added, never replaced.
        To rewrite notes use `set_notes`, to move an item out of its project use
        `move_item` — both of those need confirmation.
        """
        item = db.get(uuid)
        if item is None:
            raise LookupError(f"No item with uuid {uuid}")
        guard.check_scope("update_item", area=item.get("area"), uuid=uuid)
        attributes = build_attributes(title, None, when, deadline)
        if add_tags:
            attributes["add-tags"] = add_tags
        if project:
            attributes["list" if not _is_uuid(project) else "list-id"] = project
        if heading:
            attributes["heading"] = heading
        if area:
            attributes["area" if not _is_uuid(area) else "area-id"] = area
        if not attributes:
            return item
        result = writer.update(uuid, item.get("type", "todo"), attributes)
        guard.audit("update_item", "ok", uuid=uuid, fields=sorted(attributes))
        return result

    @server.tool()
    def append_note(uuid: str, text: str, position: str = "end") -> dict[str, Any]:
        """Add a line to an item's notes, keeping what is already there.

        `position` is end or start. This is the safe way to record progress;
        it never overwrites existing content.
        """
        item = db.get(uuid)
        if item is None:
            raise LookupError(f"No item with uuid {uuid}")
        guard.check_scope("append_note", area=item.get("area"), uuid=uuid)
        key = "prepend-notes" if position == "start" else "append-notes"
        result = writer.update(uuid, item.get("type", "todo"), {key: text})
        guard.audit("append_note", "ok", uuid=uuid, position=position)
        return result

    @server.tool()
    def add_checklist_items(uuid: str, items: list[str]) -> dict[str, Any]:
        """Append checklist items to an existing to-do."""
        item = db.get(uuid)
        if item is None:
            raise LookupError(f"No item with uuid {uuid}")
        guard.check_scope("add_checklist_items", area=item.get("area"), uuid=uuid)
        result = writer.update(
            uuid, "todo", {"append-checklist-items": checklist_block(items)}
        )
        guard.audit("add_checklist_items", "ok", uuid=uuid, count=len(items))
        return result

    # -- destructive: require confirmed=true ----------------------------

    @server.tool()
    def complete_item(uuid: str, confirmed: bool = False) -> dict[str, Any]:
        """Mark a to-do or project as done.

        Items the agent itself created in the agents area complete immediately.
        Anything else returns a preview first and completes only when called
        again with confirmed=true after the user agrees.
        """
        item = db.get(uuid)
        if item is None:
            raise LookupError(f"No item with uuid {uuid}")
        guard.check_scope("complete_item", area=item.get("area"), uuid=uuid)
        if not confirmed and not _agent_owned(uuid):
            guard.audit("complete_item", "confirmation_required", uuid=uuid)
            return confirmation_required(
                "complete_item",
                {"uuid": uuid, "title": item.get("title"), "project": item.get("project")},
                "This item was not created by the agent, so completing it changes the "
                "user's own list.",
            )
        result = writer.update(uuid, item.get("type", "todo"), {"completed": True})
        guard.audit("complete_item", "ok", uuid=uuid, title=item.get("title"))
        return result

    @server.tool()
    def cancel_item(uuid: str, confirmed: bool = False) -> dict[str, Any]:
        """Mark a to-do or project as canceled. Always needs confirmation."""
        item = db.get(uuid)
        if item is None:
            raise LookupError(f"No item with uuid {uuid}")
        guard.check_scope("cancel_item", area=item.get("area"), uuid=uuid)
        if not confirmed:
            guard.audit("cancel_item", "confirmation_required", uuid=uuid)
            return confirmation_required(
                "cancel_item",
                {"uuid": uuid, "title": item.get("title"), "project": item.get("project")},
                "Canceling hides the item from active lists.",
            )
        result = writer.update(uuid, item.get("type", "todo"), {"canceled": True})
        guard.audit("cancel_item", "ok", uuid=uuid, title=item.get("title"))
        return result

    @server.tool()
    def set_notes(uuid: str, notes: str, confirmed: bool = False) -> dict[str, Any]:
        """Replace an item's notes wholesale. Prefer append_note.

        Always needs confirmation: the previous notes are shown in the preview
        so nothing is lost silently.
        """
        item = db.get(uuid)
        if item is None:
            raise LookupError(f"No item with uuid {uuid}")
        guard.check_scope("set_notes", area=item.get("area"), uuid=uuid)
        if not confirmed:
            guard.audit("set_notes", "confirmation_required", uuid=uuid)
            return confirmation_required(
                "set_notes",
                {
                    "uuid": uuid,
                    "title": item.get("title"),
                    "current_notes": item.get("notes"),
                    "new_notes": notes,
                },
                "This overwrites the existing notes.",
            )
        result = writer.update(uuid, item.get("type", "todo"), {"notes": notes})
        guard.audit("set_notes", "ok", uuid=uuid)
        return result

    @server.tool()
    def remove_tags(uuid: str, tags: list[str], confirmed: bool = False) -> dict[str, Any]:
        """Remove tags from an item. Needs confirmation — tags carry meaning
        in the user's own workflow."""
        item = db.get(uuid)
        if item is None:
            raise LookupError(f"No item with uuid {uuid}")
        guard.check_scope("remove_tags", area=item.get("area"), uuid=uuid)
        remaining = [tag for tag in item.get("tags", []) if tag not in tags]
        if not confirmed:
            guard.audit("remove_tags", "confirmation_required", uuid=uuid)
            return confirmation_required(
                "remove_tags",
                {
                    "uuid": uuid,
                    "title": item.get("title"),
                    "current_tags": item.get("tags", []),
                    "tags_after": remaining,
                },
                "The Things URL scheme can only replace the whole tag list, so "
                "removal rewrites it.",
            )
        result = writer.update(uuid, item.get("type", "todo"), {"tags": remaining})
        guard.audit("remove_tags", "ok", uuid=uuid, removed=tags)
        return result

    @server.tool()
    def move_item(
        uuid: str,
        project: str | None = None,
        area: str | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Move an item to another project or area.

        Needs confirmation when it leaves its current project, since that
        reorganises the user's structure.
        """
        item = db.get(uuid)
        if item is None:
            raise LookupError(f"No item with uuid {uuid}")
        guard.check_scope("move_item", area=area or item.get("area"), uuid=uuid)
        # `project` may arrive as a title or a uuid; either one matching means
        # the item is staying where it is.
        leaving = bool(item.get("project")) and project not in (
            item.get("project"),
            item.get("project_uuid"),
        )
        if leaving and not confirmed:
            guard.audit("move_item", "confirmation_required", uuid=uuid)
            return confirmation_required(
                "move_item",
                {
                    "uuid": uuid,
                    "title": item.get("title"),
                    "from": item.get("project") or item.get("area"),
                    "to": project or area,
                },
                "Moving takes the item out of the project it lives in now.",
            )
        attributes: dict[str, Any] = {}
        if project:
            attributes["list" if not _is_uuid(project) else "list-id"] = project
        if area:
            attributes["area" if not _is_uuid(area) else "area-id"] = area
        result = writer.update(uuid, item.get("type", "todo"), attributes)
        guard.audit("move_item", "ok", uuid=uuid, to=project or area)
        return result

    @server.tool()
    def delete_item(uuid: str, confirmed: bool = False) -> dict[str, Any]:
        """Move an item to the Things trash. Always needs confirmation.

        Recoverable from the trash inside Things until the trash is emptied.
        """
        item = db.get(uuid)
        if item is None:
            raise LookupError(f"No item with uuid {uuid}")
        guard.check_scope("delete_item", area=item.get("area"), uuid=uuid)
        if not confirmed:
            guard.audit("delete_item", "confirmation_required", uuid=uuid)
            return confirmation_required(
                "delete_item",
                {
                    "uuid": uuid,
                    "title": item.get("title"),
                    "type": item.get("type"),
                    "project": item.get("project"),
                    "area": item.get("area"),
                },
                "This moves the item to the trash. A project takes its to-dos with it.",
            )
        applescript.trash(uuid)
        guard.audit("delete_item", "ok", uuid=uuid, title=item.get("title"))
        return {"trashed": uuid, "title": item.get("title")}

    @server.tool()
    def empty_trash(confirmed: bool = False) -> dict[str, Any]:
        """Permanently delete everything in the Things trash. Irreversible.

        Disabled unless THINGS_ALLOW_EMPTY_TRASH=1, and even then requires
        confirmed=true.
        """
        if not config.allow_empty_trash:
            raise PermissionError(
                "Emptying the trash is disabled. It cannot be undone. If the user "
                "really wants it, they can set THINGS_ALLOW_EMPTY_TRASH=1 or do it "
                "in Things directly."
            )
        pending = db.trash(limit=200)
        if not confirmed:
            guard.audit("empty_trash", "confirmation_required", count=len(pending))
            return confirmation_required(
                "empty_trash",
                {"count": len(pending), "items": [i.get("title") for i in pending[:20]]},
                "Permanent deletion. There is no undo.",
            )
        applescript.empty_trash()
        guard.audit("empty_trash", "ok", count=len(pending))
        return {"emptied": len(pending)}

    # -- navigation -----------------------------------------------------

    @server.tool()
    def show_in_things(uuid: str | None = None, list_name: str | None = None) -> str:
        """Bring Things to the front showing an item or a built-in list.

        `list_name` is inbox, today, upcoming, anytime, someday or logbook.
        """
        target = uuid or list_name or "today"
        subprocess.run(
            ["open", f"things:///show?id={urllib.parse.quote(target)}"],
            capture_output=True,
            check=False,
        )
        return f"Opened {target} in Things."

    def _area_of(project: str | None) -> str | None:
        if not project:
            return None
        matches = db.projects(limit=200)
        for candidate in matches:
            if project in (candidate.get("uuid"), candidate.get("title")):
                return candidate.get("area")
        return None


def _is_uuid(value: str) -> bool:
    """Things uuids are 22-character tokens with no spaces; titles rarely are."""
    return len(value) >= 20 and " " not in value
