"""Configuration: database discovery, auth token, write scope, audit log."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

GROUP_CONTAINER = "JLMPQHK86H.com.culturedcode.ThingsMac"
THINGS_APP = Path("/Applications/Things3.app")

CONFIG_DIR = Path(
    os.environ.get("THINGS3_MCP_CONFIG_DIR", Path.home() / ".config" / "things3-mcp")
)
CONFIG_FILE = CONFIG_DIR / "config.json"
AUDIT_LOG = CONFIG_DIR / "audit.log"

DEFAULT_AGENTS_AREA = "Agents"

# Write scopes, from most to least restrictive. Destructive operations always
# require explicit confirmation regardless of the scope in effect.
SCOPE_AGENTS_ONLY = "agents-only"
SCOPE_CONFIRM_OUTSIDE = "confirm-outside"
SCOPE_UNRESTRICTED = "unrestricted"
WRITE_SCOPES = (SCOPE_AGENTS_ONLY, SCOPE_CONFIRM_OUTSIDE, SCOPE_UNRESTRICTED)


def find_database() -> Path | None:
    """Locate main.sqlite inside the Things group container.

    The ThingsData-* directory carries a per-install suffix, so it is globbed
    rather than hardcoded.
    """
    override = os.environ.get("THINGS_DB_PATH")
    if override:
        path = Path(override).expanduser()
        return path if path.exists() else None

    container = Path.home() / "Library" / "Group Containers" / GROUP_CONTAINER
    if not container.is_dir():
        return None

    candidates = sorted(
        container.glob("ThingsData-*/Things Database.thingsdatabase/main.sqlite")
    )
    if not candidates:
        candidates = sorted(container.glob("**/main.sqlite"))
    return candidates[0] if candidates else None


def _load_file() -> dict:
    try:
        with CONFIG_FILE.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def parse_areas(value: str | list[str] | None) -> list[str]:
    """Accept a single area or several, from JSON or a comma-separated string."""
    if not value:
        return []
    if isinstance(value, str):
        value = value.split(",")
    names = [name.strip() for name in value if name and name.strip()]
    return list(dict.fromkeys(names))


@dataclass
class Config:
    db_path: Path | None = field(default_factory=find_database)
    auth_token: str | None = None
    write_scope: str = SCOPE_CONFIRM_OUTSIDE
    agents_areas: list[str] = field(default_factory=lambda: [DEFAULT_AGENTS_AREA])
    agent_id: str = "claude"
    allow_empty_trash: bool = False

    @property
    def agents_area(self) -> str:
        """The area new work streams land in unless another one is named."""
        return self.agents_areas[0] if self.agents_areas else DEFAULT_AGENTS_AREA

    def owns_area(self, area: str | None) -> bool:
        return bool(area) and any(
            area.casefold() == owned.casefold() for owned in self.agents_areas
        )

    @classmethod
    def load(cls) -> Config:
        stored = _load_file()
        scope = os.environ.get("THINGS_WRITE_SCOPE") or stored.get(
            "write_scope", SCOPE_CONFIRM_OUTSIDE
        )
        if scope not in WRITE_SCOPES:
            scope = SCOPE_CONFIRM_OUTSIDE
        # `agents_area` (singular) is still read so older config files and the
        # matching environment variable keep working.
        areas = parse_areas(
            os.environ.get("THINGS_AGENTS_AREAS")
            or os.environ.get("THINGS_AGENTS_AREA")
            or stored.get("agents_areas")
            or stored.get("agents_area")
        ) or [DEFAULT_AGENTS_AREA]
        return cls(
            db_path=find_database(),
            auth_token=os.environ.get("THINGS_AUTH_TOKEN") or stored.get("auth_token"),
            write_scope=scope,
            agents_areas=areas,
            agent_id=os.environ.get("THINGS_AGENT_ID")
            or stored.get("agent_id", "claude"),
            allow_empty_trash=os.environ.get("THINGS_ALLOW_EMPTY_TRASH") == "1"
            or bool(stored.get("allow_empty_trash", False)),
        )

    def save(self, **updates) -> None:
        """Persist selected keys to the config file with 0600 permissions."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        stored = _load_file()
        stored.update(updates)
        CONFIG_FILE.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
        CONFIG_FILE.chmod(0o600)
        for key, value in updates.items():
            if hasattr(self, key):
                setattr(self, key, value)
