#!/usr/bin/env python3
"""EDINET 書類一覧を期間分取得し、有価証券報告書(docTypeCode=120, secCodeあり)を集計."""
import datetime, json, os, sys, time, urllib.request, urllib.parse

key = os.environ.get("EDINET_KEY") or sys.exit("export EDINET_KEY=...")
LISTS = "raw/edinet/lists"
os.makedirs(LISTS, exist_ok=True)

def list_docs(day):
    url = "https://api.edinet-fsa.go.jp/api/v2/documents.json?" + urllib.parse.urlencode(
        {"date": day, "type": 2, "Subscription-Key": key})
    with urllib.request.urlopen(url, timeout=90) as r:
        return json.load(r).get("results", [])

def main(start, end):
    d = datetime.date.fromisoformat(start)
    end_d = datetime.date.fromisoformat(end)
    yuho = {}  # edinetCode -> doc record (最新優先: 後方の日付で上書き)
    while d <= end_d:
        day = d.isoformat()
        path = f"{LISTS}/{day}.json"
        if os.path.exists(path):
            res = json.load(open(path)).get("results", [])
        else:
            try:
                res = list_docs(day)
                with open(path, "w") as f: json.dump({"results": res}, f, ensure_ascii=False)
            except Exception as e:
                print(day, "ERR", e); res = []
            time.sleep(1.2)
        n = sum(1 for x in res if x.get("docTypeCode") == "120" and x.get("secCode"))
        for x in res:
            if x.get("docTypeCode") == "120" and x.get("secCode"):
                yuho[x["edinetCode"]] = x
        print(day, f"docs={len(res)} yuho={n} unique={len(yuho)}", flush=True)
        d += datetime.timedelta(days=1)
    with open("data/edinet_yuho_index.json", "w") as f:
        json.dump(yuho, f, ensure_ascii=False, indent=0)
    print("TOTAL unique filers:", len(yuho))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
