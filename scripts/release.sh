#!/usr/bin/env bash
# Cut a release: bump the version everywhere, close the changelog section, tag.
#
#   ./scripts/release.sh 0.2.0
#
# Pushing the tag is left to you, and is what triggers the GitHub release.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VERSION="${1:-}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 <major.minor.patch>" >&2
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is dirty. Commit or stash first." >&2
  exit 1
fi

if git rev-parse "v$VERSION" >/dev/null 2>&1; then
  echo "Tag v$VERSION already exists." >&2
  exit 1
fi

TODAY=$(date +%Y-%m-%d)
REPO="EmanueleValentini/things3-mcp"
PREVIOUS=$(python3 -c "import json;print(json.load(open('.claude-plugin/plugin.json'))['version'])")

python3 - "$VERSION" "$TODAY" "$REPO" "$PREVIOUS" <<'PY'
import json, pathlib, re, sys

version, today, repo, previous = sys.argv[1:5]

plugin = pathlib.Path(".claude-plugin/plugin.json")
data = json.loads(plugin.read_text())
data["version"] = version
plugin.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

pyproject = pathlib.Path("server/pyproject.toml")
pyproject.write_text(
    re.sub(r'^version = "[^"]+"', f'version = "{version}"', pyproject.read_text(), count=1, flags=re.M)
)

changelog = pathlib.Path("CHANGELOG.md")
text = changelog.read_text()
if f"## [{version}]" in text:
    sys.exit(f"CHANGELOG.md already has a section for {version}")

body = text.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0].strip()
if not body:
    sys.exit("Nothing under '## [Unreleased]' — write the changelog entry first.")

text = text.replace(
    "## [Unreleased]\n" + text.split("## [Unreleased]\n", 1)[1].split("\n## [", 1)[0],
    f"## [Unreleased]\n\n## [{version}] — {today}\n\n{body}\n",
    1,
)
text = text.replace(
    f"[Unreleased]: https://github.com/{repo}/compare/v{previous}...HEAD",
    f"[Unreleased]: https://github.com/{repo}/compare/v{version}...HEAD\n"
    f"[{version}]: https://github.com/{repo}/releases/tag/v{version}",
    1,
)
changelog.write_text(text)
print(f"Bumped {previous} -> {version}")
PY

uv run --directory server pytest -q

git add -A
git commit -m "release: v$VERSION"
git tag -a "v$VERSION" -m "v$VERSION"

cat <<EOF

Tagged v$VERSION. Nothing has left this machine yet.

  git push origin main --follow-tags

That publishes the GitHub release from the changelog section. Users pick it up
with /plugin update things3@things3 — an installed plugin is a frozen clone and
does not follow the repo on its own.
EOF
