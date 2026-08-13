# things3-mcp

Control [Things 3](https://culturedcode.com/things/) from Claude Code and Codex,
in natural language — and let agents keep their own work plan inside Things,
where you can watch it from your Mac or your phone.

macOS only. Requires Things 3 and [uv](https://docs.astral.sh/uv/).

## What it does

**For you:** "cosa ho oggi?", "crea un progetto per il trasloco con le fasi
prima/durante/dopo", "cosa è in ritardo?". Reading is instant — it queries the
Things database directly rather than driving the app.

**For agents:** dedicated areas in Things where an agent turns a plan into a
project, claims tasks one at a time, logs progress into the notes, and hands
work back for review. Two agents (Claude and Codex) can share them without
stepping on each other, and you can keep one domain apart from another by
giving it its own area.

## Install

### Claude Code

```bash
/plugin marketplace add EmanueleValentini/things3-mcp
```

```bash
/plugin install things3@things3
```

Then run `/things3:setup` — it checks the database, triggers the macOS
automation prompt, stores the auth token and picks a write scope.

### Codex

```bash
git clone https://github.com/EmanueleValentini/things3-mcp.git && ./things3-mcp/scripts/install-codex.sh
```

Registers `[mcp_servers.things3]` in `~/.codex/config.toml` (backing up the
existing file) and installs the skills into `~/.codex/skills/`. Restart Codex,
then ask it to run `health_check`.

## Commands

| Command | What it does |
|---|---|
| `/things3:setup` | Configure the connection end to end |
| `/things3:standup` | Daily review: today, overdue, agent streams, decisions |
| `/things3:new-project` | Propose a project with phases, create it once approved |

## How it talks to Things

| Direction | Channel | Why |
|---|---|---|
| Read | sqlite, read-only | Fast, complete, does not open or focus the app |
| Write | `things:///json` URL scheme | The only channel that creates headings and checklist items, and builds a whole project in one call |
| Trash, new tags | AppleScript | Not available in the URL scheme |

The URL scheme silently ignores any tag that does not already exist — no error,
the tag is just missing afterwards. Every write therefore creates its missing
tags over AppleScript first, so `agent`, `wip` and the rest appear the first
time they are used rather than vanishing.

Writes are serialised behind a rate limit, since Things drops anything past 250
items per 10 seconds, and each one polls the database afterwards so a create can
be followed immediately by a read.

## Safety

Three levels, enforced in the server rather than in prompts, so they hold for
any client:

- **Automatic** — all reads, and any write inside an agent area.
- **Check first** — creating or editing in your own projects. The agent
  describes it and asks before the first write.
- **The user is asked, always** — `delete_item`, `delete_area`, `cancel_item`,
  `set_notes`, `remove_tags`, moving an item out of its project, `empty_trash`,
  and completing an item the agent did not create, plus adopting an area of
  yours into the agent workspace. The server asks *your client* to put the
  question to you, over MCP elicitation, so the answer comes from you rather
  than from the agent's judgement.

  Not every client supports elicitation — Claude Code, as of this writing, does
  not. There the server falls back to handing the agent a preview to relay, and
  the agent must stop and wait for your reply before calling again with
  `confirmed=true`. The audit log records which of the two channels granted
  consent, so `channel: confirmed_flag` tells you the agent relayed it and
  `channel: elicitation` that the client asked you directly.

`delete_item` moves to the Things trash and is recoverable. `empty_trash` is the
one irreversible operation and is disabled unless `THINGS_ALLOW_EMPTY_TRASH=1`.
Every write is appended to `~/.config/things3-mcp/audit.log`.

`THINGS_WRITE_SCOPE` sets the boundary: `agents-only` (writes confined to the
agent areas), `confirm-outside` (default), `unrestricted`. Destructive
operations need confirmation under all three.

## The agent workspace

Things nests exactly three levels — **area › project › heading › to-do ›
checklist** — and the workspace maps onto them: an area per domain, a project
per work stream, headings as the phases of the plan.

One area is enough to start. `agent_workspace_init("Agents — Dev")` adds
another and creates it in Things, for keeping domains apart. Creating a new
area needs no confirmation, since an empty area holds nothing that could be
damaged; adopting an area that already contains your projects does, because it
would bring that work under rules that skip confirmation.

## Configuration

`~/.config/things3-mcp/config.json`, chmod 0600, written by `configure`.
Environment variables override it:

| Variable | Meaning |
|---|---|
| `THINGS_AUTH_TOKEN` | Needed to modify existing items. Things > Settings > General > Enable Things URL scheme > Manage |
| `THINGS_DB_PATH` | Override database discovery |
| `THINGS_WRITE_SCOPE` | `agents-only` / `confirm-outside` / `unrestricted` |
| `THINGS_AGENTS_AREAS` | Comma-separated areas the agents own (default `Agents`) |
| `THINGS_AGENT_ID` | Distinguishes agents sharing the workspace |
| `THINGS_ALLOW_EMPTY_TRASH` | `1` to allow permanent deletion |

## Tools

Read: `list_inbox`, `list_today`, `list_upcoming`, `list_anytime`,
`list_someday`, `list_logbook`, `list_trash`, `list_projects`, `list_areas`,
`list_tags`, `get_item`, `search`, `get_selection`.

Write: `create_todo`, `create_project`, `update_item`, `append_note`,
`add_checklist_items`, `complete_item`, `cancel_item`, `set_notes`,
`remove_tags`, `move_item`, `delete_item`, `delete_area`, `empty_trash`,
`show_in_things`.

Agent workspace: `agent_workspace_init`, `agent_create_stream`, `agent_status`,
`agent_next_task`, `agent_claim_task`, `agent_log_progress`, `agent_block_task`,
`agent_complete_task`.

System: `health_check`, `configure`.

## Development

```bash
cd server && uv run pytest
```

The suite builds a synthetic database with the same shape as Things' and never
touches your data or launches the app. `scripts/smoke.sh` runs a live end-to-end
check against the real app and cleans up after itself.

Everything that knows the undocumented Things schema is in
`server/src/things3_mcp/db.py`; `health_check` verifies the columns it depends
on and reports clearly if an app update changes them.

MIT.
