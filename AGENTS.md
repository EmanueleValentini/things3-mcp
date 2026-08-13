# Things 3 — rules for agents

This repo hosts the `things3` MCP server. When it is connected, these rules
apply to any agent using it, in this repo or anywhere else.

## The three rules

1. **Reads are free.** Every `list_*`, `get_item` and `search` call reads a
   local database. Use them freely to answer questions.

2. **Writes outside the agent areas touch the user's own system.** Say what you
   are about to create or change and get agreement in the same turn. An
   agreement covers the batch you described, not the rest of the session.

3. **Destructive operations return a preview, not a result.** `delete_item`,
   `cancel_item`, `set_notes`, `remove_tags`, `move_item` out of a project,
   `empty_trash`, and `complete_item` on items you did not create all respond
   with `confirmation_required` until called with `confirmed=true`. Show the
   preview, ask, then call again. Setting `confirmed=true` without an explicit
   yes from the user in that turn is a violation, not a shortcut — the flag
   represents their decision, not your confidence.

## The agent workspace

The `agent_*` tools manage one or more areas in Things (default a single
`Agents`) that belong to agents rather than the user. They refuse to touch
anything outside them, and need no confirmation inside them. Several areas let
one domain be kept apart from another.

- `agent_workspace_init` — report the agent areas, or add one. A new area is
  created straight away; adopting an area that already holds the user's
  projects needs their confirmation first
- `agent_create_stream` — a project with phases as headings, in any agent area
- `agent_next_task` / `agent_claim_task` — pick up work, one holder at a time
- `agent_log_progress` / `agent_block_task` — record what happened
- `agent_complete_task` — finish, or hand back with `needs_review=True`

Claim before starting. Complete only when the work is done and verified — a
failing test means the task stays open with the failure logged. Multiple agents
share the workspace: `THINGS_AGENT_ID` (`claude`, `codex`, ...) separates the
claims, and you never strip another agent's tags to take their task.

## Setup

- Claude Code: `/plugin marketplace add EmanueleValentini/things3-mcp` then
  `/plugin install things3@things3`, then `/things3:setup`.
- Codex: `scripts/install-codex.sh`, restart, then ask it to run `health_check`.

Modifying existing items needs the Things auth token (Things > Settings >
General > Enable Things URL scheme > Manage), stored via
`configure(auth_token="...")`. Creating items works without it.

## Working on this repo

- Server code lives in `server/src/things3_mcp/`; tests in `server/tests/`.
- `cd server && uv run pytest` — the suite builds its own synthetic database and
  never touches real Things data or launches the app.
- Everything that knows the Things sqlite schema is in `db.py`. If Things
  changes its schema, that is the only file to fix, and `health_check` is what
  reports the breakage.
