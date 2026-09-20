"""HTTP API input validation (real in-process server on the temp port) and state.json persistence."""
import json

import pytest

import server

GHOST = "deadbeef"  # well-formed id that does not exist


# ---------------- HTTP: malformed bodies / headers ----------------

@pytest.mark.parametrize("raw", [b"{not json", b'{"name": "x"', b"\xff\xfe\x00garbage"])
def test_invalid_json_is_400(api, raw):
    code, body, _ = api.post("/api/projects", raw=raw)
    assert code == 400 and body["error"] == "Invalid JSON"


def test_wrong_content_type_is_415(api):
    code, body, _ = api.post("/api/projects", raw=b"{}", headers={"Content-Type": "text/plain"})
    assert code == 415 and "application/json" in body["error"]


def test_oversized_body_is_413(api):
    big = json.dumps({"name": "x" * (server.MAX_BODY + 10)}).encode()
    code, body, _ = api.post("/api/projects", raw=big)
    assert code == 413


@pytest.mark.parametrize("path", ["/api/projects", "/api/agents", "/api/chat"])
@pytest.mark.parametrize("payload", [[], "text", 5, None])
def test_non_object_json_is_rejected_not_500(api, path, payload):
    code, body, _ = api.post(path, raw=json.dumps(payload).encode())
    assert code in (400,) and "error" in body


def test_bad_host_header_is_403(api):
    code, _, _ = api.get("/api/state", headers={"Host": "evil.example:80"})
    assert code == 403


def test_foreign_origin_blocked_on_post_only(api):
    code, _, _ = api.post("/api/projects", {"name": "A", "q": 0, "r": 0}, headers={"Origin": "http://evil.example"})
    assert code == 403
    assert server.projects == {}
    code, _, _ = api.get("/api/state", headers={"Origin": "http://evil.example"})
    assert code == 200


def test_unknown_routes_are_404(api):
    assert api.get("/api/nope")[0] == 404
    assert api.post("/api/nope", {})[0] == 404
    assert api.delete("/api/agents/not-an-id")[0] == 404


# ---------------- HTTP: missing fields / limits ----------------

def test_create_project_validation(api):
    assert api.post("/api/projects", {})[0] == 400                                  # no name
    assert api.post("/api/projects", {"name": "  ", "q": 0, "r": 0})[0] == 400       # blank name
    assert api.post("/api/projects", {"name": "x" * 41, "q": 0, "r": 0})[0] == 400   # name too long
    assert api.post("/api/projects", {"name": "A", "q": 0})[0] == 400                # missing r
    assert api.post("/api/projects", {"name": "A", "q": True, "r": 0})[0] == 400     # bool is not a coordinate
    assert api.post("/api/projects", {"name": "A", "q": 99, "r": 0})[0] == 400       # out of range
    assert api.post("/api/projects", {"name": "A", "q": 0, "r": 0, "description": "d" * 501})[0] == 400
    assert api.post("/api/projects", {"name": "A", "q": 1, "r": 0})[0] == 400        # first must be at 0,0
    assert server.projects == {}
    code, body, _ = api.post("/api/projects", {"name": "A", "q": 0, "r": 0})
    assert code == 201 and body["name"] == "A"
    assert api.post("/api/projects", {"name": "a", "q": 1, "r": 0})[0] == 400        # duplicate name (case-insens.)


