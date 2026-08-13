---
description: Daily review from Things — what is on today, what is overdue, what agents are holding, what needs a decision.
---

Give the user a short standup from Things 3. Read only; change nothing.

Gather:

- `list_today`
- `list_inbox` — anything unfiled
- `list_upcoming(limit=10)` — what lands in the next few days
- `search(status="open", deadline_before=<today's date>)` — overdue
- `agent_status` — agent streams, work in progress, blocked items
- `list_logbook(limit=10)` — what got finished recently

Then write, in this order and nothing more:

1. **Oggi** — today's items, one line each.
2. **In ritardo** — overdue, with how late. Skip the section if empty.
3. **Agenti** — per stream: in progress, blocked (with the reason), waiting for
   review. Skip if the workspace is empty.
4. **Da decidere** — inbox items that need filing, and anything blocked waiting
   on the user.

Keep it scannable. No table unless there are more than ten items, no restating
of fields the user can see in the app, no advice they did not ask for. If
something is blocked on them, say what specifically is needed.

$ARGUMENTS may name an area or project to narrow the review to.
