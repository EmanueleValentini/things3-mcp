"""MCP server entry point."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from . import agents, applescript, tools_read, tools_write
from .config import WRITE_SCOPES, Config, parse_areas
from .db import DatabaseUnavailable, SchemaError
from .services import Services

INSTRUCTIONS = """\
Controls Things 3 on macOS.

Reads come from the Things database and are always safe. Writes go to the app.
Three rules:

1. Writing anywhere outside the agent areas touches the user's own system —
   say what you are about to create or change and get agreement first.
2. Destructive tools (delete_item, cancel_item, set_notes, remove_tags,
   move_item, empty_trash, and complete_item on items you did not create)
   return a preview instead of acting. Show the preview to the user and call
   again with confirmed=true only after they say yes. Never set confirmed=true
   on your own.
3. The agent_* tools are your own workspace inside the agent areas. Use them to
   track your work; they need no confirmation.

Run health_check if anything behaves unexpectedly.
"""


def build_server() -> MCPServer:
    services = Services.build()
    server = MCPServer(
        name="things3",
        version="0.1.0",
        instructions=INSTRUCTIONS,
    )

    @server.tool()
    def health_check() -> dict[str, Any]:
        """Verify the whole chain: app present, database readable, schema as
        expected, auth token available, automation permission granted.

        Reports what works and what to do about what does not.
        """
        config = services.config
        report: dict[str, Any] = {
            "things_installed": applescript.is_installed(),
            "database": str(config.db_path) if config.db_path else None,
            "auth_token": bool(config.auth_token),
            "write_scope": config.write_scope,
            "agents_areas": config.agents_areas,
            "agent_id": config.agent_id,
        }
        problems: list[str] = []

        if not report["things_installed"]:
            problems.append("Things 3 is not in /Applications.")
        try:
            report["counts"] = services.db.check_schema()
            report["database_readable"] = True
        except (DatabaseUnavailable, SchemaError) as error:
            report["database_readable"] = False
            problems.append(str(error))

        if not config.auth_token:
            problems.append(
                "No auth token: creating items works, updating existing ones does "
                "not. Run /things3:setup."
            )
        missing_areas = [
            name for name in config.agents_areas if services.db.area_by_title(name) is None
        ]
        if missing_areas:
            problems.append(
                f"Agent areas not in Things yet: {', '.join(missing_areas)}. "
                "agent_workspace_init creates them."
            )

        report["ok"] = not problems
        report["problems"] = problems
        return report

    @server.tool()
    def configure(
        auth_token: str | None = None,
        write_scope: str | None = None,
        agents_areas: list[str] | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist settings to ~/.config/things3-mcp/config.json.

        `write_scope` is agents-only, confirm-outside or unrestricted.
        `agents_areas` replaces the list of areas agents own; the first is where
        new work streams go. To add one area without listing them all, and to
        create it in Things, use agent_workspace_init instead. `agent_id`
        distinguishes agents that share the workspace (claude, codex, ...).
        The token is stored with 0600 permissions and never echoed back.
        """
        updates: dict[str, Any] = {}
        if auth_token is not None:
            updates["auth_token"] = auth_token.strip()
        if write_scope is not None:
            if write_scope not in WRITE_SCOPES:
                raise ValueError(f"write_scope must be one of {WRITE_SCOPES}")
            updates["write_scope"] = write_scope
        if agents_areas is not None:
            areas = parse_areas(agents_areas)
            if not areas:
                raise ValueError("agents_areas cannot be empty")
            updates["agents_areas"] = areas
        if agent_id is not None:
            updates["agent_id"] = agent_id
        if updates:
            services.config.save(**updates)
        return {
            "saved": sorted(updates),
            "auth_token": bool(services.config.auth_token),
            "write_scope": services.config.write_scope,
            "agents_areas": services.config.agents_areas,
            "agent_id": services.config.agent_id,
        }

    tools_read.register(server, services)
    tools_write.register(server, services)
    agents.register(server, services)
    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
