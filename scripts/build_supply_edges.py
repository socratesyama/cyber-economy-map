#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_supply_edges.py の成果物（data/supply_edges_raw.json）を F_jp 企業に名前照合し、
db/cybermap.sqlite の relation テーブルへ supply_buyer_of エッジとして投入する。

エッジの方向: src = 売り手（仕入先・サプライヤー）, dst = 買い手（顧客）
  - 顧客開示（有報「主要な販売先」）: src=開示企業, dst=相手先
  - 仕入先開示（有報「主要な仕入先」）: src=相手先, dst=開示企業

各エッジの数量:
  - revenue_share: 売り手の総販売高に占める買い手向け販売の割合（有報開示値）
  - amount: 買い手向け販売金額（JPY。単位不明時は share × 売り手売上高で推計、extraction に記録）
  - cost_share: 買い手の COGS に占める仕入額の割合 = amount / buyer.cogs（エンジンの伝播係数の基礎）

照合: NFKC 正規化 + 法人形態接尾辞（株式会社等）除去後の完全一致を
company.legal_name / name_ja / short_name / company_alias に対して行う。

使い方:
  python3 scripts/build_supply_edges.py [--dry-run]
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from scenario_engine import DB  # noqa: E402

RAW_PATH = os.path.join(ROOT, "data", "supply_edges_raw.json")
OUT_PATH = os.path.join(ROOT, "data", "supply_edges.json")

UNIT_MULT = {"千円": 1e3, "百万円": 1e6, "億円": 1e8, "万円": 1e4, None: None}
LEGAL_SUFFIXES = ["株式会社", "㈱", "㈲", "有限会社", "合同会社", "（株）", "(株)",
                  "ホールディングス", "ホ\u30fc\u30eb\u30c7\u30a3\u30f3\u30b0\u30b9"]


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    for t in LEGAL_SUFFIXES:
        s = s.replace(t, "")
    return re.sub(r"\s+", "", s)


# 前方一致フォールバック用: 候補名の前後が語境界（空白・括弧・句読点等）であることを要求
_BOUND = r"[\s()（）、。.,/・\"'“”]"


def build_substring_candidates(con):
    """部分一致フォールバック用の候補リスト（正規化名 → cid、長い順）"""
    cands, seen = [], set()
    for layer in ("F_jp", "F_border"):
        for cid, *names in con.execute(
                "SELECT company_id, legal_name, name_ja, short_name FROM company WHERE layer=?", (layer,)):
            for n in names:
                if n:
                    nn = norm_name(n)
                    if len(nn) >= 5 and nn not in seen:
                        seen.add(nn)
                        cands.append((nn, cid))
    cands.sort(key=lambda x: -len(x[0]))
    return cands


def fuzzy_lookup(raw_name: str, cands):
    """折り返し等で前後にノイズが混入した行から企業名を境界チェック付きで発見する。
    完全一致しなかった行のみに使う（精度より再現率の補助）。"""
    nm = unicodedata.normalize("NFKC", raw_name or "")
    for nn, cid in cands:
        if nn not in nm:
            continue
        start = nm.find(nn)
        before_ok = start == 0 or re.match(_BOUND, nm[start - 1])
        after_ok = start + len(nn) == len(nm) or re.match(_BOUND, nm[start + len(nn)])
        if before_ok and after_ok:
            return cid
    return None


def build_name_index(con):
    """正規化名称 → company_id（F_jp）の索引。F_border（未上場の親会社等）も候補に含め、
    F_jp を優先する。"""
    idx, border = {}, {}
    for layer, target in (("F_jp", idx), ("F_border", border)):
        for cid, *names in con.execute(
                "SELECT company_id, legal_name, name_ja, short_name FROM company WHERE layer=?", (layer,)):
            for n in names:
                if n:
                    target.setdefault(norm_name(n), cid)
    for alias, cid in con.execute("SELECT alias, company_id FROM company_alias"):
        row = con.execute("SELECT layer FROM company WHERE company_id=?", (cid,)).fetchone()
        if row and row[0] in ("F_jp", "F_border"):
            target = idx if row[0] == "F_jp" else border
            target.setdefault(norm_name(alias), cid)
    idx.update(border)  # F_jp 優先（同名は F_jp が残る）
    return idx


