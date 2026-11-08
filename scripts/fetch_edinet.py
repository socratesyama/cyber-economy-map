#!/usr/bin/env python3
"""EDINET API v2 pipeline — 有価証券報告書の取得と主要データ抽出 (tier 1 source).

使い方:
  1. EDINET API利用者登録 (無料) で Subscription-Key を取得
     https://www.fsa.go.jp/opendata/ (EDINET API v2利用規約に同意して発行)
  2. export EDINET_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  3. python3 fetch_edinet.py --start 2026-10-01 --end 2026-10-31 --download

出力:
  ../raw/edinet/documents_YYYYMMDD.json   書類一覧
  ../raw/edinet/xbrl/{doc_id}.zip         有報XBRL
  ../data/edinet_extract.jsonl            抽出済みレコード (大株主・関係会社等)

抽出対象 (有価証券報告書 XBRL / ESEF):
  - 大株主の状況        (jpcrp_cor:ShareholdersByNumberOfShares など)
  - 関係会社の状況      (jpcrp_cor:OverviewOfAffiliatedCompanies)
  - 主要な販売先・仕入先 (jpcrp_cor:MajorCustomersText / suppliers)
  - 地域別売上          (jpcrp_cor:SegmentGeography)
  - 財務諸表            (jplvf_cor / ifrs-full タグ)
"""
import argparse, datetime, json, os, sys, time, urllib.request, urllib.error, zipfile

API = "https://api.edinet-fsa.go.jp/api/documents/v2"
RAW = "../raw/edinet"
DATA = "../data"

def headers():
    key = os.environ.get("EDINET_KEY")
    if not key:
        sys.exit("EDINET_KEY 環境変数を設定してください（無料登録: https://www.fsa.go.jp/opendata/）")
    return {"Ocp-Apim-Subscription-Key": key, "User-Agent": "CyberEconomyMap/0.1"}

def fetch_json(url):
    req = urllib.request.Request(url, headers=headers())
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def list_documents(day, doc_type=2):
    """type=2: 提出された書類 (有報等)."""
    url = f"{API}.json?date={day}&type={doc_type}"
    try:
        return fetch_json(url)
    except urllib.error.HTTPError as e:
        print(f"{day}: HTTP {e.code}")
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True)
    ap.add_argument("--download", action="store_true", help="XBRLをダウンロード")
    ap.add_argument("--limit", type=int, default=50, help="1日あたりの最大DL数")
    args = ap.parse_args()

    os.makedirs(f"{RAW}/xbrl", exist_ok=True)
    os.makedirs(DATA, exist_ok=True)
    d = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end)
    # 有価証券報告書: formCode 030000 (本体), type 2 = 提出書類
    while d <= end:
        day = d.isoformat()
        res = list_documents(day)
        d += datetime.timedelta(days=1)
        if not res: continue
        docs = res.get("results", [])
        yuho = [x for x in docs if x.get("formCode") == "030000" and x.get("secCode")]
        print(f"{day}: {len(docs)} docs, {len(yuho)} 有報")
        with open(f"{RAW}/documents_{day.replace('-','')}.json", "w") as f:
            json.dump(res, f, ensure_ascii=False)
        if not args.download: continue
        for x in yuho[: args.limit]:
            doc_id = x["docID"]
            path = f"{RAW}/xbrl/{doc_id}.zip"
            if os.path.exists(path): continue
            url = f"{API}/{doc_id}?type=5"  # type=5: XBRL
            try:
                req = urllib.request.Request(url, headers=headers())
                with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
                    f.write(r.read())
                print("  saved", doc_id, x.get("secCode"), x.get("filerName"))
            except urllib.error.HTTPError as e:
                print("  DL error", doc_id, e.code)
            time.sleep(1)  # 礼儀正しいレート制限

if __name__ == "__main__":
    main()
