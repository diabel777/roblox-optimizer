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
