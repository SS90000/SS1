"""Fail the workflow if data.json is invalid or lost data. Usage: validate.py before.json after.json"""
import json, sys
before, after = (json.load(open(p)) for p in sys.argv[1:3])
def count(d): return len(d["drugs"]), sum(len(x["records"]) for x in d["drugs"])
b, a = count(before), count(after)
assert set(before) <= set(after), f"top-level keys removed: {set(before) - set(after)}"
assert a[0] >= b[0] and a[1] >= b[1], f"drugs/records went down: {b} -> {a}"
STATUS = {"Approved", "Recommended", "Under review"}
CONF = {"regulator", "company", "database", "thirdparty"}
for x in after["drugs"]:
    for k in ("id", "inn", "brands", "sponsors", "records"): assert k in x, f"{x.get('inn')}: missing {k}"
    for r in x["records"]:
        assert r.get("status") in STATUS, f"{x['inn']}: bad status {r.get('status')}"
        assert r.get("confidence") in CONF, f"{x['inn']}: bad confidence {r.get('confidence')}"
        assert r.get("source", "").startswith("http"), f"{x['inn']}: missing source"
print(f"OK: {b} -> {a} (drugs, records)")
