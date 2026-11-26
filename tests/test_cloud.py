import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import base64
import io
import json
import zipfile

import pytest

from pro_optimizer import cloud


def test_code_normalization_and_validation():
    assert cloud.normalize_code("abcde-23456") == "ABCDE23456"
    assert cloud.CODE_RE.match(cloud.normalize_code(" ab cde-23 456 "))
    with pytest.raises(cloud.CloudError):
        cloud.link("123", "PC")


def test_token_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud, "_token_file", lambda: tmp_path / "cloud.bin")
    assert not cloud.is_linked()
    cloud.save_account("a" * 64, "Diabel", "d***@x.pl")
    acc = cloud.load_account()
    assert acc["nick"] == "Diabel" and acc["token"] == "a" * 64
    with pytest.raises(cloud.CloudError):
        cloud.save_account("zly", "x", "y")
    cloud.logout()
    assert not cloud.is_linked()


def test_request_rejects_foreign_paths():
    with pytest.raises(cloud.CloudError):
        cloud._request("GET", "http://evil.example/x")


def test_pack_unpack_and_zip_slip(tmp_path):
    src = tmp_path / "snap"
    src.mkdir()
    (src / "manifest.json").write_text("{}")
    (src / "a.reg").write_text("x")
    data = cloud.pack_dir(src)
    out = tmp_path / "out"
    assert cloud.unpack_to(data, out) == 2
    assert (out / "a.reg").read_text() == "x"
    # złośliwy zip ze ścieżką poza folderem
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.txt", "boom")
    bad = base64.b64encode(buf.getvalue()).decode()
    with pytest.raises(cloud.CloudError):
        cloud.unpack_to(bad, tmp_path / "out2")
    assert not (tmp_path / "evil.txt").exists()


def test_401_logs_out(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud, "_token_file", lambda: tmp_path / "cloud.bin")
    cloud.save_account("b" * 64, "n", "e")

    def boom(*a, **k):
        raise cloud.CloudError("Zaloguj się ponownie", 401)
    monkeypatch.setattr(cloud, "_request", boom)
    with pytest.raises(cloud.CloudError):
        cloud.me()
    assert not cloud.is_linked()


def test_ask_ai_filters_actions(monkeypatch):
    monkeypatch.setattr(cloud, "_authed", lambda *a, **k: {"ok": True, "reply": "ok", "actions": [{"id": "x"}, "zly", {"id": 5}] + [{"id": "a"}] * 9})
    r = cloud.ask_ai([{"role": "user", "content": "hej"}], {})
    assert len(r["actions"]) == 4 and all(isinstance(a["id"], str) for a in r["actions"])


def test_ai_actions_whitelist():
    from pro_optimizer import ai_actions as aa
    assert aa.validate({"id": "rm_rf"}) is None
    assert aa.validate({"id": "open_page", "args": {"page": "../../x"}}) is None
    ok = aa.validate({"id": "open_page", "args": {"page": "speed", "evil": 1}})
    assert ok["args"] == {"page": "speed"}
    assert aa.validate({"id": "enable_automation", "args": {"task": "format_c"}}) is None
    assert aa.validate({"id": "enable_automation", "args": {"task": "ram"}})["args"] == {"task": "ram"}
    assert aa.validate("x") is None and aa.validate({"id": "optimize_now"})["desc"]
