"""Write scopes, destructive-operation gating, and the audit log.

Enforced server-side rather than in skill prompts, so the same rules apply to
Claude Code, Codex, or anything else that speaks MCP. Two independent checks:

* **scope** — where a write is allowed to land (see ``THINGS_WRITE_SCOPE``)
* **confirmation** — destructive operations refuse to run unless the caller
  passes ``confirmed=true``, which an agent may only set after the user has
  said yes in the current turn.
"""

from __future__ import annotations

import json
from typing import Any

from .config import SCOPE_AGENTS_ONLY, Config, AUDIT_LOG, CONFIG_DIR
from .dates import now_iso
from .db import ThingsDB


class PermissionDenied(RuntimeError):
    pass


def confirmation_required(action: str, preview: dict[str, Any], why: str) -> dict[str, Any]:
    """The payload a destructive tool returns instead of writing anything.

    The agent must show this to the user and call again with ``confirmed=true``
    only after an explicit yes.
    """
    return {
        "confirmation_required": True,
        "action": action,
        "why": why,
        "preview": preview,
        "next_step": (
            "Show this to the user, ask for explicit confirmation, then call the "
            "same tool again with confirmed=true. Never set confirmed=true on your "
            "own initiative."
        ),
    }


class Guard:
    def __init__(self, config: Config, db: ThingsDB):
        self.config = config
        self.db = db

    # -- scope ----------------------------------------------------------

    def in_agents_area(self, item: dict[str, Any] | None) -> bool:
        return bool(item) and item.get("area") == self.config.agents_area

    def check_scope(self, tool: str, *, area: str | None, uuid: str | None = None) -> None:
        """Reject writes that land outside the agents area under a strict scope."""
        if self.config.write_scope != SCOPE_AGENTS_ONLY:
            return
        if area is None and uuid:
            item = self.db.get(uuid)
            area = item.get("area") if item else None
        if area != self.config.agents_area:
            raise PermissionDenied(
                f"{tool} targets {area or 'no area'}, but THINGS_WRITE_SCOPE is "
                f"'{SCOPE_AGENTS_ONLY}': writes are confined to the "
                f"'{self.config.agents_area}' area. Ask the user to widen the scope "
                "in /things3:setup if this is intended."
            )

    def outside_agents_area(self, uuid: str) -> bool:
        """True when an item lives outside the agents area — used to decide
        whether a non-destructive write still deserves a heads-up."""
        return not self.in_agents_area(self.db.get(uuid))

    # -- audit ----------------------------------------------------------

    def audit(self, tool: str, outcome: str, **detail: Any) -> None:
        entry = {"at": now_iso(), "tool": tool, "outcome": outcome, **detail}
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with AUDIT_LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # auditing must never break the operation it records
