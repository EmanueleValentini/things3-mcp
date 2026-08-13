#!/usr/bin/env bash
# Register the things3 MCP server with Codex and install the skills.
#
# Idempotent: re-running replaces the managed block rather than appending a
# second one. The existing config.toml is backed up before any change.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
CONFIG="$CODEX_HOME/config.toml"
SKILLS_DIR="$CODEX_HOME/skills"
BEGIN_MARKER="# >>> things3-mcp >>>"
END_MARKER="# <<< things3-mcp <<<"

command -v uv >/dev/null || {
  echo "uv is not installed. See https://docs.astral.sh/uv/getting-started/" >&2
  exit 1
}

mkdir -p "$CODEX_HOME" "$SKILLS_DIR"

# -- config.toml -------------------------------------------------------------

if [ -f "$CONFIG" ]; then
  BACKUP="$CONFIG.bak.$(date +%Y%m%d%H%M%S)"
  cp "$CONFIG" "$BACKUP"
  echo "Backed up $CONFIG -> $BACKUP"
  # Drop a previously installed block, if any.
  awk -v b="$BEGIN_MARKER" -v e="$END_MARKER" '
    $0 == b { skip = 1 }
    !skip   { print }
    $0 == e { skip = 0 }
  ' "$BACKUP" > "$CONFIG"
else
  touch "$CONFIG"
fi

cat >> "$CONFIG" <<EOF
$BEGIN_MARKER
[mcp_servers.things3]
command = "uv"
args = ["run", "--directory", "$REPO_ROOT/server", "things3-mcp"]
startup_timeout_sec = 60

[mcp_servers.things3.env]
THINGS_AGENT_ID = "codex"
$END_MARKER
EOF

echo "Registered [mcp_servers.things3] in $CONFIG"

# -- skills ------------------------------------------------------------------

for skill in "$REPO_ROOT"/skills/*/; do
  name="$(basename "$skill")"
  rm -rf "${SKILLS_DIR:?}/$name"
  cp -R "$skill" "$SKILLS_DIR/$name"
  echo "Installed skill $name -> $SKILLS_DIR/$name"
done

# -- first run ---------------------------------------------------------------

echo
echo "Warming up the server (this resolves Python dependencies)..."
(cd "$REPO_ROOT/server" && uv sync --quiet)

cat <<'EOF'

Done. Restart Codex, then try: "cosa ho oggi in Things?"

Still to do by hand, once:
  * store the auth token so existing items can be modified:
      Things > Settings > General > Enable Things URL scheme > Manage
      then ask Codex to run configure(auth_token="...")
  * create an area named "Agents" in Things if you want the agent workspace
    (automation cannot create areas)
EOF