def test_create_agent_validation(api, hq):
    pid = hq.project()["id"]
    ok = {"name": "Bob", "role": "r", "backend": "mock", "project": pid}
    assert api.post("/api/agents", {**ok, "name": ""})[0] == 400
    assert api.post("/api/agents", {**ok, "name": "x" * 41})[0] == 400
    assert api.post("/api/agents", {**ok, "role": "r" * 2001})[0] == 400
    assert api.post("/api/agents", {**ok, "backend": "nope"})[0] == 400
    assert api.post("/api/agents", {k: v for k, v in ok.items() if k != "backend"})[0] == 400
    assert api.post("/api/agents", {**ok, "project": GHOST})[0] == 400
    assert api.post("/api/agents", {k: v for k, v in ok.items() if k != "project"})[0] == 400
    assert api.post("/api/agents", {**ok, "backend": "claude", "model": "gpt-9"})[0] == 400
    assert api.post("/api/agents", {**ok, "backend": "gemini", "model": "--evil"})[0] == 400
    assert api.post("/api/agents", {**ok, "backend": "gemini", "model": "a b;c"})[0] == 400
    assert api.post("/api/agents", {**ok, "backend": "opencode", "model": "paid/model"})[0] == 400
    assert server.agents == {}
    code, body, _ = api.post("/api/agents", ok)
    assert code == 201 and body["model"] == "mock"
    assert api.post("/api/agents", {**ok, "name": "BOB"})[0] == 400                  # duplicate name


def test_agent_limit_enforced(api, hq):
    pid = hq.project()["id"]
    for i in range(server.MAX_AGENTS):
        hq.agent(f"a{i}", project=pid)
    code, body, _ = api.post("/api/agents", {"name": "extra", "backend": "mock", "project": pid})
    assert code == 400 and "limit" in body["error"].lower()


def test_task_validation_and_unknown_agent(api, hq):
    a = hq.agent("Worker")
    assert api.post(f"/api/agents/{a['id']}/task", {})[0] == 400
    assert api.post(f"/api/agents/{a['id']}/task", {"task": "   "})[0] == 400
    assert api.post(f"/api/agents/{a['id']}/task", {"task": "x" * (server.MAX_MESSAGE_CHARS + 1)})[0] == 400
    assert api.post(f"/api/agents/{GHOST}/task", {"task": "hi"})[0] == 404
    assert hq.stub.worker_calls() == []


def test_chat_validation(api, hq):
    assert api.post("/api/chat", {})[0] == 400
    assert api.post("/api/chat", {"text": "x" * (server.MAX_MESSAGE_CHARS + 1)})[0] == 400
    code, body, _ = api.post("/api/chat", {"text": "hello"})           # no director yet
    assert code == 400 and "Director" in body["error"]


def test_unknown_ids_on_agent_project_notes_routes(api):
    assert api.delete(f"/api/agents/{GHOST}")[0] == 404
    assert api.delete(f"/api/projects/{GHOST}")[0] == 404
    assert api.get(f"/api/notes/{GHOST}")[0] == 404
    assert api.post(f"/api/agents/{GHOST}/director")[0] == 404
    assert api.post(f"/api/agents/{GHOST}/move", {"platform": "x"})[0] in (404, 400)


def test_move_bad_bodies_do_not_500(api, hq):
    a = hq.agent("Worker")
    for raw in (b"[1]", b'"str"', b"{}", b'{"platform": "nonexistent"}'):
        code, _, _ = api.post(f"/api/agents/{a['id']}/move", raw=raw)
        assert code < 500, f"body {raw!r} gave {code}"


def test_delete_project_with_agents_is_409(api, hq):
    a = hq.agent("Worker")
    assert api.delete(f"/api/projects/{a['project']}")[0] == 409
    assert api.delete(f"/api/agents/{a['id']}")[0] == 200
    assert api.delete(f"/api/projects/{a['project']}")[0] == 200


# ---------------- persistence ----------------

def test_save_load_roundtrip(hq):
    p = hq.project("Main")
    a = hq.agent("Alice", project=p["id"], director=True, role="lead")
    hq.agent("Bob", project=p["id"])
    server.add_chat("user", "hello")
    server.add_chat("director", "hi there")
    server.settings["autoReview"] = False
    with server.lock:
        server.save()
    before = json.loads(json.dumps({"projects": server.projects, "agents": server.agents,
                                    "chat": server.chat, "settings": server.settings}))
    hq.reload_from_disk()
    after = json.loads(json.dumps({"projects": server.projects, "agents": server.agents,
                                   "chat": server.chat, "settings": server.settings}))
    assert after == before
    assert server.current_director()["id"] == a["id"]
    assert not server.STATE_FILE.with_suffix(".tmp").exists()


