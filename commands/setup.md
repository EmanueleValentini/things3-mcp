---
description: Configure the Things 3 connection — check the database, grant automation access, store the auth token, pick the write scope.
---

Set up the `things3` MCP server for this machine. Work through the steps in
order and stop at the first one that fails, telling the user exactly what to do.

1. **Check the chain.** Run `health_check`. Report each line in plain language:
   Things installed, database readable, item counts, auth token, write scope,
   agents area.

2. **Automation permission.** Call `get_selection`. The first time, macOS shows
   a dialog asking to let the terminal control Things — tell the user to expect
   it and to click OK. If it fails with a permission error, point them at System
   Settings > Privacy & Security > Automation. Triggering it here means it will
   not interrupt a real task later.

3. **Auth token.** Needed to modify existing items; creating works without it.
   If `health_check` reported no token, ask the user to open Things >
   Settings > General, enable **Things URL scheme**, click **Manage**, and copy
   the token. Then store it with `configure(auth_token="...")`. Never echo the
   token back in your reply.

4. **Write scope.** Ask which they want, defaulting to `confirm-outside`:
   - `agents-only` — the server refuses any write outside the agents area
   - `confirm-outside` — writes anywhere, but you check with them first outside
     the agents area
   - `unrestricted` — no check for ordinary edits
   Destructive operations always need explicit confirmation regardless. Save the
   choice with `configure(write_scope=...)`.

5. **Agent workspace.** Run `agent_workspace_init`. If the area is missing, ask
   the user to create an area named `Agents` in Things (the + at the bottom of
   the sidebar) — automation cannot create areas. Offer to name it something
   else via `configure(agents_area=...)`.

6. **Verify.** Create a to-do titled `things3-mcp setup check` with
   `create_todo`, read it back with `get_item`, then remove it with
   `delete_item(uuid, confirmed=True)` — this one is yours to clean up, so the
   confirmation is not a question for the user. Report that the round trip
   worked.

Finish with a two-line summary: what is configured, and anything still missing.
