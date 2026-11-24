import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import zlib

from pro_optimizer import gamepad as g, wheel as wh


def test_sanitize_clamps_and_rejects_garbage():
    s = g.sanitize({"color": [999, -5, "x"], "brightness": 500, "trigger_left": "evil", "headphone": "abc", "mic_led": 1})
    assert s["color"] == [255, 0, 0] and s["brightness"] == 100
    assert s["trigger_left"] == "off" and s["headphone"] == 70 and s["mic_led"] is True
    assert g.sanitize("nonsense") == g.sanitize(None)


def test_dualsense_usb_report_layout():
    r = g.build_dualsense({"color": [1, 2, 3], "brightness": 100, "headphone": 100, "mic": 0})
    assert len(r) == 63 and r[0] == 0x02
    assert r[1 + 44:1 + 47] == bytes([1, 2, 3])
    assert r[1 + 4] == 255 and r[1 + 6] == 0


def test_dualsense_bluetooth_crc():
    r = g.build_dualsense({}, bluetooth=True, seq=3)
    assert len(r) == 78 and r[0] == 0x31 and r[1] == 0x30
    assert r[-4:] == zlib.crc32(b"\xa2" + r[:-4]).to_bytes(4, "little")


def test_dualshock4_reports():
    usb = g.build_dualshock4({"color": [10, 20, 30], "brightness": 50})
    assert len(usb) == 32 and usb[0] == 0x05 and usb[6:9] == bytes([5, 10, 15])
    bt = g.build_dualshock4({}, bluetooth=True)
    assert len(bt) == 78 and bt[-4:] == zlib.crc32(b"\xa2" + bt[:-4]).to_bytes(4, "little")


def test_trigger_modes():
    assert g._trigger_bytes("off", 10, 10) == bytes(11)
    assert g._trigger_bytes("rigid", 50, 100)[:3] == bytes([1, 128, 255])
    assert g._trigger_bytes("section", 0, 100)[0] == 2


def test_wheel_profiles_all_combinations():
    for b in wh.BRANDS:
        for gm in wh.GAMES:
            for st in wh.STYLES:
                p = wh.profile(b, gm, st)
                assert p["game_rows"] and all(0 <= v <= 100 for _, v, _ in p["game_rows"])
    assert len(wh.profile("g29", "fh4", "real")["game_rows"]) < len(wh.profile("g29", "fh5", "real")["game_rows"])
    assert wh.profile("nonsense", "x", "y")["brand"] == wh.BRANDS["other"]["name"]


def test_nettools_and_autotune():
    from pro_optimizer import autotune, nettools
    assert nettools.parse_ping("Average = 5ms") == 5.0 and nettools.parse_ping("brak") is None
    assert nettools.ping("evil.com; calc") is None            # tylko hosty z listy
    assert "power" not in autotune.plan(16, True, True)["tweaks"]   # laptop: bez planu max. wydajności
    assert "power" in autotune.plan(16, False, True)["tweaks"]
    assert "power" not in autotune.plan(16, False, False)["tweaks"]


def test_keep_mode_does_not_touch_game_rumble_or_audio():
    r = g.build_dualsense({"trigger_left": "off", "trigger_right": "off"}, mode="keep")
    f0 = r[1]
    assert f0 & 0b00000001 == 0                 # brak flagi wibracji
    assert f0 & 0b11110000 == 0                 # brak głośności / audio
    assert f0 & 0b00001100 == 0                 # spusty wyłączone -> gra ma nimi sterować
    r2 = g.build_dualsense({"trigger_right": "rigid"}, mode="keep")
    assert r2[1] & 0b00000100
    assert g.build_dualshock4({}, mode="keep")[1] == 0x06


def test_auto_triggers_by_game():
    cfg = g.effective_config({}, ["forza5"])
    assert cfg["trigger_left"] == "rigid" and cfg["_trig"]["left"] == (15, 75)
    assert g.effective_config({}, ["notepad"])["trigger_left"] == "off"
    assert g.effective_config({"auto_triggers": False}, ["forza5"])["trigger_left"] == "off"
    rep = g.build_dualsense(cfg, mode="keep")
    assert rep[1 + 21] == 1 and rep[1 + 23] == round(75 * 255 / 100)


def test_integrity_detects_tampering(tmp_path):
    from pro_optimizer import ed25519, integrity
    sk = bytes(range(32))
    pk = ed25519.public_key(sk).hex()
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.bin").write_bytes(b"\x00\x01")
    (tmp_path / integrity.FILE).write_text(__import__("json").dumps(integrity.build(tmp_path, sk)))
    assert integrity.verify(tmp_path, pk)["ok"]
    (tmp_path / "a.txt").write_text("evil")
    (tmp_path / "new.dll").write_text("x")
    r = integrity.verify(tmp_path, pk)
    assert not r["ok"] and r["modified"] == ["a.txt"] and r["extra"] == ["new.dll"]
    assert not integrity.verify(tmp_path, ed25519.public_key(bytes(32)).hex())["ok"]   # zły klucz = odrzucone


