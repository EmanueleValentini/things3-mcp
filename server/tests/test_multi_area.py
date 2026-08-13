"""Several agent areas, one per domain.

Agents may create and adopt areas themselves, which is only safe because an
area they create is empty. Adopting one that already holds the user's projects
would quietly move that work under rules that skip confirmation, so it is
gated.
"""

import pytest

from things3_mcp import agents
from things3_mcp.config import Config, parse_areas
from things3_mcp.permissions import PermissionDenied
from things3_mcp.services import Services

from conftest import FakeServer


@pytest.fixture
def created_areas(monkeypatch):
    names = []
    monkeypatch.setattr(agents.applescript, "create_area", lambda name: names.append(name))
    return names


@pytest.fixture
def agent_tools(services, created_areas):
    server = FakeServer()
    agents.register(server, services)
    return server.tools


@pytest.fixture(autouse=True)
def no_config_writes(monkeypatch):
    """Keep the tests off the real ~/.config file."""
    monkeypatch.setattr(
        Config, "save", lambda self, **updates: [setattr(self, k, v) for k, v in updates.items()]
    )


def test_parse_areas_accepts_a_string_or_a_list():
    assert parse_areas("Agents") == ["Agents"]
    assert parse_areas("Dev, Personal") == ["Dev", "Personal"]
    assert parse_areas(["Dev", "Dev", " Personal "]) == ["Dev", "Personal"]
    assert parse_areas(None) == []


def test_the_first_area_is_where_new_streams_go():
    config = Config(agents_areas=["Dev", "Personal"])
    assert config.agents_area == "Dev"


def test_ownership_ignores_case():
    config = Config(agents_areas=["Agents"])
    assert config.owns_area("agents")
    assert not config.owns_area("Casa")
    assert not config.owns_area(None)


def test_adding_a_new_area_creates_and_registers_it(agent_tools, config, created_areas):
    result = agent_tools["agent_workspace_init"](area="Agents — Dev")
    assert created_areas == ["Agents — Dev"]
    assert config.agents_areas == ["Agents", "Agents — Dev"]
    assert [entry["area"] for entry in result["areas"]] == ["Agents", "Agents — Dev"]


def test_adopting_an_area_with_the_users_projects_asks_first(
    agent_tools, config, created_areas
):
    result = agent_tools["agent_workspace_init"](area="Casa")
    assert result["confirmation_required"] is True
    assert result["preview"]["existing_projects"] == ["Trasloco"]
    assert config.agents_areas == ["Agents"]  # not adopted
    assert created_areas == []  # and not recreated


def test_adopting_it_works_once_confirmed(agent_tools, config):
    agent_tools["agent_workspace_init"](area="Casa", confirmed=True)
    assert config.agents_areas == ["Agents", "Casa"]


def test_re_adding_a_known_area_is_a_no_op(agent_tools, config, created_areas):
    agent_tools["agent_workspace_init"](area="Agents")
    assert config.agents_areas == ["Agents"]
    assert created_areas == []


def test_a_stream_cannot_be_created_in_an_unowned_area(agent_tools):
    with pytest.raises(PermissionDenied, match="not an agent area"):
        agent_tools["agent_create_stream"](title="x", area="Casa")


def test_items_in_any_owned_area_are_managed(services, config, db):
    config.agents_areas = ["Agents", "Casa"]
    assert services.guard.in_agents_area(db.get("todo-personal"))


def test_status_and_next_task_span_every_area(agent_tools, config, db_path):
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO TMTask (uuid, title, type, status, trashed, start, \"index\","
        " creationDate, userModificationDate, area)"
        " VALUES ('proj-two', 'Second stream', 1, 0, 0, 1, 0, 1786600000.0,"
        " 1786600000.0, 'area-personal')"
    )
    conn.execute(
        "INSERT INTO TMTask (uuid, title, type, status, trashed, start, \"index\","
        " creationDate, userModificationDate, project)"
        " VALUES ('todo-two', 'Task altrove', 0, 0, 0, 1, 0, 1786600000.0,"
        " 1786600000.0, 'proj-two')"
    )
    conn.commit()
    conn.close()

    config.agents_areas = ["Agents", "Casa"]
    status = agent_tools["agent_status"]()
    assert {s["title"] for s in status["streams"]} == {
        "Refactor auth",
        "Trasloco",
        "Second stream",
    }

    only_casa = agent_tools["agent_status"](area="Casa")
    assert {s["title"] for s in only_casa["streams"]} == {"Trasloco", "Second stream"}

    # Agents comes first in the list, so its unclaimed task wins.
    assert agent_tools["agent_next_task"]()["title"] == "Write the tests"
    assert agent_tools["agent_next_task"](area="Casa")["title"] == "Chiamare l'idraulico"


def test_status_rejects_an_area_agents_do_not_own(agent_tools):
    with pytest.raises(PermissionDenied, match="not an agent area"):
        agent_tools["agent_status"](area="Casa")
