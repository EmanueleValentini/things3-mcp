"""The agent workspace: Things projects used as an agent's own work tracker.

Conventions, all enforced here so Claude and Codex behave identically:

* one area (default "Agents") holds every agent work stream
* one project per stream, headings are the phases of the plan
* tags: ``agent`` marks agent-owned items, ``agent:<id>`` marks the owner,
  ``wip`` a claimed task, ``blocked`` a stuck one, ``needs-review`` a finished
  one waiting on the user
* progress is appended to the notes as timestamped lines, never overwritten

These tools write only inside the agents area, so they need no confirmation.
Anything touching the user's own projects goes through the general tools, which
gate destructive changes.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from .dates import now_iso
from .permissions import PermissionDenied
from .services import Services
from .tools_write import build_attributes, build_project_items

TAG_AGENT = "agent"
TAG_WIP = "wip"
TAG_BLOCKED = "blocked"
TAG_REVIEW = "needs-review"


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
                f"{item.get('title')!r} is in {item.get('area') or 'no area'}, not the "
                f"'{config.agents_area}' area. The agent_* tools only manage the agent "
                "workspace; use the general tools for the user's own items."
            )
        return item

    def _log(uuid: str, line: str) -> None:
        writer.update(uuid, "todo", {"append-notes": f"\n[{now_iso()}] {line}"})

    @server.tool()
    def agent_workspace_init() -> dict[str, Any]:
        """Check that the agents area exists and report what is in it.

        Call this before the first agent_* write in a session. Areas cannot be
        created through Things' automation interfaces, so if it is missing the
        result explains the one-time manual step.
        """
        area = db.area_by_title(config.agents_area)
        if area is None:
            return {
                "ready": False,
                "area": config.agents_area,
                "action_needed": (
                    f"Create an area named '{config.agents_area}' in Things "
                    "(File > New Area, or the + button at the bottom of the sidebar). "
                    "Things does not allow creating areas from automation. Once it "
                    "exists, call this tool again."
                ),
            }
        streams = db.projects(area=config.agents_area, limit=100)
        return {
            "ready": True,
            "area": config.agents_area,
            "area_uuid": area["uuid"],
            "agent_id": config.agent_id,
            "write_scope": config.write_scope,
            "streams": [
                {"uuid": s["uuid"], "title": s["title"], "when": s.get("when")}
                for s in streams
            ],
        }

    @server.tool()
    def agent_create_stream(
        title: str,
        notes: str | None = None,
        phases: list[str] | None = None,
        todos: list[dict] | None = None,
        when: str | None = None,
        deadline: str | None = None,
    ) -> dict[str, Any]:
        """Create a work stream: one project in the agents area.

        `phases` become headings in order. Each entry of `todos` is an object
        with `title` and optionally `notes`, `heading` (a phase title),
        `checklist` and `deadline`. Everything is created in one call.
        """
        area = db.area_by_title(config.agents_area)
        if area is None:
            raise PermissionDenied(
                f"The '{config.agents_area}' area does not exist yet. "
                "Call agent_workspace_init first."
            )
        attributes = build_attributes(
            title, notes, when, deadline, [TAG_AGENT, owner_tag(config.agent_id)]
        )
        attributes["area-id"] = area["uuid"]
        items = build_project_items(phases, todos, extra_tags=[TAG_AGENT])
        if items:
            attributes["items"] = items

        project = writer.create([{"type": "project", "attributes": attributes}], title)
        guard.audit("agent_create_stream", "ok", uuid=project["uuid"], title=title)
        return db.project_tree(project["uuid"])

    @server.tool()
    def agent_status(stream: str | None = None) -> dict[str, Any]:
        """What the agent workspace currently looks like.

        Returns each stream with its open, in-progress and blocked counts, plus
        the tasks this agent currently holds. Pass `stream` (title or uuid) to
        drill into one project.
        """
        if stream:
            matches = [
                p
                for p in db.projects(area=config.agents_area, limit=100)
                if stream in (p.get("uuid"), p.get("title"))
            ]
            if not matches:
                raise LookupError(f"No agent stream matching {stream!r}")
            return db.project_tree(matches[0]["uuid"])

        streams = []
        for project in db.projects(area=config.agents_area, limit=100):
            todos = db.children(project["uuid"])
            streams.append(
                {
                    "uuid": project["uuid"],
                    "title": project["title"],
                    "open": len(todos),
                    "wip": [t["title"] for t in todos if TAG_WIP in t.get("tags", [])],
                    "blocked": [
                        t["title"] for t in todos if TAG_BLOCKED in t.get("tags", [])
                    ],
                }
            )
        mine = db.search(tag=owner_tag(config.agent_id), area=config.agents_area, limit=50)
        return {
            "agent_id": config.agent_id,
            "area": config.agents_area,
            "streams": streams,
            "claimed_by_me": [
                {"uuid": t["uuid"], "title": t["title"], "project": t.get("project")}
                for t in mine
                if TAG_WIP in t.get("tags", [])
            ],
        }

    @server.tool()
    def agent_next_task(stream: str | None = None) -> dict[str, Any]:
        """The next unclaimed, unblocked task in the agent workspace.

        Respects project and heading order, so phases are worked in sequence.
        Returns `{"empty": true}` when there is nothing left to pick up.
        """
        projects = db.projects(area=config.agents_area, limit=100)
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
