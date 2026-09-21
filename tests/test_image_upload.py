"""Image upload backend: POST /api/upload_image, GET /uploads/<name>, chat/task image wiring."""
import base64
import http.client
import json
import uuid

import pytest

import server

# minimal valid PNG (1x1 transparent)
PNG_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode()


@pytest.fixture(autouse=True)
def upload_dir(monkeypatch, tmp_path):
    d = tmp_path / "uploads"
    monkeypatch.setattr(server, "UPLOAD_DIR", d)
    d.mkdir(parents=True, exist_ok=True)
    return d


def abs_line(d, rel):
    return f"[Bild angehaengt: {(d / rel.split('/', 1)[1]).resolve()}]"


# ---------------- upload endpoint ----------------

def test_upload_valid_png_returns_path_and_saves_file(api, upload_dir):
    code, body, _ = api.post("/api/upload_image", {"filename": "whatever.png", "data_url": PNG_DATA_URL})
    assert code == 201, body
    assert body["ok"] is True
    assert body["url"] == "/" + body["path"]
    assert body["path"].startswith("uploads/") and body["path"].endswith(".png")
    name = body["path"].split("/", 1)[1]
    assert uuid.UUID(name[:-4]).hex == name[:-4]                # server-side uuid, client name ignored
    assert (upload_dir / name).read_bytes() == PNG_BYTES


def test_upload_two_files_get_different_uuid_names(api, upload_dir):
    _, a, _ = api.post("/api/upload_image", {"filename": "same.png", "data_url": PNG_DATA_URL})
    _, b, _ = api.post("/api/upload_image", {"filename": "same.png", "data_url": PNG_DATA_URL})
    assert a["path"] != b["path"]
    assert (upload_dir / a["path"].split("/", 1)[1]).is_file()
    assert (upload_dir / b["path"].split("/", 1)[1]).is_file()


@pytest.mark.parametrize("data_url", [
    "data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode(),
    "data:text/plain;base64," + base64.b64encode(b"hi").decode(),
    "data:image/png;base64not-data",
    "not a data url at all",
])
def test_upload_wrong_type_is_415_and_writes_nothing(api, upload_dir, data_url):
    code, body, _ = api.post("/api/upload_image", {"filename": "x.png", "data_url": data_url})
    assert code == 415 and "error" in body
    assert not upload_dir.exists() or not any(upload_dir.iterdir())


def test_upload_bad_base64_is_400(api):
    code, body, _ = api.post("/api/upload_image", {"filename": "x.png", "data_url": "data:image/png;base64,%%%"})
    assert code == 400 and "base64" in body["error"]
    code, _, _ = api.post("/api/upload_image", {"filename": "x.png", "data_url": "data:image/png;base64,"})
    assert code == 400


def test_upload_too_large_is_413(api, monkeypatch):
    monkeypatch.setattr(server, "MAX_UPLOAD_BYTES", 10)
    code, body, _ = api.post("/api/upload_image", {"filename": "x.png", "data_url": PNG_DATA_URL})
    assert code == 413 and "too large" in body["error"]


def test_upload_over_real_10mb_limit_is_413(api):
    raw = b"0" * (server.MAX_UPLOAD_BYTES + 1)
    data_url = "data:image/png;base64," + base64.b64encode(raw).decode()
    assert len(data_url) < server.MAX_UPLOAD_BODY
    code, body, _ = api.post("/api/upload_image", {"filename": "big.png", "data_url": data_url})
    assert code == 413 and "too large" in body["error"]


def test_upload_non_object_body_is_rejected(api):
    code, body, _ = api.post("/api/upload_image", raw=json.dumps(["x"]).encode())
    assert code == 400 and "error" in body


# ---------------- serving uploads ----------------

def test_get_upload_serves_exact_bytes_with_content_type(api, upload_dir):
    _, body, _ = api.post("/api/upload_image", {"filename": "x.png", "data_url": PNG_DATA_URL})
    name = body["path"].split("/", 1)[1]
    conn = http.client.HTTPConnection("127.0.0.1", server.PORT, timeout=10)
    conn.request("GET", f"/uploads/{name}")
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    assert resp.status == 200 and resp.getheader("Content-Type") == "image/png"
    assert data == PNG_BYTES


def test_get_upload_blocks_traversal_and_unknown(api, upload_dir):
    (upload_dir / "secret.txt").write_bytes(b"no")
    assert api.get("/uploads/..")[0] == 403
    assert api.get("/uploads/nope.png")[0] == 404
    assert api.get("/uploads/sub%2Fsecret.txt")[0] == 404
    assert api.get("/uploads/..%5Cstate.json")[0] == 404
    assert api.get("/uploads/secret.txt")[0] == 404          # unknown content type for the uploads route
    assert api.get("/uploads/")[0] == 404


