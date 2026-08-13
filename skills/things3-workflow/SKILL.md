---
name: things3-workflow
description: Use when the user wants to manage tasks, projects, areas or their day in Things 3 — capturing to-dos, planning a project with phases, reviewing what is due, tidying the inbox, or asking what they should work on. Covers the natural-language workflow on top of the things3 MCP tools.
---

# Managing Things 3

The `things3` MCP server reads the Things database directly and writes through
the app. Reads are always safe; writes touch the user's real system.

## Before anything else

Run `health_check` once per session if you have not already. It tells you
whether the database is readable, whether the auth token is present (needed to
modify existing items), and which write scope is in effect. If something is
missing it says what to do — usually `/things3:setup`.

## Finding things

Prefer the narrow tool over a broad one:

| The user says | Use |
|---|---|
| "what's on today" | `list_today` |
| "what's coming up" | `list_upcoming` |
| "what's in my inbox" | `list_inbox` |
| "anything about the mortgage" | `search(query="mutuo")` |
| "what's in project X" | `get_item(uuid_of_X)` — returns headings and to-dos |
| "this task" (no name) | `get_selection` — what they have selected in the app |

`search` combines filters with AND: `search(tag="urgente", area="Lavoro")`.
Always resolve a name to a uuid with `search` or `list_projects` before editing,
and never invent a uuid.

## Capturing

`create_todo` for a single task. Fill in what the user actually said and no
more — do not invent deadlines, tags or projects. `when` accepts `today`,
`tomorrow`, `evening`, `anytime`, `someday` or an ISO date; `deadline` is the
hard due date and is not the same thing as `when`.

## Planning a project

`create_project` builds the whole tree in one call — this is the main thing this
server is for. Sketch the structure in chat first, get agreement, then create:

```
create_project(
  title="Trasloco",
  area="Casa",
  headings=["Prima del trasloco", "Il giorno stesso", "Dopo"],
  todos=[
    {"title": "Preventivi traslochi", "heading": "Prima del trasloco",
     "checklist": ["Ditta A", "Ditta B"]},
    {"title": "Cambio residenza", "heading": "Dopo", "deadline": "2026-09-30"},
  ],
)
```

Headings are phases, not categories of everything — three to six is usually
right. If the user describes more than about 40 to-dos, create the project with
the first phases and add the rest with `create_todo` afterwards.

## Changing existing items

- `update_item` — title, dates, added tags, move into a project or heading.
  Non-destructive: it only touches the fields you pass and tags are added, never
  replaced.
- `append_note` — add a line to notes, keeping what is there.
- `complete_item` — mark done.

## What needs the user's word first

Two separate rules, both enforced by the server so you cannot slip past them:

1. **Outside the agents area.** Creating or changing something in the user's own
   projects is allowed, but say what you are about to do and get agreement in
   the same turn. One agreement covers the batch you described, not the rest of
   the session.
2. **Destructive operations** — `delete_item`, `cancel_item`, `set_notes`,
   `remove_tags`, `move_item` out of a project, `empty_trash`, and
   `complete_item` on anything you did not create. These return
   `confirmation_required` with a preview instead of acting. Show the preview,
   ask, and only call again with `confirmed=true` after an explicit yes. Never
   set `confirmed=true` because it seems obvious — that flag represents the
   user's decision, not yours.

If a tool returns `confirmation_required`, that is not an error and not
something to work around with a different tool.

## Reviewing

For a daily review: `list_today`, then `list_inbox` for anything unfiled, then
`search(deadline_before=...)` for what is closing in. Report it as a short
summary, not a dump of every field — the user knows their own tasks.
