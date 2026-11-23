#!/usr/bin/env python3
"""Check the published home-scale week against tools/curated-body.json.

No network. Fails if a measurement date, value, or the InBody/activity
series drifts, or if extract.py would drop the curated rows.
"""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
data = json.loads((ROOT / "data.json").read_text(encoding="utf-8"))
cur = json.loads((ROOT / "tools" / "curated-body.json").read_text(encoding="utf-8"))

assert data["bia"] == cur["bia"]
assert data["reported"] == cur["reported"]
assert [r["d"] for r in data["bia"]] == ["2026-11-20", "2026-11-21", "2026-11-22", "2026-11-23"]
assert [(r["kg"], r["pbf"], r["ffm"]) for r in data["bia"]] == [
    (76.25, 25.6, 56.7), (75.8, 25.6, 56.4), (76.5, 26.0, 56.6), (76.4, 25.1, 57.2)]
assert data["bia"][0]["tod"] == "morning" and "t" not in data["bia"][0]
assert data["bia"][1]["pick"] == "last-of-two-same-weight"
assert data["bia"][3]["t"] == "08:54:37" and data["bia"][3]["bmi"] == 26.4
for r in data["bia"]:
    assert r["tz"] == "Asia/Bangkok" and r["src"] == "zepp-amazfit" and r["method"] == "home-bia"
    assert "smm" not in r and abs(r["kg"] * (1 - r["pbf"] / 100) - r["ffm"]) < 0.06

base, waist = data["reported"]
assert base["d"] == "2026-11-16" and base["tod"] == "morning" and base["kind"] == "baseline"
assert base["kg"] == 77.0 and base["inches"] == 38 and base["cm"] == 96.52
assert waist["d"] == "2026-11-23" and waist["t"] == "09:12" and waist["kind"] == "waist"
assert waist["inches"] == 37.5 and waist["cm"] == 95.25 and waist["meal"] == "unknown"
assert "kg" not in waist
for r in data["reported"]:
    assert r["tz"] == "Asia/Bangkok" and r["src"] == "manual"
    assert round(r["inches"] * 2.54, 2) == r["cm"]

ib = data["inbody"]
assert ib == [{"date": "2026-11-15 16:08", "kg": 77.7, "smm": 28.5, "fatKg": 26.5, "pbf": 34.1,
               "visceral": 12, "whr": 0.94, "bmr": 1476, "ffm": 51.2, "score": 60, "bmi": 26.9}]
assert data["bodyMass"] == [["2025-06-04", 75.0, "app"], ["2026-04-23", 75.55, "health"],
    ["2026-04-24", 75.45, "health"], ["2026-04-30", 76.0, "app"], ["2026-10-24", 76.0, "watch"]]
assert data["waist"] == [] and data["bodyFatPct"] == [] and data["manual"] == []
assert data["exportLastFullDay"] == "2026-11-22"
assert len(data["daily"]) == 310 and data["daily"][-1][0] == "2026-11-23"
assert len(data["workouts"]) == 486 and len(data["rhr"]) == 658
assert data["generated"] >= "2026-11-23 09:12"

html = (ROOT / "index.html").read_text(encoding="utf-8")
sw = (ROOT / "sw.js").read_text(encoding="utf-8")
assert 'var VER="v1.2"' in html and "k-fit-v1.2" in sw
assert "D.bia" in html and "publishedKg" in html and "z:5" in html
assert "กล้ามเนื้อโครงร่าง (SMM)" in html and "มวลไร้ไขมัน" in html
script = html.split("<script>", 1)[1].split("</script>", 1)[0]
subprocess.run(["node", "--check", "-"], input=script, text=True, check=True)

src = (ROOT / "tools" / "extract.py").read_text(encoding="utf-8")
ns = {"__file__": str(ROOT / "tools" / "extract.py")}
exec(src.split("XML = sys.argv[1]", 1)[0], ns)
assert ns["load_curated"]() == (cur["bia"], cur["reported"])
print("check_body ok", data["generated"])
