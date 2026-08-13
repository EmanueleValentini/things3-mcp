# things3-mcp

[![CI](https://github.com/EmanueleValentini/things3-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/EmanueleValentini/things3-mcp/actions/workflows/ci.yml)

Talk to [Things 3](https://culturedcode.com/things/) in plain language from
Claude Code and Codex — and let your agents keep their own plan inside Things,
where you can watch it from your Mac or your phone.

macOS only. Needs Things 3 and [uv](https://docs.astral.sh/uv/).

---

## What you can do with it

**Ask about your day.** Reading is instant, because it queries the Things
database directly instead of driving the app — no window steals focus.

> what's on today?
> anything overdue?
> what's sitting in my inbox?
> find everything tagged urgent in the Work area

**Plan out loud.** One sentence becomes a project with phases, to-dos and
checklists, created in a single operation so it appears finished rather than
assembling itself in front of you.

> build me a project for the move, with phases before / during / after
> add "get quotes" under the first phase, with a checklist of three movers
> push everything in the launch project to next week

**Give agents somewhere to work.** An agent turns its plan into a Things
project, claims one task at a time, writes progress into the notes, and hands
work back for review. You follow along in an app you already keep open.

> set up a work stream for the API refactor and start on it
> where did we get to yesterday?
> what's blocked?

---

## Install

### Claude Code

```bash
/plugin marketplace add EmanueleValentini/things3-mcp
```

```bash
/plugin install things3@things3
```

Restart the session so the tools load, then run `/things3:setup`.

An installed plugin is a frozen copy at the version you installed. It does not
follow the repository, so run `/plugin update things3@things3` to pick up a new
release.

### Cowork

Cowork reads the same plugin format, so the same marketplace works there —
add `EmanueleValentini/things3-mcp` from its plugin settings.

One caveat worth knowing before you try: this plugin talks to a Mac app through
its local database and AppleScript. It only works where Things 3 actually runs.
If your Cowork session executes in a Linux sandbox rather than on your Mac,
`health_check` will tell you the database is not there, and no tool will work —
that is a property of where the session runs, not something a plugin can fix.

### Codex

```bash
git clone https://github.com/EmanueleValentini/things3-mcp.git && ./things3-mcp/scripts/install-codex.sh
```

That registers `[mcp_servers.things3]` in `~/.codex/config.toml`, backing up the
existing file, and installs the skills into `~/.codex/skills/`. Restart Codex
and ask it to run `health_check`.

Both agents share one workspace. `THINGS_AGENT_ID` keeps their claims apart.

### The auth token

Creating things works out of the box. **Changing anything that already exists —
tags, notes, dates, completion — needs a token**, because Things guards those
operations: anything on your Mac can open a `things:///` link, so modifying
existing data requires proof.

Things > Settings > General > enable **Things URL scheme** > **Manage**, copy
the token, and ask the agent to run `configure(auth_token="...")`. It is stored
in `~/.config/things3-mcp/config.json` with `0600` permissions and never printed
back. `/things3:setup` walks you through it.

---

## Commands

| Command | What it does |
|---|---|
| `/things3:setup` | Configure the connection end to end and check it works |
| `/things3:standup` | Today, overdue, agent streams, what needs deciding |
| `/things3:new-project` | Propose a project with phases, create it once you approve |

---

## Your data, and who gets to touch it

Three levels, enforced inside the server rather than in a prompt, so they hold
whatever client is talking to it:

- **Automatic** — every read, and any write inside an agent area.
- **Check with you first** — creating or editing in your own projects. The agent
  describes what it is about to do and waits for agreement.
- **You are asked, every time** — `delete_item`, `delete_area`, `cancel_item`,
  `set_notes`, `remove_tags`, moving an item out of its project, `empty_trash`,
  completing an item the agent did not create, and adopting one of your areas
  into the agent workspace.

For that last group the server asks *your client* to put the question to you,
over MCP elicitation, so the answer comes from you and not from the agent's
judgement. **Claude Code does not support elicitation today**, so there the
server hands the agent a preview to relay, and the agent has to stop and wait
for your reply before acting — your original "delete X" is the request, not the
confirmation of the irreversible step.

`delete_item` moves things to the Things trash, where you can get them back.
`empty_trash` is the one irreversible operation and stays off unless you set
`THINGS_ALLOW_EMPTY_TRASH=1`. Deleting an **area** is not recoverable from the
app either — areas never reach the trash — so its preview lists everything that
would lose its grouping.

Every write lands in `~/.config/things3-mcp/audit.log`, including which channel
granted consent: `elicitation` means the client asked you, `confirmed_flag`
means the agent relayed it.

Want a harder boundary? `THINGS_WRITE_SCOPE=agents-only` refuses every write
outside the agent areas. Destructive operations still ask, under every scope.

---

## The agent workspace

Things nests exactly this far — **area › project › heading › to-do › checklist**
— and the workspace maps onto it:

| Things | Agent |
|---|---|
| Area | A domain the agents own (default `Agents`) |
| Project | One work stream |
| Heading | A phase of the plan |
| To-do | A task, claimed by one agent at a time |
| Tags | `agent`, `wip`, `blocked`, `needs-review`, `agent:<id>` |

Ask an agent to add an area and it creates one — a new, empty area is nothing to
be careful with. Asking it to adopt an area that already holds *your* projects
is a different matter, and it has to ask you first.

Claims are how two agents share the workspace: a task tagged `wip` by `claude`
cannot be claimed by `codex`, so they never collide on the same work.

---

## Configuration

`~/.config/things3-mcp/config.json`, written by the `configure` tool.
Environment variables win over it:

| Variable | Meaning |
|---|---|
| `THINGS_AUTH_TOKEN` | Needed to modify existing items |
| `THINGS_DB_PATH` | Point at a different Things database |
| `THINGS_WRITE_SCOPE` | `agents-only` / `confirm-outside` (default) / `unrestricted` |
| `THINGS_AGENTS_AREAS` | Comma-separated areas the agents own |
| `THINGS_AGENT_ID` | Tells agents apart in a shared workspace |
| `THINGS_ALLOW_EMPTY_TRASH` | `1` to allow permanent deletion |

---

## When something is wrong

Run `health_check` first — it tests the whole chain and names what is missing.

**"No auth token"** — creating works, changing existing items does not. See
[the auth token](#the-auth-token).

**Things stops responding, or nothing you create appears.** Things queues
commands but does not process them while a modal window is open. Bring the app
to the front and dismiss whatever it is asking. A telltale sign is AppleScript
timing out with `-1712` while `version` still answers.

**"macOS denied automation access."** System Settings > Privacy & Security >
Automation, and allow your terminal to control Things. `/things3:setup`
triggers the prompt on purpose so it does not interrupt you later.

**A tag or area you asked for is missing.** Both are created for you now, so if
one still does not appear, check `health_check` for automation access — that is
the channel used to create them.

**"Schema differs from what this server expects."** A Things update changed its
database. Reading is unreliable until the server catches up; please
[open an issue](https://github.com/EmanueleValentini/things3-mcp/issues) with
your Things version.

---

## Tools

**Read** — `list_inbox`, `list_today`, `list_upcoming`, `list_anytime`,
`list_someday`, `list_logbook`, `list_trash`, `list_projects`, `list_areas`,
`list_tags`, `get_item`, `search`, `get_selection`

**Write** — `create_todo`, `create_project`, `update_item`, `append_note`,
`add_checklist_items`, `complete_item`, `cancel_item`, `set_notes`,
`remove_tags`, `move_item`, `delete_item`, `delete_area`, `empty_trash`,
`show_in_things`

**Agent workspace** — `agent_workspace_init`, `agent_create_stream`,
`agent_status`, `agent_next_task`, `agent_claim_task`, `agent_log_progress`,
`agent_block_task`, `agent_complete_task`

**System** — `health_check`, `configure`

---

## How it talks to Things

| Direction | Channel | Why |
|---|---|---|
| Read | sqlite, read-only | Fast and complete, and never opens the app |
| Write | `things:///json` URL scheme | The only channel that creates headings and checklist items, and builds a whole project in one call |
| Trash, new tags and areas | AppleScript | Not possible through the URL scheme |

Some of Things' behaviour is undocumented and was found by testing against the
real app: the JSON command ignores a to-do's `heading` attribute and files it
under whichever heading precedes it; to-dos under a heading are stored with no
project of their own; tags that do not exist are dropped in silence, so they get
created first. The [changelog](CHANGELOG.md) has the full list.

Writes are serialised behind a rate limit — Things discards anything past 250
items per 10 seconds — and each one waits for the database to catch up, so a
create can be followed immediately by a read.

---

## Contributing

```bash
cd server && uv run pytest
```

The suite builds its own database, fakes the AppleScript calls, and never
touches your Things data, your config, or the app. `scripts/smoke.sh` is the
live counterpart: it drives the real tools against the real app and cleans up
after itself.

Every pull request adds a line to `CHANGELOG.md` under `## [Unreleased]`,
written for someone using the plugin rather than someone reading the diff. CI
enforces it; label a pull request `no-changelog` if it truly changes nothing
users would notice.

Releases are `./scripts/release.sh <version>`, which bumps both manifests,
closes the changelog section, runs the tests and tags. Pushing the tag publishes
the GitHub release. Two things count as breaking: removing or renaming a tool,
and letting an agent act with less consent than before.

Everything that knows Things' undocumented schema lives in
`server/src/things3_mcp/db.py`, and `health_check` is what tells you when an app
update has broken it.

---

MIT
