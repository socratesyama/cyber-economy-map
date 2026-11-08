#!/usr/bin/env python3
"""EDINET 有報CSV(type=5)を一括ダウンロード（レジューム対応）."""
import json, os, sys, time, urllib.request, urllib.parse, concurrent.futures

key = os.environ.get("EDINET_KEY") or sys.exit("export EDINET_KEY=...")
os.makedirs("raw/edinet/csv", exist_ok=True)
idx = json.load(open("data/edinet_yuho_index.json"))
CSV = "raw/edinet/csv"
todo = [(v["docID"], v) for v in idx.values() if not os.path.exists(f"{CSV}/{v['docID']}.zip")]
print("todo:", len(todo), flush=True)

def dl(item):
    doc_id, v = item
    url = f"https://api.edinet-fsa.go.jp/api/v2/documents/{doc_id}?" + urllib.parse.urlencode(
        {"type": 5, "Subscription-Key": key})
    try:
        with urllib.request.urlopen(url, timeout=300) as r, open(f"{CSV}/{doc_id}.zip", "wb") as f:
            f.write(r.read())
        return doc_id, "ok"
    except Exception as e:
        return doc_id, f"ERR {str(e)[:60]}"

done = 0
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
    for doc_id, status in ex.map(dl, todo):
        done += 1
        if status != "ok":
            print(doc_id, status, flush=True)
        if done % 100 == 0:
            print(f"{done}/{len(todo)}", flush=True)
print("FINISHED", done)
