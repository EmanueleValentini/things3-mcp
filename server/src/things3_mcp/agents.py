"""The agent workspace: Things projects used as an agent's own work tracker.

Conventions, all enforced here so Claude and Codex behave identically:

* one or more areas (default a single "Agents") hold the agent work streams —
  several areas let one domain be kept apart from another
* one project per stream, headings are the phases of the plan
* tags: ``agent`` marks agent-owned items, ``agent:<id>`` marks the owner,
  ``wip`` a claimed task, ``blocked`` a stuck one, ``needs-review`` a finished
  one waiting on the user
* progress is appended to the notes as timestamped lines, never overwritten

These tools write only inside the agent areas, so they need no confirmation.
Anything touching the user's own projects goes through the general tools, which
gate destructive changes.
"""

from __future__ import annotations

import time
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import applescript
from .dates import now_iso
from .permissions import PermissionDenied, confirmation_required
from .services import Services
from .tools_write import build_attributes, build_project_items

TAG_AGENT = "agent"
TAG_WIP = "wip"
TAG_BLOCKED = "blocked"
TAG_REVIEW = "needs-review"

# How long to wait for a newly created area to reach the database.
AREA_TIMEOUT = 3.0


def owner_tag(agent_id: str) -> str:
    return f"agent:{agent_id}"


