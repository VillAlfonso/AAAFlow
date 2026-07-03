"""Poll an AAAFlow job until it finishes. Token-cheap: prints only stage changes.

Usage:  python scratchpad/poll.py <job_id> [timeout_sec=590]
Exit:   0 = done, 1 = job error, 2 = timeout (job still running — re-arm)
"""
import json
import sys
import time
import urllib.request

jid = sys.argv[1]
budget = float(sys.argv[2]) if len(sys.argv) > 2 else 590
t0 = time.time()
last = ""
while time.time() - t0 < budget:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:8000/api/jobs/{jid}", timeout=10) as r:
            j = json.load(r)
    except Exception as e:  # noqa: BLE001
        print("poll error:", e, flush=True)
        time.sleep(6)
        continue
    line = f"{j['status']} · {j.get('stage') or ''} · {round((j.get('progress') or 0) * 100)}%"
    if line != last:
        print(line, flush=True)
        last = line
    if j["status"] == "done":
        print(json.dumps(j.get("result"))[:500])
        sys.exit(0)
    if j["status"] == "error":
        print("ERROR:", j.get("error"))
        sys.exit(1)
    time.sleep(10)
print("TIMEOUT")
sys.exit(2)
