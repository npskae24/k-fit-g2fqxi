#!/usr/bin/env python3
"""Extract a compact data.json from an Apple Health export.xml (read-only).

Usage: python3 tools/extract.py /path/to/export.xml [checkins.db] > data.json
The site never needs the export itself; only data.json is published.
No personal identifiers (names, device names, source names) are written out.
Home-scale BIA and self-reported waist/baseline are copied from
tools/curated-body.json. Those dates are Asia/Bangkok measurement dates
and are not rewritten from a sync timestamp.
"""
import sys, json, sqlite3, datetime as dt, bisect, os, re
from array import array
from collections import defaultdict
import xml.etree.ElementTree as ET

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")

def load_curated():
    """Copy the whitelist of published body facts. Drop anything else."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "curated-body.json")
    if not os.path.exists(path):
        return [], []
    with open(path, encoding="utf-8") as f:
        extra = json.load(f)
    if not isinstance(extra, dict):
        raise SystemExit("curated-body.json must be an object")
    unknown = set(extra) - {"bia", "reported"}
    if unknown:
        raise SystemExit("curated-body.json unexpected keys: %s" % sorted(unknown))
    bia_keep = ("d", "t", "tz", "tod", "kg", "bmi", "pbf", "ffm", "src", "method", "pick")
    rep_keep = ("d", "t", "tz", "tod", "kg", "cm", "inches", "src", "kind", "meal")

    def take(rows, keep, need):
        out = []
        if not rows:
            return out
        if not isinstance(rows, list):
            raise SystemExit("curated rows must be a list")
        for r in rows:
            if not isinstance(r, dict):
                raise SystemExit("curated row must be an object")
            bad = set(r) - set(keep)
            if bad:
                raise SystemExit("curated unexpected field %s" % sorted(bad))
            if not _DATE.match(str(r.get("d", ""))):
                raise SystemExit("curated bad date")
            if "t" in r and not _TIME.match(str(r["t"])):
                raise SystemExit("curated bad time on %s" % r["d"])
            for k in need:
                if k not in r:
                    raise SystemExit("curated %s missing %s" % (r["d"], k))
            out.append({k: r[k] for k in keep if k in r})
        return out

    bia = take(extra.get("bia"), bia_keep, ("d", "kg", "pbf", "ffm", "src", "method"))
    reported = take(extra.get("reported"), rep_keep, ("d", "src", "kind"))
    for r in reported:
        if "kg" not in r and "cm" not in r:
            raise SystemExit("curated reported %s needs kg or cm" % r["d"])
    return bia, reported

# Published series start on this Asia/Bangkok calendar date.
START = "2026-11-01"

def clip_published(data):
    """Remove every dated row before START. The site publishes this file only."""
    def day(row, key):
        return row[0] if key is None else str(row.get(key, ""))[:10]
    for key in ("daily", "bodyMass", "waist", "bodyFatPct", "rhr"):
        data[key] = [r for r in data[key] if day(r, None) >= START]
    for key, field in (("workouts", "d"), ("manual", "d"), ("bia", "d"), ("reported", "d"), ("inbody", "date")):
        data[key] = [r for r in data[key] if day(r, field) >= START]
    data["start"] = START
    return data

XML = sys.argv[1]
DB = sys.argv[2] if len(sys.argv) > 2 else None

def is_watch(src):
    s = (src or "").replace("\xa0", " ")
    return "Apple Watch" in s

SRC_PRI = {"watch": 0, "garmin": 1, "strava": 2, "whoop": 3, "other": 4}
def src_label(src):
    if is_watch(src): return "watch"
    return {"Connect": "garmin", "Strava": "strava", "WHOOP": "whoop"}.get(src or "", "other")

def ep(s):  # "2026-11-16 07:00:00 +0700" -> epoch seconds
    return int(dt.datetime.fromisoformat(s[:10] + "T" + s[11:19] + s[20:23] + ":" + s[23:25]).timestamp())

active = defaultdict(float); steps_w = defaultdict(float); steps_p = defaultdict(float)
exmin = defaultdict(float); rhr = {}
mass = []; waist = []; fatpct = []
hr_t = array("q"); hr_v = array("f")
asum = {}  # ActivitySummary for cross-check
workouts = []
src_active = defaultdict(int)
export_date = None

ctx = ET.iterparse(XML, events=("start", "end"))
_, root = next(ctx)
n = 0
for ev, el in ctx:
    if ev != "end":
        continue
    tag = el.tag
    if tag == "ExportDate":
        export_date = el.get("value")
        el.clear()
    elif tag == "Record":
        t = el.get("type"); src = el.get("sourceName")
        if t == "HKQuantityTypeIdentifierHeartRate":
            if is_watch(src):
                hr_t.append(ep(el.get("startDate"))); hr_v.append(float(el.get("value")))
        elif t == "HKQuantityTypeIdentifierActiveEnergyBurned":
            src_active[(src or "").replace("\xa0", " ").split("’")[-1]] += 1
            if is_watch(src):
                v = float(el.get("value"));
                if el.get("unit") == "kJ": v /= 4.184
                active[el.get("startDate")[:10]] += v
        elif t == "HKQuantityTypeIdentifierStepCount":
            d = el.get("startDate")[:10]; v = float(el.get("value"))
            (steps_w if is_watch(src) else steps_p)[d] += v
        elif t == "HKQuantityTypeIdentifierAppleExerciseTime":
            if is_watch(src): exmin[el.get("startDate")[:10]] += float(el.get("value"))
        elif t == "HKQuantityTypeIdentifierRestingHeartRate":
            rhr[el.get("startDate")[:10]] = round(float(el.get("value")))
        elif t == "HKQuantityTypeIdentifierBodyMass":
            v = float(el.get("value"))
            if el.get("unit") == "lb": v *= 0.45359237
            src_kind = "watch" if is_watch(src) else ("health" if src == "Health" else "app")
            mass.append([el.get("startDate")[:10], round(v, 2), src_kind])
        elif t == "HKQuantityTypeIdentifierWaistCircumference":
            v = float(el.get("value")); u = el.get("unit")
            v = v * 100 if u == "m" else v * 2.54 if u == "in" else v
            waist.append([el.get("startDate")[:10], round(v, 1)])
        elif t == "HKQuantityTypeIdentifierBodyFatPercentage":
            fatpct.append([el.get("startDate")[:10], round(float(el.get("value")) * 100, 1)])
        el.clear()
    elif tag == "ActivitySummary":
        d = el.get("dateComponents")
        if d and el.get("activeEnergyBurned"):
            asum[d] = float(el.get("activeEnergyBurned"))
        el.clear()
    elif tag == "Workout":
        w = {"type": el.get("workoutActivityType", "").replace("HKWorkoutActivityType", ""),
             "start": el.get("startDate"), "end": el.get("endDate"),
             "dur": round(float(el.get("duration") or 0), 1), "src": src_label(el.get("sourceName"))}
        if el.get("durationUnit") == "sec": w["dur"] = round(w["dur"] / 60, 1)
        if el.get("totalDistance"):
            dv = float(el.get("totalDistance")); du = el.get("totalDistanceUnit")
            w["km"] = dv * 1.609344 if du == "mi" else dv / 1000 if du == "m" else dv
        if el.get("totalEnergyBurned"):
            w["kcal"] = float(el.get("totalEnergyBurned"))
        for c in el:
            if c.tag == "WorkoutStatistics":
                ty = c.get("type")
                if ty.endswith("ActiveEnergyBurned") and c.get("sum"):
                    v = float(c.get("sum")); w["kcal"] = v / 4.184 if c.get("unit") == "kJ" else v
                elif ty.endswith("HeartRate"):
                    if c.get("average"): w["hr"] = float(c.get("average"))
                    if c.get("maximum"): w["hrmax"] = float(c.get("maximum"))
                elif ty.startswith("HKQuantityTypeIdentifierDistance") and c.get("sum"):
                    dv = float(c.get("sum")); du = c.get("unit")
                    w["km"] = dv * 1.609344 if du == "mi" else dv / 1000 if du == "m" else dv
            elif c.tag == "MetadataEntry" and c.get("key") == "HKIndoorWorkout":
                w["indoor"] = c.get("value") == "1"
        workouts.append(w)
        el.clear()
    n += 1
    if n % 200000 == 0:
        root.clear()

# HR from samples for workouts lacking statistics
order = sorted(range(len(hr_t)), key=hr_t.__getitem__)
T = [hr_t[i] for i in order]; V = [hr_v[i] for i in order]
# de-duplicate the same session synced from several apps (keep Apple Watch first)
for w in workouts:
    w["a"], w["b"] = ep(w["start"]), ep(w["end"])
kept = []
for w in sorted(workouts, key=lambda w: SRC_PRI[w["src"]]):
    dup = False
    for k in kept:
        ov = min(w["b"], k["b"]) - max(w["a"], k["a"])
        if ov > 0.5 * max(60, min(w["b"] - w["a"], k["b"] - k["a"])):
            dup = True; break
    if not dup: kept.append(w)
sys.stderr.write("workouts raw=%d kept=%d\n" % (len(workouts), len(kept)))
workouts = kept
out_w = []
for w in workouts:
    a, b = ep(w["start"]), ep(w["end"])
    if "hr" not in w:
        i, j = bisect.bisect_left(T, a), bisect.bisect_right(T, b)
        if j > i:
            seg = V[i:j]; w["hr"] = sum(seg) / len(seg); w["hrmax"] = max(seg)
    row = {"d": w["start"][:10], "t": w["start"][11:16], "type": w["type"], "min": w["dur"]}
    if w.get("km"): row["km"] = round(w["km"], 2)
    if w.get("hr"): row["hr"] = round(w["hr"])
    if w.get("hrmax"): row["hrmax"] = round(w["hrmax"])
    if w.get("kcal") is not None: row["kcal"] = round(w["kcal"])
    if "indoor" in w: row["in"] = 1 if w["indoor"] else 0
    row["src"] = w["src"]
    out_w.append(row)
out_w.sort(key=lambda r: (r["d"], r["t"]))

days = sorted(set(active) | set(steps_w) | set(exmin))
daily = []
for d in days:
    st = steps_w.get(d) or steps_p.get(d) or 0
    daily.append([d, round(active.get(d, 0)), round(st), round(exmin.get(d, 0))])

# Last complete calendar day in Asia/Bangkok: the day before ExportDate
# unless the export itself was taken late evening (>= 21:00).
if export_date:
    exp_day = dt.date.fromisoformat(export_date[:10])
    exp_hour = int(export_date[11:13])
    last_full = (exp_day if exp_hour >= 21 else exp_day - dt.timedelta(days=1)).isoformat()
else:
    last_full = days[-1] if days else ""
sys.stderr.write("exportDate=%s lastFullDay=%s\n" % (export_date, last_full))

bia, reported = load_curated()
data = {
    "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    "exportLastFullDay": last_full,
    "dailyCols": ["date", "activeKcal", "steps", "exerciseMin"],
    "daily": daily,
    "workouts": out_w,
    "bodyMass": sorted(mass),
    "waist": sorted(waist),
    "bodyFatPct": sorted(fatpct),
    "rhr": sorted([[d, v] for d, v in rhr.items()]),
    "inbody": [], "manual": [],
    "bia": bia, "reported": reported,
}
if DB:
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    for r in c.execute("select test_date,weight_kg,smm_kg,body_fat_kg,pbf_pct,visceral_level,whr,bmr_kcal,ffm_kg,score,bmi from inbody order by 1"):
        data["inbody"].append(dict(zip(["date","kg","smm","fatKg","pbf","visceral","whr","bmr","ffm","score","bmi"], r)))
# Manual entries only for sessions not already present in this export.
data["manual"] = []
clip_published(data)
sys.stderr.write("active sources: %s\n" % dict(src_active))
sys.stderr.write("days=%d workouts=%d mass=%d waist=%d hr_samples=%d bia=%d reported=%d\n" % (len(daily), len(out_w), len(mass), len(waist), len(T), len(data["bia"]), len(data["reported"])))
# cross-check with ActivitySummary
diffs = [(d, round(active.get(d, 0)), round(v)) for d, v in asum.items() if "2026-09-16" <= d <= "2026-11-14" and abs(active.get(d, 0) - v) > 5]
sys.stderr.write("ActivitySummary diffs Sep16-Nov14: %s\n" % diffs[:20])
json.dump(data, sys.stdout, ensure_ascii=False, separators=(",", ":"))
