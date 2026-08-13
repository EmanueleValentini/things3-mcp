---
name: agent-worklog
description: Use when an agent should track its own multi-step work in Things 3 — turning a plan into a project the user can watch, claiming tasks before working on them, logging progress, handing work back for review, or coordinating with another agent (Claude and Codex) over the same workspace.
---

# Using Things as the agent's work tracker

The `agent_*` tools give you a workspace inside Things: one or more areas
(default a single `Agents`), one project per work stream, headings as phases.
The user sees your plan and your progress in an app they already keep open, on
their phone as well as their Mac.

These tools only write inside the agent areas, so they need no confirmation.
Anything outside them goes through the general tools and their rules.

## Starting

`agent_workspace_init` first: it reports the agent areas and whether each one
exists in Things. If `ready` is false the area is missing — say so and ask
before recreating it, since the user may have removed it on purpose.

To keep domains apart, give each one its own area:
`agent_workspace_init(area="Agents — Dev")` creates and registers it. Adopting
an area that already holds the user's own projects returns a preview instead —
that needs their yes, because it would put their work under rules that skip
confirmation. Never fall back to writing into their projects because an area
was missing.

## Turning a plan into a stream

One `agent_create_stream` call per piece of work:

```
agent_create_stream(
  title="Things3MCP — write layer",
  notes="Repo: ~/Documents/DEV/REPOS/Things3MCP",
  phases=["Design", "Implement", "Verify"],
  todos=[
    {"title": "URL scheme payload builder", "heading": "Implement"},
    {"title": "Rate limit queue", "heading": "Implement"},
    {"title": "Live smoke test", "heading": "Verify",
     "checklist": ["create", "read back", "trash"]},
  ],
)
```

Task titles should say what will be true when the task is done, and each one
should be finishable in a single sitting. A stream with two tasks is not worth
creating; keep that work in the conversation.

## The working loop

1. `agent_next_task` — the first unclaimed, unblocked task, in phase order.
2. `agent_claim_task(uuid)` — take it. Fails if another agent holds it, which is
   how two agents share one workspace without collisions. Claim *before* you
   start, not after.
3. Do the work. `agent_log_progress(uuid, note)` at real milestones — a decision
   taken, a file written, a test passing. Not every tool call; the notes are for
   a person reading later.
4. `agent_complete_task(uuid, summary)` when it is genuinely done. Pass
   `needs_review=True` instead when the user should look before it counts —
   that leaves it open and tagged `needs-review`.

If you get stuck: `agent_block_task(uuid, reason)` with a reason the user can
act on, then move to the next task. Do not mark blocked work complete.

## Honesty rules

The worklog is only useful if it is true.

- Complete a task only when the work is done and verified. Tests failing means
  the task is not complete — log the failure and keep it open.
- Do not claim tasks you are not about to start; a claimed task looks in
  progress to everyone else.
- Log what happened, including what did not work.

## Two agents, one workspace

`agent_id` distinguishes them (`claude`, `codex`, ...) via `configure` or the
`THINGS_AGENT_ID` environment variable. Claims are visible as `wip` plus
`agent:<id>`, so `agent_status` shows who holds what. If a task you need is
claimed by someone else, pick another one — never strip their tags to take it.

## Reporting back

`agent_status` gives per-stream open/wip/blocked counts and what you currently
hold. Use it to open a session ("here's where we left off") and to close one.