def register(server: MCPServer, services: Services) -> None:
    db, writer, guard, config = (
        services.db,
        services.writer,
        services.guard,
        services.config,
    )

    def _require_agents_area(uuid: str) -> dict[str, Any]:
        item = db.get(uuid)
        if item is None:
            raise LookupError(f"No item with uuid {uuid}")
        if not guard.in_agents_area(item):
            raise PermissionDenied(
                f"{item.get('title')!r} is in {item.get('area') or 'no area'}, not an "
                f"agent area ({', '.join(config.agents_areas)}). The agent_* tools only "
                "manage the agent workspace; use the general tools for the user's own "
                "items."
            )
        return item

    def _log(uuid: str, line: str) -> None:
        writer.update(uuid, "todo", {"append-notes": f"\n[{now_iso()}] {line}"})

    def _create_area(name: str) -> dict[str, Any] | None:
        """Create an area and wait for it to reach the database.

        AppleScript returns as soon as Things accepts the command, but the row
        lands a moment later — without this, a workspace report taken right
        after creating an area says the area does not exist.
        """
        applescript.create_area(name)
        deadline = time.monotonic() + AREA_TIMEOUT
        while time.monotonic() < deadline:
            record = db.area_by_title(name)
            if record is not None:
                return record
            time.sleep(0.1)
        return None

    def _all_streams() -> list[dict[str, Any]]:
        """Every project across every agent area, areas in configured order."""
        streams: list[dict[str, Any]] = []
        for name in config.agents_areas:
            streams.extend(db.projects(area=name, limit=100))
        return streams

    @server.tool()
    def agent_workspace_init(area: str | None = None, confirmed: bool = False) -> dict[str, Any]:
        """Set up or inspect the agent workspace.

        With no argument, reports the areas agents already own and what is in
        them. Pass `area` to add another one — useful for separating domains,
        one area per domain and one project per work stream inside it.

        A new area is created and registered straight away: an empty area holds
        nothing that could be damaged. Adopting an area that already contains
        the user's own items is different — it would bring their work under
        rules that skip confirmation — so that returns a preview and needs
        `confirmed=true` after they agree.
        """
        if area:
            existing = db.area_by_title(area)
            if existing is None:
                _create_area(area)
                created = True
            else:
                created = False
                contents = db.projects(area=area, limit=100)
                if not config.owns_area(area) and contents and not confirmed:
                    guard.audit("agent_workspace_init", "confirmation_required", area=area)
                    return confirmation_required(
                        "agent_workspace_init",
                        {
                            "area": area,
                            "existing_projects": [p["title"] for p in contents],
                        },
                        f"'{area}' already holds the user's own projects. Adding it to "
                        "the agent workspace lets agents write there without asking "
                        "each time.",
                    )
            if not config.owns_area(area):
                config.save(agents_areas=[*config.agents_areas, area])
            guard.audit("agent_workspace_init", "ok", area=area, created=created)

        report = []
        for name in config.agents_areas:
            record = db.area_by_title(name)
            report.append(
                {
                    "area": name,
                    "exists": record is not None,
                    "streams": [
                        {"uuid": s["uuid"], "title": s["title"], "when": s.get("when")}
                        for s in (db.projects(area=name, limit=100) if record else [])
                    ],
                }
            )
        return {
            "ready": all(entry["exists"] for entry in report),
            "default_area": config.agents_area,
            "agent_id": config.agent_id,
            "write_scope": config.write_scope,
            "areas": report,
        }

    @server.tool()
    def agent_create_stream(
        title: str,
        notes: str | None = None,
        phases: list[str] | None = None,
        todos: list[dict] | None = None,
        when: str | None = None,
        deadline: str | None = None,
        area: str | None = None,
    ) -> dict[str, Any]:
        """Create a work stream: one project in an agent area.

        `phases` become headings in order. Each entry of `todos` is an object
        with `title` and optionally `notes`, `heading` (a phase title),
        `checklist` and `deadline`. Everything is created in one call.

        `area` picks which agent area to put it in, for workspaces split by
        domain; it defaults to the first one. Use agent_workspace_init to add
        an area before naming it here.
        """
        target = area or config.agents_area
        if not config.owns_area(target):
            owned = ", ".join(config.agents_areas)
            raise PermissionDenied(
                f"'{target}' is not an agent area (agents own: {owned}). Add it with "
                "agent_workspace_init, or use create_project to put a project in one "
                "of the user's own areas."
            )
        area_record = db.area_by_title(target) or _create_area(target)
        if area_record is None:
            raise PermissionDenied(
                f"Could not create or find the '{target}' area in Things."
            )
        attributes = build_attributes(
            title, notes, when, deadline, [TAG_AGENT, owner_tag(config.agent_id)]
        )
        attributes["area-id"] = area_record["uuid"]
        items = build_project_items(phases, todos, extra_tags=[TAG_AGENT])
        if items:
            attributes["items"] = items

        project = writer.create([{"type": "project", "attributes": attributes}], title)
        guard.audit("agent_create_stream", "ok", uuid=project["uuid"], title=title)
        return db.project_tree(project["uuid"])

    @server.tool()
    def agent_status(stream: str | None = None, area: str | None = None) -> dict[str, Any]:
        """What the agent workspace currently looks like.

        Covers every agent area. Returns each stream with its open, in-progress
        and blocked counts, plus the tasks this agent currently holds. Pass
        `stream` (title or uuid) to drill into one project, or `area` to limit
        the report to one domain.
        """
        if stream:
            matches = [
                p for p in _all_streams() if stream in (p.get("uuid"), p.get("title"))
            ]
            if not matches:
                raise LookupError(f"No agent stream matching {stream!r}")
            return db.project_tree(matches[0]["uuid"])

        if area and not config.owns_area(area):
            raise PermissionDenied(
                f"'{area}' is not an agent area ({', '.join(config.agents_areas)})."
            )
        streams = []
        for project in _all_streams():
            if area and project.get("area", "").casefold() != area.casefold():
                continue
            todos = db.children(project["uuid"])
            streams.append(
                {
                    "uuid": project["uuid"],
                    "title": project["title"],
                    "area": project.get("area"),
                    "open": len(todos),
                    "wip": [t["title"] for t in todos if TAG_WIP in t.get("tags", [])],
                    "blocked": [
                        t["title"] for t in todos if TAG_BLOCKED in t.get("tags", [])
                    ],
                }
            )
        mine = [
            todo
            for name in config.agents_areas
            for todo in db.search(tag=owner_tag(config.agent_id), area=name, limit=50)
        ]
        return {
            "agent_id": config.agent_id,
            "areas": config.agents_areas,
            "streams": streams,
            "claimed_by_me": [
                {"uuid": t["uuid"], "title": t["title"], "project": t.get("project")}
                for t in mine
                if TAG_WIP in t.get("tags", [])
            ],
        }

    @server.tool()
    def agent_next_task(stream: str | None = None, area: str | None = None) -> dict[str, Any]:
        """The next unclaimed, unblocked task in the agent workspace.

        Respects project and heading order, so phases are worked in sequence.
        Searches every agent area unless `area` or `stream` narrows it.
        Returns `{"empty": true}` when there is nothing left to pick up.
        """
        projects = _all_streams()
        if area:
            projects = [
                p for p in projects if p.get("area", "").casefold() == area.casefold()
            ]
        if stream:
            projects = [p for p in projects if stream in (p.get("uuid"), p.get("title"))]
        for project in projects:
            for todo in db.children(project["uuid"]):
                tags = todo.get("tags", [])
                if TAG_WIP in tags or TAG_BLOCKED in tags:
                    continue
                return todo
        return {"empty": True, "reason": "No unclaimed, unblocked tasks in the workspace."}

    @server.tool()
    def agent_claim_task(uuid: str) -> dict[str, Any]:
        """Take ownership of a task before starting work on it.

        Fails if another agent already holds it, so parallel agents do not
        collide. Adds `wip` and the owner tag and stamps the notes.
        """
        item = _require_agents_area(uuid)
        tags = item.get("tags", [])
        if TAG_WIP in tags:
            holder = next(
                (t.split(":", 1)[1] for t in tags if t.startswith("agent:")), "someone"
            )
            if holder != config.agent_id:
                raise PermissionDenied(
                    f"{item['title']!r} is already claimed by {holder}. Pick another "
                    "task with agent_next_task, or ask the user to reassign it."
                )
            return item
        writer.update(
            uuid,
            "todo",
            {
                "add-tags": [TAG_AGENT, TAG_WIP, owner_tag(config.agent_id)],
                "append-notes": f"\n[{now_iso()}] claimed by {config.agent_id}",
            },
        )
        guard.audit("agent_claim_task", "ok", uuid=uuid, agent=config.agent_id)
        return db.get(uuid) or item

    @server.tool()
    def agent_log_progress(uuid: str, note: str) -> dict[str, Any]:
        """Append a timestamped progress line to a task's notes."""
        _require_agents_area(uuid)
        _log(uuid, f"{config.agent_id}: {note}")
        guard.audit("agent_log_progress", "ok", uuid=uuid)
        return db.get(uuid) or {}

    @server.tool()
    def agent_block_task(uuid: str, reason: str) -> dict[str, Any]:
        """Mark a task blocked and say why, so the user can unblock it."""
        _require_agents_area(uuid)
        writer.update(
            uuid,
            "todo",
            {
                "add-tags": [TAG_BLOCKED],
                "append-notes": f"\n[{now_iso()}] blocked ({config.agent_id}): {reason}",
            },
        )
        guard.audit("agent_block_task", "ok", uuid=uuid, reason=reason)
        return db.get(uuid) or {}

    @server.tool()
    def agent_complete_task(
        uuid: str, summary: str, needs_review: bool = False
    ) -> dict[str, Any]:
        """Finish a task: append a summary, drop `wip`, mark it done.

        Set `needs_review` to leave it open and tagged `needs-review` instead,
        for work the user should look at before it counts as finished.
        """
        item = _require_agents_area(uuid)
        remaining = [
            tag for tag in item.get("tags", []) if tag not in (TAG_WIP, TAG_BLOCKED)
        ]
        attributes: dict[str, Any] = {
            "append-notes": f"\n[{now_iso()}] done ({config.agent_id}): {summary}",
        }
        if needs_review:
            attributes["tags"] = [*remaining, TAG_REVIEW]
        else:
            attributes["tags"] = remaining
            attributes["completed"] = True
        writer.update(uuid, "todo", attributes)
        guard.audit(
            "agent_complete_task", "ok", uuid=uuid, review=needs_review, summary=summary
        )
        return db.get(uuid) or item