def test_working_agent_is_marked_failed_after_restart(hq):
    a = hq.agent("Worker")
    a["status"] = "working"
    with server.lock:
        server.save()
    hq.reload_from_disk()
    b = server.agents[a["id"]]
    assert b["status"] == "failed" and "restarted" in b["error"]


def test_chat_history_trimmed_on_load(hq):
    hq.project()
    server.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    msgs = [{"role": "user", "text": str(i), "ts": i} for i in range(server.MAX_CHAT + 50)]
    server.STATE_FILE.write_text(json.dumps({"projects": list(server.projects.values()), "agents": [],
                                             "chat": msgs, "settings": {}}), encoding="utf-8")
    hq.reload_from_disk()
    assert len(server.chat) == server.MAX_CHAT and server.chat[-1]["text"] == str(server.MAX_CHAT + 49)


def test_missing_state_file_starts_empty(hq):
    assert not server.STATE_FILE.exists()
    hq.reload_from_disk()
    assert server.projects == {} and server.agents == {} and server.chat == []
    assert server.settings["autoReview"] is True


@pytest.mark.parametrize("content", ["{not json", "", '{"projects": [{"id": "aa', "\x00\x00\x00"])
def test_corrupt_state_file_is_handled(hq, content, capsys):
    server.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    server.STATE_FILE.write_text(content, encoding="utf-8")
    hq.reload_from_disk()                       # must not raise
    assert server.projects == {} and server.agents == {}
    assert "could not read saved state" in capsys.readouterr().err


def test_valid_json_of_wrong_shape_is_handled(hq):
    """A syntactically valid but non-object state file (e.g. a list) should not crash startup."""
    server.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    server.STATE_FILE.write_text("[]", encoding="utf-8")
    hq.reload_from_disk()
    assert server.projects == {} and server.agents == {}


def test_agent_with_unknown_project_is_reattached_on_load(hq):
    p = hq.project("Main")
    server.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    orphan = {"id": "0badf00d", "name": "Orphan", "project": GHOST, "backend": "mock", "model": "mock",
              "status": "idle"}
    server.STATE_FILE.write_text(json.dumps({"projects": [p], "agents": [orphan]}), encoding="utf-8")
    hq.reload_from_disk()
    a = server.agents["0badf00d"]
    assert a["project"] == p["id"] and a["isDirector"] is False and a["notesFile"].endswith("0badf00d.md")


def test_legacy_agents_json_migrates_into_main_platform(hq):
    server.LEGACY_FILE.parent.mkdir(parents=True, exist_ok=True)
    server.LEGACY_FILE.write_text(json.dumps([{"id": "0badf00d", "name": "Old", "backend": "mock",
                                               "model": "mock", "status": "idle"}]), encoding="utf-8")
    hq.reload_from_disk()
    assert [p["name"] for p in server.projects.values()] == ["Main"]
    assert server.agents["0badf00d"]["project"] in server.projects
    server.LEGACY_FILE.unlink()


def test_long_chat_message_accepted_and_reaches_director_uncut(api, hq):
    hq.agent("Boss", director=True)
    text = ("wort " * 6400).strip()                          # ~32000 chars, > old 4000 limit and > old 700 director clip
    assert 4000 < len(text) <= server.MAX_MESSAGE_CHARS
    code, _, _ = api.post("/api/chat", {"text": text})
    assert code == 202
    hq.wait_idle()
    assert hq.chat_text("user")[0] == text                   # stored uncut
    assert text in hq.stub.director_calls()[0][1]            # forwarded to the Director uncut


def test_max_size_multibyte_message_fits_body_limit(api, hq):
    hq.agent("Boss", director=True)
    text = "€\n\"" * (server.MAX_MESSAGE_CHARS // 3)   # 3-byte + escaped chars: worst-case body size
    code, body, _ = api.post("/api/chat", {"text": text})
    assert code == 202, body
