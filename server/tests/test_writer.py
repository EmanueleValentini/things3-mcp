import json
import urllib.parse

import pytest

from things3_mcp import writer as writer_module
from things3_mcp.writer import AuthTokenMissing, WriteError, Writer, count_items


class FakeResult:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return FakeResult()

    monkeypatch.setattr(writer_module.subprocess, "run", fake_run)
    return calls


def parse(url):
    query = urllib.parse.urlparse(url).query
    params = dict(urllib.parse.parse_qsl(query))
    return params, json.loads(params["data"])


def test_count_items_includes_nested_records():
    payload = [
        {
            "type": "project",
            "attributes": {
                "title": "p",
                "items": [
                    {"type": "heading", "attributes": {"title": "h"}},
                    {
                        "type": "to-do",
                        "attributes": {
                            "title": "t",
                            "checklist-items": [
                                {"type": "checklist-item", "attributes": {"title": "c"}}
                            ],
                        },
                    },
                ],
            },
        }
    ]
    assert count_items(payload) == 4


def test_send_builds_a_json_url(config, db, sent):
    Writer(config, db).send(
        [{"type": "to-do", "attributes": {"title": "ciao è"}}], needs_auth=False
    )
    url = sent[0][-1]
    assert sent[0][:2] == ["open", "-g"]
    assert url.startswith("things:///json?")
    params, data = parse(url)
    assert data[0]["attributes"]["title"] == "ciao è"
    assert params["auth-token"] == "test-token"


def test_update_without_token_explains_where_to_get_one(config, db, sent):
    config.auth_token = None
    with pytest.raises(AuthTokenMissing, match="Settings"):
        Writer(config, db).send([{"type": "to-do"}], needs_auth=True)
    assert sent == []


def test_create_without_token_still_works(config, db, sent):
    config.auth_token = None
    Writer(config, db).send([{"type": "to-do"}], needs_auth=False)
    params, _ = parse(sent[0][-1])
    assert "auth-token" not in params


def test_failed_open_is_surfaced(config, db, monkeypatch):
    monkeypatch.setattr(
        writer_module.subprocess,
        "run",
        lambda *a, **k: FakeResult(returncode=1, stderr="boom"),
    )
    with pytest.raises(WriteError, match="boom"):
        Writer(config, db).send([{"type": "to-do"}], needs_auth=False)


def test_create_resolves_the_new_uuid(config, db, sent, monkeypatch):
    monkeypatch.setattr(writer_module, "CONFIRM_TIMEOUT", 0.2)
    instance = Writer(config, db)
    # "Ship it" already exists in the fixture with an old creationDate, so a
    # create that finds nothing newer must fail rather than return the old row.
    with pytest.raises(WriteError, match="no item titled"):
        instance.create([{"type": "to-do", "attributes": {"title": "Ship it"}}], "Ship it")


def test_update_requires_an_existing_item(config, db, sent):
    with pytest.raises(LookupError):
        Writer(config, db).update("nope", "todo", {"title": "x"})


def test_rate_limit_waits_when_the_window_is_full(config, db, sent, monkeypatch):
    slept = []
    monkeypatch.setattr(writer_module.time, "sleep", lambda s: slept.append(s))
    instance = Writer(config, db)
    payload = [{"type": "to-do", "attributes": {"title": f"t{i}"}} for i in range(150)]
    instance.send(payload, needs_auth=False)
    instance.send(payload, needs_auth=False)
    assert slept, "second batch should have been throttled"
