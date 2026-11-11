#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""有価証券報告書から「主要な販売先・仕入先」開示を収集し、data/supply_edges_raw.json を生成する。

データ源（いずれも認証不要・無料）:
  1. EDINETPORTAL (https://edinetportal.kazuma-45a.workers.dev)
     銘柄コード → 最新の有価証券報告書 docID を解決
  2. gBizINFO (https://info.gbiz.go.jp/hojin/edinetDownload?docId=...)
     有価証券報告書 PDF を取得（日本経済産業省が一次提供元の EDINET 書類を配信）

処理:
  1. F_jp 企業（db/cybermap.sqlite の ticker）ごとに最新有報 docID を解決（data/yuho_docids.json にキャッシュ）
  2. PDF を取得し pdftotext -layout でテキスト化（raw/supply_txt/ にキャッシュ、PDF は破棄）
  3. 「主な相手先別の販売実績」「主要な販売先」「主要な仕入先」等の開示テーブルをパース
  4. data/supply_edges_raw.json: {ticker: {doc_id, date, unit, customers: [...], suppliers: [...]}}

使い方:
  python3 scripts/fetch_supply_edges.py [--workers 6] [--only 7203 7259 ...] [--limit N]
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from scenario_engine import DB  # noqa: E402

PORTAL = "https://edinetportal.kazuma-45a.workers.dev"
GBIZ = "https://info.gbiz.go.jp/hojin/edinetDownload?docId="
UA = {"User-Agent": "CyberEconomyMap-research/1.0"}
TEXT_DIR = os.path.join(ROOT, "raw", "supply_txt")
YUHO_CACHE = os.path.join(ROOT, "data", "yuho_docids.json")
OUT_PATH = os.path.join(ROOT, "data", "supply_edges_raw.json")

# ---------------------------------------------------------------- text helpers

_FW = {"０": "0", "１": "1", "２": "2", "３": "3", "４": "4", "５": "5",
       "６": "6", "７": "7", "８": "8", "９": "9", "％": "%", "，": ",",
       "　": " "}


def to_ascii(s: str) -> str:
    for k, v in _FW.items():
        s = s.replace(k, v)
    return s


# --------------------------------------------------------------- docID resolve

def load_local_yuho_index():
    """ローカルの EDINET 有報一覧（data/edinet_yuho_index.json）を ticker→docID に変換（フォールバック用）"""
    path = os.path.join(ROOT, "data", "edinet_yuho_index.json")
    if not os.path.exists(path):
        return {}
    idx = json.load(open(path, encoding="utf-8"))
    out = {}
    for k, v in idx.items():
        if v.get("formCode") == "030000" and v.get("secCode"):
            t = v["secCode"][:4]
            if t not in out or v.get("submitDateTime", "") > out[t]["date"]:
                out[t] = {"doc_id": v["docID"], "date": v.get("submitDateTime", "")[:10]}
    return out


def portal_filings(ticker: str, tries: int = 2):
    url = f"{PORTAL}/v1/companies/{ticker}/filings"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            d = json.load(urllib.request.urlopen(req, timeout=20))
            yuho = [f for f in d["data"] if f.get("category") == "有価証券報告書"]
            if yuho:
                best = max(yuho, key=lambda f: f.get("submitDate", ""))
                return {"doc_id": best["docId"], "date": best.get("submitDate", "")}
            return None
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1 + i)


def resolve_docids(tickers, workers=8):
    os.makedirs(os.path.dirname(YUHO_CACHE), exist_ok=True)
    cache = json.load(open(YUHO_CACHE, encoding="utf-8")) if os.path.exists(YUHO_CACHE) else {}
    local = load_local_yuho_index()
    todo = [t for t in tickers if t not in cache or cache[t].get("doc_id") is None]
    if todo:
        print(f"resolving {len(todo)} tickers via EDINETPORTAL ...", flush=True)
        with ThreadPoolExecutor(workers) as ex:
            for t, res in ex.map(lambda t: (t, portal_filings(t)), todo):
                if res is None and t in local:
                    res = local[t]
                if res is None:
                    res = {"doc_id": None, "date": None}
                cache[t] = res
        json.dump(cache, open(YUHO_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    ok = sum(1 for v in cache.values() if v.get("doc_id"))
    print(f"docID resolved: {ok}/{len(tickers)}")
    return cache


# ------------------------------------------------------------------- fetching

def fetch_pdf(doc_id: str, dest: str, tries: int = 3):
    if os.path.exists(dest):
        return True
    for i in range(tries):
        try:
            req = urllib.request.Request(GBIZ + doc_id, headers=UA)
            data = urllib.request.urlopen(req, timeout=90).read()
            if len(data) < 10_000:  # 明らかに不正な応答
                raise ValueError(f"short response {len(data)}")
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            return True
        except Exception as e:
            if i == tries - 1:
                print(f"  download failed {doc_id}: {e}", flush=True)
                return False
            time.sleep(2 + 2 * i)


def pdf_to_text(pdf_path: str, txt_path: str) -> bool:
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext not found")
    r = subprocess.run(["pdftotext", "-layout", pdf_path, txt_path],
                       capture_output=True, timeout=120)
    return r.returncode == 0 and os.path.exists(txt_path) and os.path.getsize(txt_path) > 2000


def fetch_and_extract(item):
    ticker, doc_id = item
    txt_path = os.path.join(TEXT_DIR, f"{ticker}_{doc_id}.txt")
    if os.path.exists(txt_path):  # キャッシュ
        return ticker, doc_id, txt_path
    pdf_path = txt_path + ".pdf"
    if not fetch_pdf(doc_id, pdf_path):
        return ticker, doc_id, None
    try:
        ok = pdf_to_text(pdf_path, txt_path)
        return ticker, doc_id, txt_path if ok else None
    except Exception as e:
        print(f"  extract failed {ticker} {doc_id}: {e}", flush=True)
        return ticker, doc_id, None
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)  # PDF はテキスト化後破棄


# -------------------------------------------------------------------- parsing

# 開示セクションの見出し（「主要な販売先及び仕入先」等のバリエーション）
HEADER_PAT = re.compile(
    r"(主な相手先別の販売実績|主な相手先の販売実績|主要な販売先|主要な仕入先|主な販売先|主な仕入先|"
    r"主な相手先別の販売高|主要な販売先及び仕入先)")
STOP_PAT = re.compile(r"(経営者の視点|③|④|生産、受注の状況|該当事項はありません|議決権|株式数|従業員|資本金)")
# 表見出し語（相手先名に含まれない語）。行頭の見出し断片を名前から除去するのに使う
HEADER_WORD = re.compile(r"(?:割合|金額|構成比|販売高|相手先|前期|当期|連結会計年度|事業年度|実績)(?:（[^）]*）)?")
NUM_PAT = re.compile(r"(\d[\d,]*(?:\.\d+)?)(%|\s*%)")
AMT_PAT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,})(?!\s*%)")
AMOUNT_TOKEN = re.compile(r"(\d[\d,]*(?:\.\d+)?)")
UNIT_PAT = re.compile(r"(千円|百万円|億円|万円)")