# ---------------- images on chat messages ----------------

def test_chat_message_with_image_persisted_and_prompted(api, hq, upload_dir):
    hq.agent("Boss", director=True)
    _, up, _ = api.post("/api/upload_image", {"filename": "x.png", "data_url": PNG_DATA_URL})
    rel = up["path"]
    code, body, _ = api.post("/api/chat", {"text": "look at this screenshot", "images": [rel]})
    assert code == 202, body
    hq.wait_idle()
    msg = [m for m in server.chat if m["role"] == "user"][-1]
    assert msg["images"] == [rel]
    with server.lock:
        server.save()
    hq.reload_from_disk()
    msg = [m for m in server.chat if m["role"] == "user"][-1]
    assert msg["images"] == [rel]
    prompt = hq.stub.director_calls()[0][1]
    assert abs_line(upload_dir, rel) in prompt
    # snapshot (what the browser renders) carries the images again
    assert server.snapshot()["chat"][-2]["images"] == [rel]


def test_chat_images_survive_700_clip_of_other_roles_and_long_user_text(api, hq, upload_dir):
    hq.agent("Boss", director=True)
    rel = "uploads/abc.png"
    (upload_dir / "abc.png").write_bytes(PNG_BYTES)
    text = ("wort " * 300).strip()                              # ~1499 chars, far beyond the old 700 clip
    code, _, _ = api.post("/api/chat", {"text": text, "images": [rel]})
    assert code == 202
    hq.wait_idle()
    prompt = hq.stub.director_calls()[0][1]
    assert text in prompt                                       # owner text uncut
    assert abs_line(upload_dir, rel) in prompt                  # image path present and uncut


@pytest.mark.parametrize("images", ["uploads/x.png", 42, ["../state.json"], ["uploads/../../x.png"],
                                    ["uploads/missing.png"], ["a" * 70]])
def test_chat_with_invalid_images_is_rejected(api, hq, images):
    hq.agent("Boss", director=True)
    code, body, _ = api.post("/api/chat", {"text": "hi", "images": images})
    assert code in (400, 404) and "error" in body
    assert [m for m in server.chat if m["role"] == "user"] == []


def test_chat_accepts_leading_slash_image_path(api, hq, upload_dir):
    hq.agent("Boss", director=True)
    rel = "uploads/abc.png"
    (upload_dir / "abc.png").write_bytes(PNG_BYTES)
    code, _, _ = api.post("/api/chat", {"text": "hi", "images": ["/" + rel]})
    assert code == 202
    hq.wait_idle()
    assert [m for m in server.chat if m["role"] == "user"][-1]["images"] == [rel]


def test_chat_with_images_and_empty_text_is_accepted(api, hq, upload_dir):
    hq.agent("Boss", director=True)
    rel = "uploads/abc.png"
    (upload_dir / "abc.png").write_bytes(PNG_BYTES)
    code, body, _ = api.post("/api/chat", {"text": "", "images": [rel]})
    assert code == 202, body
    hq.wait_idle()
    msg = [m for m in server.chat if m["role"] == "user"][-1]
    assert msg["text"] == "" and msg["images"] == [rel]
    assert abs_line(upload_dir, rel) in hq.stub.director_calls()[0][1]


def test_chat_with_no_text_and_no_images_is_rejected(api):
    code, body, _ = api.post("/api/chat", {"text": "", "images": []})
    assert code == 400 and "empty" in body["error"]


# ---------------- images on agent tasks ----------------

def test_direct_task_appends_absolute_image_paths(api, hq, upload_dir):
    a = hq.agent("Worker")
    rel = "uploads/abc.png"
    (upload_dir / "abc.png").write_bytes(PNG_BYTES)
    code, body, _ = api.post(f"/api/agents/{a['id']}/task", {"task": "look at the picture", "images": [rel]})
    assert code == 202, body
    hq.wait_idle()
    agent, prompt = hq.stub.worker_calls("Worker")[0]
    assert abs_line(upload_dir, rel) in prompt
    assert a["task"] == "look at the picture"                   # stored task text stays clean


def test_director_assign_action_can_carry_images(hq, upload_dir):
    hq.agent("Worker")
    rel = "uploads/abc.png"
    (upload_dir / "abc.png").write_bytes(PNG_BYTES)
    hq.act({"type": "assign", "agent": "Worker", "task": "read it", "images": [rel]})
    hq.wait_idle()
    _, prompt = hq.stub.worker_calls("Worker")[0]
    assert abs_line(upload_dir, rel) in prompt


def test_direct_task_with_broken_images_is_rejected(api, hq):
    a = hq.agent("Worker")
    code, body, _ = api.post(f"/api/agents/{a['id']}/task", {"task": "x", "images": ["uploads/nope.png"]})
    assert code == 404 and "error" in body
    assert hq.stub.worker_calls() == []
