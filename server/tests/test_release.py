"""Guards on the things a release gets wrong.

The version lives in two files and the changelog in a third. Nothing at runtime
reads all three, so drift is invisible until someone installs the plugin and
gets a version number that does not match what they were given.
"""

import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
PYPROJECT = ROOT / "server" / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def plugin_version() -> str:
    return json.loads(PLUGIN.read_text())["version"]


def package_version() -> str:
    return tomllib.loads(PYPROJECT.read_text())["project"]["version"]


def released_versions() -> list[str]:
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(), re.M)


def test_the_two_version_numbers_agree():
    assert plugin_version() == package_version()


def test_the_version_is_semver():
    assert SEMVER.match(plugin_version()), plugin_version()


def test_the_current_version_has_a_changelog_entry():
    assert plugin_version() in released_versions()


def test_the_changelog_leads_with_the_current_version():
    assert released_versions()[0] == plugin_version()


def test_the_changelog_keeps_an_unreleased_section():
    """Where the next PR writes its entry."""
    assert "## [Unreleased]" in CHANGELOG.read_text()


def test_released_versions_descend():
    versions = [tuple(map(int, v.split("."))) for v in released_versions()]
    assert versions == sorted(versions, reverse=True)


def test_every_released_version_has_a_link_target():
    text = CHANGELOG.read_text()
    for version in released_versions():
        assert f"[{version}]: https://" in text, f"no link for {version}"


@pytest.mark.parametrize("path", [PLUGIN, MARKETPLACE])
def test_the_plugin_manifests_stay_parseable(path):
    """A syntax error here breaks installation with no useful message."""
    data = json.loads(path.read_text())
    assert data["name"] == "things3"


def test_the_marketplace_points_at_this_repo_root():
    entry = json.loads(MARKETPLACE.read_text())["plugins"][0]
    assert entry["source"] == "./"
    assert entry["name"] == json.loads(PLUGIN.read_text())["name"]


def test_health_check_survives_a_machine_without_things(tmp_path, monkeypatch):
    """The plugin also installs on Cowork, which may run it in a Linux sandbox.

    There is no Things there, and no database. health_check is what has to say
    so — crashing is the one thing it must not do.
    """
    import asyncio

    monkeypatch.setenv("THINGS_DB_PATH", str(tmp_path / "absent.sqlite"))
    monkeypatch.setenv("THINGS3_MCP_CONFIG_DIR", str(tmp_path / "config"))

    from things3_mcp.server import build_server

    report = asyncio.run(build_server().call_tool("health_check", {}))
    data = report[1] if isinstance(report, tuple) else report
    text = str(data)
    assert "not found" in text
    assert "'ok': False" in text or '"ok": false' in text
