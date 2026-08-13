# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Because this is a plugin people install and then trust with their task manager,
two rules shape what counts as a breaking change:

- removing or renaming a tool, or changing what its arguments mean, is **major**
- anything that lets an agent write or delete with *less* consent than before is
  **major** too, however small the diff

## [Unreleased]

### Fixed

- `health_check` no longer crashes on a machine without Things 3 — a Linux
  sandbox, for instance. It reports what is missing, which is its whole job.

### Documentation

- Installing on Cowork, which uses the same plugin format and the same
  marketplace command.

## [0.1.0] — 2026-08-13

First release. Reads Things 3 from its database, writes through the URL scheme,
and gives agents a workspace of their own inside the app.

### Added

- **Reading** — `list_inbox`, `list_today`, `list_upcoming`, `list_anytime`,
  `list_someday`, `list_logbook`, `list_trash`, `list_projects`, `list_areas`,
  `list_tags`, `get_item`, `search`, `get_selection`. All served from the Things
  database directly, so they neither open nor focus the app.
- **Writing** — `create_todo`, `create_project` (headings, to-dos and checklists
  in one call), `update_item`, `append_note`, `add_checklist_items`,
  `complete_item`, `cancel_item`, `set_notes`, `remove_tags`, `move_item`,
  `delete_item`, `delete_area`, `empty_trash`, `show_in_things`.
- **Agent workspace** — `agent_workspace_init`, `agent_create_stream`,
  `agent_status`, `agent_next_task`, `agent_claim_task`, `agent_log_progress`,
  `agent_block_task`, `agent_complete_task`. One or more areas belong to agents;
  a project is a work stream and its headings are the phases. Claims stop two
  agents taking the same task.
- **Consent** — destructive operations ask the user through the client over MCP
  elicitation. Clients without it get a preview for the agent to relay, and the
  agent must wait for a reply in a separate message. `confirmed=true` never
  overrides a refusal.
- **Guard rails** — `THINGS_WRITE_SCOPE` confines writes to the agent areas,
  `empty_trash` is off unless `THINGS_ALLOW_EMPTY_TRASH=1`, and every write is
  appended to `~/.config/things3-mcp/audit.log` with the channel that granted
  consent.
- **Setup** — `health_check`, `configure`, and the `/things3:setup`,
  `/things3:standup`, `/things3:new-project` commands.
- **Codex** — `scripts/install-codex.sh` registers the server and installs the
  skills, so both agents share one workspace.

### Notes on Things' actual behaviour

Four undocumented behaviours were found by testing against the live app, and
each is now encoded and covered by tests:

- the `heading` attribute of the JSON command is ignored; a to-do belongs to
  whichever heading precedes it in the items array
- a to-do filed under a heading is stored with `project` NULL and is reachable
  only through its heading
- tags that do not already exist are dropped silently, so they are created over
  AppleScript first
- areas and tags *can* be created by automation, despite the scripting
  dictionary marking both elements read-only

[Unreleased]: https://github.com/EmanueleValentini/things3-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/EmanueleValentini/things3-mcp/releases/tag/v0.1.0