def _num(x):
    try:
        return float(x.replace(",", ""))
    except ValueError:
        return None


def _clean_name(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_supply_sections(text: str):
    """有報テキストから販売先・仕入先の開示行を抽出する。

    返り値: list of {name, share_pct, amount, role, period}
      role: 'customer'（相手先＝当社の販売先＝当社が売り手）または 'supplier'（当社の仕入先＝相手先が売り手）
      period: 'current'（当期）または 'prior'（前期のみの行・フォールバック時）
    """
    lines = [to_ascii(l.rstrip()) for l in text.splitlines()]
    rows = []
    for i, line in enumerate(lines):
        if not HEADER_PAT.search(line):
            continue
        # セクション種別
        seg = lines[i:i + 8]
        seg_txt = " ".join(seg)
        # 仕入先セクションかどうか: 見出しまたは近傍に「仕入先」単語があり販売先を含まない
        head = line + " " + (lines[i + 1] if i + 1 < len(lines) else "")
        is_supplier = ("仕入先" in head) and ("販売先" not in head)
        unit_m = UNIT_PAT.search(seg_txt)
        unit = unit_m.group(1) if unit_m else None
        # 当期/前期ラベルの追跡（4829 形式: 期間を行ごとに区切る表）
        period = "current"
        pending_name = ""
        for j in range(i + 1, min(i + 70, len(lines))):
            l = lines[j]
            if STOP_PAT.search(l):
                break
            if "前連結会計年度" in l or "前事業年度" in l:
                period = "prior"
            if "当連結会計年度" in l or "当事業年度" in l:
                period = "current"
            shares = NUM_PAT.findall(l)
            if not shares:
                # % なし形式: 行全体の数値構造から (金額, 割合) を推定
                if re.search(r"[年月日]", l):
                    pending_name = ""
                    continue  # 日付・年月を含む行（役員経歴・期間ラベル等）は除外
                all_nums = [(m.start(), _num(m.group(1))) for m in AMOUNT_TOKEN.finditer(l)]
                all_nums = [(p, v) for p, v in all_nums if v is not None]
                if not all_nums:
                    if l.strip() and not l.strip().startswith("（") and not HEADER_WORD.search(l):
                        pending_name += l.strip()
                    continue
                vals = [v for _, v in all_nums]
                # 4数値 (前期金額, 前期割合, 当期金額, 当期割合) / 2数値 (金額, 割合)
                if len(vals) >= 4 and vals[1] < 100 and vals[3] < 100:
                    sh_prior, sh_cur, amt_prior, amt_cur = vals[1], vals[3], vals[0], vals[2]
                elif len(vals) >= 2 and vals[1] < 100:
                    sh_prior, sh_cur, amt_prior, amt_cur = None, vals[1], None, vals[0]
                elif len(vals) == 1 and vals[0] < 100:
                    sh_prior, sh_cur, amt_prior, amt_cur = None, vals[0], None, None
                else:
                    pending_name = ""
                    continue
            else:
                share_list = [float(s[0].replace(",", "")) for s in shares]
                amounts = [_num(a) for a in AMT_PAT.findall(l)]
                amounts = [a for a in amounts if a is not None]
                if len(share_list) >= 2:
                    sh_prior, sh_cur = share_list[0], share_list[1]
                    amt_cur = amounts[-1] if amounts else None
                    amt_prior = amounts[0] if len(amounts) >= 2 else None
                else:
                    sh_prior, sh_cur = None, share_list[0]
                    amt_prior, amt_cur = None, (amounts[0] if amounts else None)
            # 名前部分 = 行頭から最初の数字トークンまで
            first_num = re.search(r"\d", l)
            if first_num is None:
                continue
            raw_name = pending_name + l[:first_num.start()]
            pending_name = ""
            # 行頭に混入した表見出し語（「金額 割合…」等）を除去
            cuts = [m.end() for m in HEADER_WORD.finditer(raw_name)]
            if cuts:
                raw_name = raw_name[max(cuts):]
            name = _clean_name(raw_name)
            if not name or not name.replace(" ", ""):
                continue
            if re.search(r"(小計|合計|総計|総合計)$", name.strip()) or name.strip() in {"計"}:
                continue
            if (sh_cur is not None and sh_cur > 100) or (sh_cur is None and sh_prior is not None and sh_prior > 100):
                continue
            # 行内に前期・当期の両方がない場合は、直近の期間ラベル（前/当連結会計年度）で判定
            single = sh_prior is None
            row_period = "prior" if (single and period == "prior") else "current"
            if sh_cur is not None:
                rows.append({"name": name, "share_pct": sh_cur, "amount": amt_cur,
                             "unit": unit, "role": "supplier" if is_supplier else "customer",
                             "period": row_period})
            elif sh_prior is not None:
                rows.append({"name": name, "share_pct": sh_prior, "amount": amt_prior,
                             "unit": unit, "role": "supplier" if is_supplier else "customer",
                             "period": row_period})
    # 重複除去（近接する複数トリガで同じ行が2回取れることがある）
    seen, uniq = set(), []
    for r in rows:
        key = (r["name"], r["share_pct"], r["amount"], r["role"])
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", nargs="*", default=None, help="指定 ticker のみ処理")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    tickers = sorted({r[0] for r in con.execute(
        "SELECT DISTINCT id_value FROM id_map WHERE id_type='ticker'")})
    if args.only:
        tickers = [t for t in tickers if t in set(args.only)]
    if args.limit:
        tickers = tickers[:args.limit]
    con.close()

    docids = resolve_docids(tickers)
    os.makedirs(TEXT_DIR, exist_ok=True)
    jobs = [(t, docids[t]["doc_id"]) for t in tickers if docids.get(t, {}).get("doc_id")]
    print(f"fetching {len(jobs)} yuho PDFs (gBizINFO) ...", flush=True)

    out = {}
    n_ok = n_txt = 0
    with ThreadPoolExecutor(args.workers) as ex:
        for k, (ticker, doc_id, txt_path) in enumerate(ex.map(fetch_and_extract, jobs), 1):
            rec = {"doc_id": doc_id, "date": docids[ticker].get("date")}
            if txt_path and os.path.exists(txt_path):
                n_txt += 1
                text = open(txt_path, encoding="utf-8", errors="ignore").read()
                rows = parse_supply_sections(text)
                cust = [r for r in rows if r["role"] == "customer"]
                supp = [r for r in rows if r["role"] == "supplier"]
                if cust or supp:
                    n_ok += 1
                rec["customers"] = cust
                rec["suppliers"] = supp
            else:
                rec["customers"] = []
                rec["suppliers"] = []
                rec["error"] = "fetch_or_extract_failed"
            out[ticker] = rec
            if k % 200 == 0:
                print(f"  {k}/{len(jobs)} fetched, {n_txt} text, {n_ok} with disclosure", flush=True)

    json.dump(out, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_cust = sum(len(v.get("customers", [])) for v in out.values())
    n_supp = sum(len(v.get("suppliers", [])) for v in out.values())
    print(f"done: {len(out)} firms, {n_txt} text-extracted, {n_ok} with disclosure, "
          f"{n_cust} customer rows, {n_supp} supplier rows -> {OUT_PATH}")


if __name__ == "__main__":
    main()
