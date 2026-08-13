---
description: Turn a description into a Things project with phases, to-dos and checklists — proposed first, created after you approve.
---

Build a Things 3 project from what the user describes in $ARGUMENTS (ask if it
is empty).

**First, propose. Do not create anything yet.**

Draft the structure and show it in chat:

- project title, and which area it belongs in (`list_areas` to see the options)
- phases as headings, in the order the work happens — usually three to six
- to-dos under each phase, each one finishable in a sitting, titled as the
  outcome rather than the activity
- checklists only where the steps are genuinely mechanical
- dates only where the user gave one; do not invent deadlines

Ask what to change. Two rounds of this is normal.

**Then create**, once they agree, with a single `create_project` call carrying
the whole tree — headings, to-dos, checklists together. One call keeps it under
the URL scheme's rate limit and makes the project appear complete rather than
assembling itself.

Read it back with `get_item` and confirm what landed. If the user wants it in
the agent workspace instead — work you will be doing rather than they —
use `agent_create_stream`, which is the same shape inside the `Agents` area.