def build_ticker_index(con):
    """ticker → company_id"""
    idx = {}
    for t, cid in con.execute(
            "SELECT id_value, company_id FROM id_map WHERE id_type='ticker'"):
        row = con.execute("SELECT layer FROM company WHERE company_id=?", (cid,)).fetchone()
        if row and row[0] == "F_jp":
            idx.setdefault(t, cid)
    return idx


def latest_financials(con):
    """company_id → 最新の revenue, cogs"""
    fin = {}
    for cid, fy, rev, cogs in con.execute(
            "SELECT company_id, fiscal_year, revenue, cogs FROM financials "
            "WHERE period='FY' ORDER BY company_id, fiscal_year"):
        if cid not in fin or fy > fin[cid][0]:
            fin[cid] = (fy, rev, cogs)
    return {cid: {"fiscal_year": v[0], "revenue": v[1], "cogs": v[2]} for cid, v in fin.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw = json.load(open(RAW_PATH, encoding="utf-8"))
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    name_idx = build_name_index(con)
    ticker_idx = build_ticker_index(con)
    fin = latest_financials(con)
    fuzzy_cands = build_substring_candidates(con)

    # (src, dst) -> best row
    edges = {}
    stats = defaultdict(int)

    def add_edge(seller_cid, buyer_cid, row, doc_id, date, disclosed_by):
        nonlocal edges
        key = (seller_cid, buyer_cid)
        share = row["share_pct"]
        unit_mult = UNIT_MULT.get(row.get("unit"))
        amount = None
        if row.get("amount") is not None and unit_mult is not None:
            amount = row["amount"] * unit_mult
        amount_estimated = amount is None
        if amount is None:
            # 単位不明のときは share × 売り手売上高で推計
            rev = fin.get(seller_cid, {}).get("revenue")
            if rev and share:
                amount = share / 100.0 * rev
        cost_share = None
        cogs = fin.get(buyer_cid, {}).get("cogs")
        if amount and cogs:
            if amount > cogs:
                # 買い手のCOGS全体を超える仕入は構造的に不可能（誤解析・資本関係表の混入等）→ 除外
                stats["dropped_amount_gt_cogs"] += 1
                return
            cost_share = min(1.0, amount / cogs)  # 代理店経由等で100%超は1.0に丸める
        # 開示の一貫性チェック: amount ≈ share × 売り手売上高（2.5倍以内）
        consistent = True
        if amount and not amount_estimated:
            srev = fin.get(seller_cid, {}).get("revenue")
            if srev and share:
                ratio = amount / (share / 100.0 * srev)
                if not (0.4 <= ratio <= 2.5):
                    consistent = False
        conf = 0.75 if fuzzy else 0.9
        if not consistent:
            conf *= 0.5
        if row.get("period") == "prior":
            conf -= 0.1
        rec = {
            "src": seller_cid, "dst": buyer_cid,
            "revenue_share": round(share / 100.0, 4),
            "amount": round(amount, 0) if amount else None,
            "amount_estimated": amount_estimated,
            "cost_share": round(cost_share, 4) if cost_share is not None else None,
            "confidence": round(conf, 2),
            "doc_id": doc_id, "as_of": date, "disclosed_by": disclosed_by,
            "consistent": consistent,
        }
        prev = edges.get(key)
        if prev is None:
            edges[key] = rec
        else:
            # 同一ペアの複数開示: 顧客側開示優先、次に当期・整合性・share の大きい方
            def rank(r):
                return (r["disclosed_by"] == "customer", r.get("period") == "current",
                        r["consistent"], r["revenue_share"])
            if rank(rec) > rank(prev):
                # 両側開示で数値が概ね一致すれば信頼度を上げる
                if (prev["revenue_share"] and rec["revenue_share"]
                        and 0.5 <= rec["revenue_share"] / prev["revenue_share"] <= 2.0):
                    rec["confidence"] = min(0.95, rec["confidence"] + 0.05)
                edges[key] = rec

    for ticker, rec in sorted(raw.items()):
        seller_cid = ticker_idx.get(ticker)
        if not seller_cid:
            stats["seller_ticker_unmatched"] += 1
            continue
        doc_id, date = rec.get("doc_id"), rec.get("date")
        for row in rec.get("customers", []):
            if row.get("period") != "current" and row.get("share_pct", 0) < 5:
                continue  # 前期のみの行は大きな依存のみ採用
            if row["share_pct"] < 1.0:
                stats["dropped_lt_1pct"] += 1
                continue
            buyer_cid = name_idx.get(norm_name(row["name"]))
            fuzzy = False
            if not buyer_cid and row.get("amount") is not None:
                # 折り返し行のフォールバック: 境界チェック付き部分一致（信頼度を下げる）
                buyer_cid = fuzzy_lookup(row["name"], fuzzy_cands)
                fuzzy = bool(buyer_cid)
            if not buyer_cid:
                stats["customer_name_unmatched"] += 1
                continue
            if buyer_cid == seller_cid:
                stats["self_edge"] += 1
                continue
            stats["customer_edges"] += 1
            add_edge(seller_cid, buyer_cid, row, doc_id, date, "customer")
        for row in rec.get("suppliers", []):
            if row.get("period") != "current" and row.get("share_pct", 0) < 5:
                continue
            if row["share_pct"] < 1.0:
                stats["dropped_lt_1pct"] += 1
                continue
            seller2 = name_idx.get(norm_name(row["name"]))
            if not seller2 and row.get("amount") is not None:
                seller2 = fuzzy_lookup(row["name"], fuzzy_cands)
            if not seller2:
                stats["supplier_name_unmatched"] += 1
                continue
            if seller2 == seller_cid:
                stats["self_edge"] += 1
                continue
            stats["supplier_edges"] += 1
            add_edge(seller2, seller_cid, row, doc_id, date, "supplier")

    n = len(edges)
    n_cost = sum(1 for e in edges.values() if e["cost_share"] is not None)
    print(f"edges: {n} (cost_share computed: {n_cost})")
    print("stats:", dict(stats))

    # 疎通確認: 主要エッジを表示
    print("\ntop edges by cost_share:")
    for e in sorted(edges.values(), key=lambda e: -(e["cost_share"] or 0))[:15]:
        nm = lambda cid: con.execute("SELECT short_name FROM company WHERE company_id=?", (cid,)).fetchone()[0]
        print(f"  {nm(e['src'])} -> {nm(e['dst'])}: rev_share={e['revenue_share']:.3f} "
              f"cost_share={e['cost_share']:.4f} amt={e['amount']/1e8:.0f}億円 conf={e['confidence']}")

    if args.dry_run:
        print("\n(dry-run: DB は更新しません)")
        return

    con.execute("DELETE FROM relation WHERE relation_type='supply_buyer_of'")
    for (src, dst), e in sorted(edges.items()):
        con.execute(
            "INSERT INTO relation (edge_id, src_id, dst_id, relation_type, revenue_share, "
            "cost_share, amount, currency, dependency_status, as_of, source_tier, "
            "source_ref, extraction, confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"supply:{src}:{dst}", src, dst, "supply_buyer_of", e["revenue_share"],
             e["cost_share"], e["amount"], "JPY", "observed_value", e["as_of"] or "",
             1, f"edinet:{e['doc_id']} (gBizINFO)",
             f"yuho_parse_v1 estimated_amount={e['amount_estimated']}", e["confidence"]))
    con.commit()
    print(f"\ninserted {n} supply_buyer_of edges into relation")

    # 人間可読な成果物
    def cname(cid):
        r = con.execute("SELECT short_name FROM company WHERE company_id=?", (cid,)).fetchone()
        return r[0] if r else cid
    out = []
    for e in sorted(edges.values(), key=lambda e: -(e["cost_share"] or 0)):
        out.append({**e, "seller": cname(e["src"]), "buyer": cname(e["dst"])})
    json.dump(out, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
