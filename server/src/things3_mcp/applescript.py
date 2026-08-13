"""AppleScript bridge for the few operations the URL scheme cannot do.

Only trashing, emptying the trash, and reading the current selection live here.
Everything else goes through the URL scheme, which is a public, stable API.
"""

from __future__ import annotations

import subprocess

from .config import THINGS_APP

APP = "Things3"

# List *names* are localised (the trash is "Cestino" in Italian), so every
# reference goes through the stable internal ids instead.
TRASH_LIST_ID = "TMTrashListSource"


class AppleScriptError(RuntimeError):
    pass


def run(script: str, timeout: float = 30) -> str:
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        message = result.stderr.strip()
        if "-1743" in message or "not allowed" in message.lower():
            raise AppleScriptError(
                "macOS denied automation access to Things 3. Grant it in System "
                "Settings > Privacy & Security > Automation, then retry. "
                "Run /things3:setup to trigger the prompt."
            )
        raise AppleScriptError(message or f"osascript exited {result.returncode}")
    return result.stdout.strip()


def is_installed() -> bool:
    return THINGS_APP.exists()


def is_running() -> bool:
    script = (
        'tell application "System Events" to return (exists (processes where name is '
        f'"{APP}"))'
    )
    return run(script) == "true"


def version() -> str:
    return run(f'tell application "{APP}" to return version')


def create_tag(name: str) -> str:
    """Create a tag and return its id.

    The URL scheme cannot do this — it ignores tags that do not exist — and the
    dictionary marks the application's tag element read-only, but `make new tag`
    works anyway. Verified against Things 3.22.
    """
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    result = run(
        f'tell application "{APP}" to make new tag with properties {{name:"{escaped}"}}'
    )
    return result.replace("tag id ", "").strip()


def trash(uuid: str) -> None:
    """Move a to-do or project to the Things trash. Recoverable in-app."""
    run(
        f'tell application "{APP}"\n'
        f'  if exists to do id "{uuid}" then\n'
        f'    move to do id "{uuid}" to list id "{TRASH_LIST_ID}"\n'
        f'  else if exists project id "{uuid}" then\n'
        f'    move project id "{uuid}" to list id "{TRASH_LIST_ID}"\n'
        f"  else\n"
        f'    error "no item with id {uuid}"\n'
        f"  end if\n"
        f"end tell"
    )


def empty_trash() -> None:
    """Permanently delete everything in the trash. Irreversible."""
    run(f'tell application "{APP}" to empty trash')


def selected_todos() -> list[dict[str, str]]:
    """Titles and ids of what the user currently has selected in Things."""
    raw = run(
        f'tell application "{APP}"\n'
        f"  set output to {{}}\n"
        f"  repeat with t in selected to dos\n"
        f'    set end of output to (id of t) & "\t" & (name of t)\n'
        f"  end repeat\n"
        f"  set AppleScript's text item delimiters to linefeed\n"
        f"  return output as text\n"
        f"end tell"
    )
    items = []
    for line in raw.splitlines():
        if "\t" in line:
            uuid, title = line.split("\t", 1)
            items.append({"uuid": uuid, "title": title})
    return items