def test_selfheal_restores_launcher(tmp_path):
    from pro_optimizer import selfheal
    from pro_optimizer.version import LAUNCHER_EXE
    (tmp_path / LAUNCHER_EXE).write_bytes(b"launcher-bytes")
    selfheal.ensure(tmp_path)
    assert (tmp_path / selfheal.BACKUP).read_bytes() == b"launcher-bytes"
    (tmp_path / LAUNCHER_EXE).unlink()                         # np. antywirus usunął launcher
    assert selfheal.ensure(tmp_path)["launcher"] is True
    assert (tmp_path / LAUNCHER_EXE).read_bytes() == b"launcher-bytes"


def test_rumble_report_has_all_flags_and_stop_report_too():
    r = g.build_dualsense({"rumble_left": 100, "rumble_right": 50}, mode="rumble")
    assert r[1] & 0b11 == 0b11 and r[1 + 38] & 0b100 and r[1 + 3] == 255 and r[1 + 2] == 128
    stop = g.build_dualsense({"rumble_left": 0, "rumble_right": 0}, mode="rumble")
    assert stop[1] & 1 and stop[1 + 3] == 0                      # flaga wibracji jest, silniki 0 => pad się zatrzymuje
    assert g.build_dualsense({}, mode="apply")[1] & 1 == 0       # zwykłe zastosowanie nie rusza wibracji


def test_battery_parsing():
    ds = g.Pad(b"x", 0x0CE6, False)
    usb = bytearray(64); usb[0] = 0x01; usb[53] = 0x17           # poziom 7, ładowanie
    assert g.parse_battery(bytes(usb), ds) == {"percent": 75, "state": "charging"}
    usb[53] = 0x20
    assert g.parse_battery(bytes(usb), ds)["state"] == "full"
    ds4 = g.Pad(b"x", 0x05C4, False)
    r = bytearray(64); r[0] = 0x01; r[30] = 0x04                 # bateria, poziom 4 z 8
    assert g.parse_battery(bytes(r), ds4) == {"percent": 50, "state": "discharging"}
    assert g.parse_battery(b"\x01\x00", ds) is None and g.parse_battery(b"", ds) is None


def test_bluetooth_detection():
    assert g.is_bluetooth({"bus_type": 2}) and not g.is_bluetooth({"bus_type": 1})
    assert g.is_bluetooth({"path": b"\\\\?\\HID#{00001124-0000-1000-8000-00805f9b34fb}_VID&0002054c"})
    assert not g.is_bluetooth({"path": b"\\\\?\\HID#VID_054C&PID_0CE6#7&abc"})


def test_speedtest_math_and_grading():
    from pro_optimizer import speedtest as st
    assert st.mbps(12_500_000, 1.0) == 100.0 and st.mbps(1, 0) == 0.0
    assert st.jitter([10, 12, 10, 14]) == (2 + 2 + 4) / 3
    good = st.grade({"ping": 12, "jitter": 2, "loss": 0, "down": 300, "up": 50, "loaded_ping": 25})
    assert good["Gry online"] == "Świetnie" and good["Streaming 4K"] == "Świetnie" and good["Opóźnienie pod obciążeniem"] == "Brak problemu"
    bad = st.grade({"ping": 150, "jitter": 40, "loss": 5, "down": 5, "up": 1, "loaded_ping": 400})
    assert bad["Gry online"] == "Słabo" and "QoS" in bad["Opóźnienie pod obciążeniem"]
    assert st.HOST == "speed.cloudflare.com" and st.DOWN.startswith("https://")


def test_battery_tracker_alerts_and_estimates():
    from pro_optimizer import padbattery as pb
    t = pb.Tracker()
    cfg = {"enabled": True, "drop": 5, "low": 15}
    t.add(80, "discharging", 0)
    assert t.alerts(cfg) == []
    t.add(74, "discharging", 600)
    assert any("74" in m for m in t.alerts(cfg))
    assert t.alerts(cfg) == []                       # ten sam alert nie powtarza się
    assert t.minutes_left() == round(74 / (6 / 10))
    t.add(14, "discharging", 6000)
    assert any("Niski" in m for m in t.alerts(cfg))
    t.add(15, "charging", 6100)
    t.add(40, "charging", 7000)
    assert t.minutes_left() and t.minutes_left() > 0
    assert pb.sanitize_alerts({"drop": "x", "low": 999})["low"] == 50


def test_ram_automation_modes():
    from pro_optimizer import automation as au
    base = {"ram": {"enabled": True, "threshold_pct": 80, "min_interval_min": 5, "interval_min": 10, "mode": "interval"}}
    assert au.plan(base, 1000, {"ram": 0}, 10, [], set()) == ["ram"]          # minęło 10 min, RAM niski -> czas
    assert au.plan(base, 100, {"ram": 0}, 99, [], set()) == []                 # tryb czasu ignoruje próg
    base["ram"]["mode"] = "threshold"
    assert au.plan(base, 1000, {"ram": 0}, 10, [], set()) == []
    assert au.plan(base, 1000, {"ram": 0}, 90, [], set()) == ["ram"]
    base["ram"]["mode"] = "both"
    assert au.plan(base, 1000, {"ram": 0}, 10, [], set()) == ["ram"]
