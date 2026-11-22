import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from pro_optimizer import profiles  # noqa: E402

KNOWN = {"power", "gamemode", "fse"}
PRESETS = {"balanced", "performance"}
CURVES = {"quiet", "balanced"}


def parse(d):
    return profiles.parse(json.dumps(d), KNOWN, PRESETS, CURVES)


class FakeSettings:
    def __init__(self):
        self.d = {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = v


class ProfileTests(unittest.TestCase):
    def good(self, **kw):
        d = {"format": "pou-profile", "version": 1, "name": "x", "tweaks": ["power"]}
        d.update(kw)
        return d

    def test_roundtrip(self):
        s = FakeSettings()
        s.d = {"roblox_profile": {"preset": "performance", "fps": 144}, "fan": {"curve": "quiet"},
               "auto": {"ram": {"enabled": True, "threshold_pct": 80, "min_interval_min": 10}}}
        exp = profiles.export_profile(s.get, {"power": True, "fse": False}, "Moj", "4.2.0")
        p = parse(exp)
        self.assertEqual(p["tweaks"], ["power"])
        self.assertEqual(p["roblox"], {"preset": "performance", "fps": 144})
        self.assertEqual(p["auto"]["ram"]["threshold_pct"], 80)

    def test_rejects_wrong_format_and_garbage(self):
        for bad in (b"not json", b"[]", json.dumps({"format": "x"}).encode(), b"\xff\xfe"):
            with self.assertRaises(profiles.ProfileError):
                profiles.parse(bad, KNOWN, PRESETS, CURVES)

    def test_too_big(self):
        with self.assertRaises(profiles.ProfileError):
            profiles.parse(b" " * (profiles.MAX_BYTES + 1), KNOWN, PRESETS, CURVES)

    def test_unknown_values_dropped(self):
        p = parse(self.good(tweaks=["power", "evil", "../x", 5, "fse"], roblox={"preset": "hack", "fps": 60},
                            fan={"curve": "nope"}, extra={"cmd": "calc"}))
        self.assertEqual(p["tweaks"], ["power", "fse"])
        self.assertNotIn("roblox", p)
        self.assertNotIn("fan", p)
        self.assertNotIn("extra", p)

    def test_numbers_have_hard_limits(self):
        for fps in (-1, 5000, True, "60"):
            with self.assertRaises(profiles.ProfileError):
                parse(self.good(roblox={"preset": "balanced", "fps": fps}))
        with self.assertRaises(profiles.ProfileError):
            parse(self.good(auto={"ram": {"threshold_pct": 1}}))

    def test_name_sanitized(self):
        p = parse(self.good(name="a\x00b\nc" + "z" * 200))
        self.assertNotIn("\x00", p["name"])
        self.assertNotIn("\n", p["name"])
        self.assertLessEqual(len(p["name"]), 60)

    def test_newer_version_refused(self):
        with self.assertRaises(profiles.ProfileError):
            parse(self.good(version=2))

    def test_apply_settings(self):
        s = FakeSettings()
        s.d = {"roblox_profile": {"preset": "balanced", "fps": 0, "targets": ["player"]}}
        p = parse(self.good(roblox={"preset": "performance", "fps": 120}, fan={"curve": "quiet"},
                            auto={"dns": {"enabled": True, "interval_hours": 12}}))
        profiles.apply_settings(p, s)
        self.assertEqual(s.d["roblox_profile"]["preset"], "performance")
        self.assertEqual(s.d["roblox_profile"]["targets"], ["player"])      # cudze pola zachowane
        self.assertEqual(s.d["fan"]["curve"], "quiet")
        self.assertTrue(s.d["auto"]["dns"]["enabled"])


if __name__ == "__main__":
    unittest.main()
