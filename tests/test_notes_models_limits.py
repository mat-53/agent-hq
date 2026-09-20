"""Agent notes files, model-list endpoints (no real CLI / network) and the MAX_PROJECTS limit."""
import types

import pytest

import server


# ---------------- agent notes ----------------

def _run_task(hq, agent, task="do the thing"):
    with server.lock:
        server.begin_task(agent, task)
    hq.wait_status(agent, "done")


def _notes_contain(hq, agent, needle):
    path = server.NOTES_DIR / agent["notesFile"]
    hq.wait_until(lambda: path.exists() and needle in path.read_text(encoding="utf-8"), what=f"notes containing {needle!r}")
    return path.read_text(encoding="utf-8")


def test_notes_file_written_and_read_back(hq, api):
    a = hq.agent("Ann", role="tester")
    hq.stub.worker_reply = "long output\nSUMMARY:\nAnn found the answer 42"
    _run_task(hq, a)
    text = _notes_contain(hq, a, "answer 42")
    assert "# Ann" in text and "Role: tester" in text and "## Latest summary" in text
    code, body, _ = api.get(f"/api/notes/{a['id']}")
    assert code == 200 and "Ann found the answer 42" in body["text"]


def test_notes_earlier_work_kept(hq):
    a = hq.agent("Ann")
    hq.stub.worker_reply = "x\nSUMMARY:\nfirst result"
    _run_task(hq, a, "task one")
    hq.stub.worker_reply = "y\nSUMMARY:\nsecond result"
    _run_task(hq, a, "task two")
    text = _notes_contain(hq, a, "second result")
    assert "## Earlier work" in text and "first result" in text


def test_notes_for_fresh_agent_and_unknown_agent(hq, api):
    a = hq.agent("Fresh")
    code, body, _ = api.get(f"/api/notes/{a['id']}")
    assert code == 200 and "text" in body
    assert api.get("/api/notes/deadbeef")[0] == 404


def test_notes_placeholder_when_file_missing(hq, api):
    a = hq.agent("Ghost")
    (server.NOTES_DIR / a["notesFile"]).unlink(missing_ok=True)
    code, body, _ = api.get(f"/api/notes/{a['id']}")
    assert code == 200 and body["text"] == "(no notes yet)"


def test_include_notes_from_passes_teammate_summary(hq):
    hq.stub.worker_reply = "out\nSUMMARY:\nBob says use port 9999"
    bob = hq.agent("Bob")
    _run_task(hq, bob)
    assert bob["summary"] == "Bob says use port 9999"
    hq.agent("Cara")
    hq.stub.calls.clear()
    hq.act({"type": "assign", "agent": "Cara", "task": "build it", "include_notes_from": ["Bob"]})
    hq.wait_idle()
    prompts = [p for _, p in hq.stub.worker_calls("Cara")]
    assert prompts, "Cara never ran"
    assert "Information from teammates" in prompts[0]
    assert "### Bob" in prompts[0] and "Bob says use port 9999" in prompts[0]


def test_include_notes_from_ignores_unknown_self_and_bad_types(hq):
    hq.stub.worker_reply = "out\nSUMMARY:\nsecret-summary"
    bob = hq.agent("Bob")
    _run_task(hq, bob)
    cara = hq.agent("Cara")
    with server.lock:
        assert server.context_from(["Nobody"], cara["id"]) == ""
        assert server.context_from(["Cara"], cara["id"]) == ""        # own name (no summary anyway)
        assert server.context_from("Bob", cara["id"]) == ""           # non-list ignored, no crash
        assert server.context_from([], cara["id"]) == ""
        assert server.context_from(["Bob"], bob["id"]) == ""          # never include an agent's own notes
        assert "secret-summary" in server.context_from(["bob"], cara["id"])   # case-insensitive


# ---------------- model list endpoints ----------------

def test_claude_models_static(api):
    code, body, _ = api.get("/api/models/claude")
    assert code == 200 and body == {"models": list(server.CLAUDE_MODELS)}


def test_gemini_models_without_key_is_clean_json(api):
    code, body, _ = api.get("/api/models/gemini")
    assert code == 200 and body["models"] == [] and "GEMINI_API_KEY" in body["error"]


