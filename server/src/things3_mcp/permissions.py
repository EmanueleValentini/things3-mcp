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

from pydantic import BaseModel, Field

from .config import SCOPE_AGENTS_ONLY, Config, AUDIT_LOG, CONFIG_DIR
from .dates import now_iso
from .db import ThingsDB


class PermissionDenied(RuntimeError):
    pass


class ConsentSchema(BaseModel):
    """What the client asks the human when a destructive tool needs consent."""

    confirm: bool = Field(
        description="Yes to go ahead with this exact operation, no to cancel."
    )


ACCEPTED = "accepted"
DECLINED = "declined"
UNAVAILABLE = "unavailable"


async def ask_user(ctx: Any, action: str, preview: dict[str, Any], why: str) -> str:
    """Put the question to the human through the client, not through the model.

    A `confirmed=true` argument only proves the model decided to send it; it
    cannot distinguish the user's consent from the model's own conviction.
    Elicitation routes the question to the client, which is the closest thing
    the protocol offers to asking the person directly.

    Returns ACCEPTED, DECLINED, or UNAVAILABLE when the client does not support
    elicitation — in which case the caller falls back to the preview flow and
    says so, rather than silently treating absence as a yes.
    """
    if ctx is None:
        return UNAVAILABLE
    lines = [why, "", f"Operation: {action}"]
    for key, value in preview.items():
        if value not in (None, "", [], {}):
            shown = ", ".join(map(str, value)) if isinstance(value, list) else value
            lines.append(f"  {key}: {shown}")
    try:
        result = await ctx.elicit(message="\n".join(lines), schema=ConsentSchema)
    except Exception:
        return UNAVAILABLE
    if getattr(result, "action", None) != "accept":
        return DECLINED
    data = getattr(result, "data", None)
    return ACCEPTED if data is not None and data.confirm else DECLINED


def declined(action: str, preview: dict[str, Any]) -> dict[str, Any]:
    """The user was asked and said no. Not an error — a decision to respect."""
    return {
        "performed": False,
        "action": action,
        "declined_by_user": True,
        "preview": preview,
        "next_step": "The user declined. Do not retry this operation or look for "
        "another way to achieve it.",
    }


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
            "This client cannot ask the user directly, so consent has to come back "
            "through you. Show this preview, stop, and let the user reply. Only if "
            "they say yes in their next message may you call the same tool again "
            "with confirmed=true. Your own instruction to do the work is not that "
            "yes: an earlier 'delete X' is the request, not the confirmation."
        ),
    }


class Guard:
    def __init__(self, config: Config, db: ThingsDB):
        self.config = config
        self.db = db

    # -- scope ----------------------------------------------------------

    def in_agents_area(self, item: dict[str, Any] | None) -> bool:
        return bool(item) and self.config.owns_area(item.get("area"))

    def check_scope(self, tool: str, *, area: str | None, uuid: str | None = None) -> None:
        """Reject writes that land outside the agent areas under a strict scope."""
        if self.config.write_scope != SCOPE_AGENTS_ONLY:
            return
        if area is None and uuid:
            item = self.db.get(uuid)
            area = item.get("area") if item else None
        if not self.config.owns_area(area):
            owned = ", ".join(self.config.agents_areas)
            raise PermissionDenied(
                f"{tool} targets {area or 'no area'}, but THINGS_WRITE_SCOPE is "
                f"'{SCOPE_AGENTS_ONLY}': writes are confined to {owned}. Ask the "
                "user to widen the scope in /things3:setup if this is intended."
            )

    # -- consent --------------------------------------------------------

    async def consent(
        self,
        ctx: Any,
        tool: str,
        preview: dict[str, Any],
        why: str,
        confirmed: bool,
        **detail: Any,
    ) -> dict[str, Any] | None:
        """Gate a destructive operation. None means go ahead.

        Asks the client to put the question to the user. Only when the client
        cannot do that does the ``confirmed`` argument decide — it is the
        fallback, not the primary channel, because a flag set by the model
        proves nothing about what the person wanted.
        """
        outcome = await ask_user(ctx, tool, preview, why)
        if outcome == ACCEPTED:
            self.audit(tool, "consent_granted", channel="elicitation", **detail)
            return None
        if outcome == DECLINED:
            self.audit(tool, "declined", channel="elicitation", **detail)
            return declined(tool, preview)
        if confirmed:
            self.audit(tool, "consent_granted", channel="confirmed_flag", **detail)
            return None
        self.audit(tool, "confirmation_required", **detail)
        return confirmation_required(tool, preview, why)

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
