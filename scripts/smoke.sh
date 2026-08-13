#!/usr/bin/env bash
# Live end-to-end check against the real Things 3 app.
#
# Drives the actual MCP tools — not a hand-built payload — so it catches the
# things unit tests cannot: whether Things really accepts what we send it.
# Creates one sandbox project, reads it back, runs a claim/log/complete cycle,
# then trashes everything it made. Touches nothing that existed beforehand.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../server"

exec uv run python - <<'PY'
import sys

from things3_mcp import tools_write
from things3_mcp.dates import now_iso
from things3_mcp.services import Services

# The test harness knows how to call async tools and how to fake a client that
# can (or cannot) ask the user.
from tests.conftest import FakeContext, FakeServer

services = Services.build()
db = services.db
server = FakeServer()
tools_write.register(server, services)
tools = server.tools

SAYS_YES = FakeContext(True)
SAYS_NO = FakeContext(False)
CANNOT_ASK = FakeContext(None)

failures = []


def check(label, condition):
    print(f"{'ok  ' if condition else 'FAIL'} {label}")
    if not condition:
        failures.append(label)


TITLE = f"things3-mcp smoke {now_iso()}"
print(f"database: {services.config.db_path}")
check("schema matches", bool(db.check_schema()))

project = tools["create_project"](
    title=TITLE,
    notes="created by scripts/smoke.sh — safe to delete",
    headings=["Fase 1", "Fase 2"],
    todos=[
        {"title": "primo task", "heading": "Fase 1", "checklist": ["passo a", "passo b"]},
        {"title": "secondo task", "heading": "Fase 1"},
        {"title": "terzo task", "heading": "Fase 2"},
    ],
)
uuid = project["uuid"]
print(f"created project {uuid}")

try:
    tree = db.project_tree(uuid)
    headings = {h["title"]: [t["title"] for t in h["todos"]] for h in tree["headings"]}
    check("two headings, in order", list(headings) == ["Fase 1", "Fase 2"])
    check("phase 1 holds its two to-dos", headings.get("Fase 1") == ["primo task", "secondo task"])
    check("phase 2 holds its one to-do", headings.get("Fase 2") == ["terzo task"])

    first = tree["headings"][0]["todos"][0]
    check("checklist created", len(db.checklist(first["uuid"])) == 2)
    check("project reachable from the to-do", first.get("project") == TITLE)

    if services.config.auth_token:
        tools["update_item"](uuid=first["uuid"], add_tags=["agent", "wip"])
        check("tags applied", "wip" in (db.get(first["uuid"]).get("tags") or []))

        tools["append_note"](uuid=first["uuid"], text="progress line")
        check("notes appended", "progress line" in (db.get(first["uuid"]).get("notes") or ""))

        # This project is not in the agents area, so completing it is the
        # user's call. With a client that cannot ask, the tool hands back a
        # preview instead of acting.
        preview = tools["complete_item"](uuid=first["uuid"], ctx=CANNOT_ASK)
        check("completing a user item asks first", preview.get("confirmation_required") is True)
        check("still open after the preview", db.get(first["uuid"])["status"] == "open")

        # A model claiming confirmation does not override the person.
        refused = tools["complete_item"](uuid=first["uuid"], confirmed=True, ctx=SAYS_NO)
        check("a no from the user beats confirmed=true", refused.get("declined_by_user") is True)
        check("still open after the refusal", db.get(first["uuid"])["status"] == "open")

        tools["complete_item"](uuid=first["uuid"], ctx=SAYS_YES)
        check("completed once the user agrees", db.get(first["uuid"])["status"] == "completed")

        guarded = tools["set_notes"](uuid=first["uuid"], notes="overwritten", ctx=CANNOT_ASK)
        check("destructive tool asks first", guarded.get("confirmation_required") is True)
        check("nothing was overwritten", "progress line" in (db.get(first["uuid"]).get("notes") or ""))
    else:
        print("skip  update cycle (no auth token configured)")
finally:
    tools["delete_item"](uuid=uuid, ctx=SAYS_YES)
    print(f"trashed {uuid}")

print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("all good")
PY