def test_gemini_models_filtered_and_sorted(api, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    gm = ["generateContent"]
    fake = {"models": [
        {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": gm},
        {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": gm},
        {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": gm},
        {"name": "models/gemini-image-x", "supportedGenerationMethods": gm},
        {"name": "models/gemini-embed", "supportedGenerationMethods": ["embedContent"]},
        {"name": "models/other-model", "supportedGenerationMethods": gm}]}
    monkeypatch.setattr(server, "http_json", lambda url, headers, body=None: fake)
    code, body, _ = api.get("/api/models/gemini")
    assert code == 200
    assert body["models"] == ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"]


def test_openrouter_models_free_only_and_cached(api, monkeypatch):
    calls = []
    fake = {"data": [{"id": "a/b:free"}, {"id": "c/d", "pricing": {"prompt": "0", "completion": "0"}},
                     {"id": "e/paid", "pricing": {"prompt": "0.1", "completion": "0.2"}}]}
    monkeypatch.setattr(server, "http_json", lambda url, headers, body=None: calls.append(url) or fake)
    code, body, _ = api.get("/api/models/openrouter")
    assert code == 200 and body["models"] == ["a/b:free", "c/d"]
    api.get("/api/models/openrouter")
    assert len(calls) == 1                                  # second answer came from MODEL_CACHE


def test_openrouter_network_failure_is_200_with_error(api, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(server, "http_json", boom)
    code, body, _ = api.get("/api/models/openrouter")
    assert code == 200 and body["models"] == [] and "network down" in body["error"]


@pytest.mark.parametrize("route", ["opencode", "opencode-readonly"])
def test_opencode_models_without_cli(api, monkeypatch, route):
    monkeypatch.setattr(server, "find_opencode", lambda: None)
    code, body, _ = api.get(f"/api/models/{route}")
    assert code == 200 and body["models"] == [] and "not found" in body["error"].lower()


@pytest.mark.parametrize("route", ["opencode", "opencode-readonly"])
def test_opencode_models_parsed_from_mock_cli(api, monkeypatch, route):
    monkeypatch.setattr(server, "find_opencode", lambda: "fake-opencode")
    out = "opencode/big-pickle\nopencode/foo-free\nopencode/paid-model\nother/x-free\n"
    monkeypatch.setattr(server.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout=out, stderr="", returncode=0))
    code, body, _ = api.get(f"/api/models/{route}")
    assert code == 200 and body["models"] == ["opencode/big-pickle", "opencode/foo-free"]


def test_unknown_model_backend_is_404(api):
    assert api.get("/api/models/nope")[0] == 404


# ---------------- MAX_PROJECTS ----------------

def _create_via_api(api, name):
    with server.lock:
        slot = server.auto_slot()
    assert slot is not None
    return api.post("/api/projects", {"name": name, "description": "", "q": slot[0], "r": slot[1]})


def test_max_projects_rejected_cleanly_via_api(api):
    for i in range(server.MAX_PROJECTS):
        code, body, _ = _create_via_api(api, f"P{i}")
        assert code in (200, 201), (i, code, body)
    assert len(server.projects) == server.MAX_PROJECTS
    before = dict(server.projects)
    # a valid, free, adjacent spot must still be refused because of the limit
    taken = {(p["q"], p["r"]) for p in server.projects.values()}
    spot = next((q + dq, r + dr) for (q, r) in taken for dq, dr in server.NEIGHBORS
                if (q + dq, r + dr) not in taken and abs(q + dq) <= 8 and abs(r + dr) <= 8)
    code, body, _ = api.post("/api/projects", {"name": "OneTooMany", "description": "", "q": spot[0], "r": spot[1]})
    assert code == 400 and "limit" in body["error"].lower() and str(server.MAX_PROJECTS) in body["error"]
    assert server.projects == before
    assert api.get("/api/state")[0] == 200                  # server still healthy


def test_max_projects_direct_call_raises_apierror(hq):
    for i in range(server.MAX_PROJECTS):
        hq.project(f"P{i}")
    with pytest.raises(server.ApiError):
        hq.project("Extra")
    assert len(server.projects) == server.MAX_PROJECTS


def test_deleting_a_project_frees_a_slot(api):
    ids = [_create_via_api(api, f"P{i}")[1]["id"] for i in range(server.MAX_PROJECTS)]
    assert len(server.projects) == server.MAX_PROJECTS
    assert api.delete(f"/api/projects/{ids[-1]}")[0] == 200
    code, body, _ = _create_via_api(api, "Again")
    assert code in (200, 201), body
