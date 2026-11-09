#!/usr/bin/env python3
"""ビジュアライゼーション用JSONエクスポート — Three.js 3Dネットワークビューア用.

出力: viz/data/graph.json
  nodes: company_id, name, sector, mcap, ticker, layer
  edges: src, dst, type (ownership_parent_of / supply_buyer_of), share_pct, confidence
  layout: 3D座標（業種クラスタ + 力学的レイアウト近似）
"""
import json, sqlite3, math, random
from collections import defaultdict

DB = "../db/cybermap.sqlite"
OUT = "../viz/data/graph.json"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# --- ノード ---
nodes = []
tickers = {r["company_id"]: r["id_value"] for r in con.execute("SELECT company_id, id_value FROM id_map WHERE id_type='ticker'")}
mcaps = {r["company_id"]: r["market_cap_jpy"] for r in con.execute("SELECT company_id, market_cap_jpy FROM market_snapshot") if r["market_cap_jpy"]}

for r in con.execute("SELECT * FROM company WHERE layer='F_jp' AND status='active'"):
    cid = r["company_id"]
    sector = r["sector_j33"]
    if not sector or sector == "-":
        sector = "その他"
    nodes.append({
        "id": cid,
        "name": r["short_name"] or r["legal_name"],
        "sector": sector,
        "ticker": tickers.get(cid, ""),
        "mcap": mcaps.get(cid, 0),
    })

# --- エッジ（資本関係 + 供給関係） ---
edges = []
for r in con.execute("SELECT * FROM relation WHERE relation_type IN ('ownership_parent_of','supply_buyer_of')"):
    sp = r["share_pct"]
    edges.append({
        "src": r["src_id"],
        "dst": r["dst_id"],
        "type": r["relation_type"],
        "share": sp if sp is not None else None,
        "conf": r["confidence"],
    })

# --- 3Dレイアウト: 業種ごとに球状クラスタ配置 + クラスタ内でランダム散布 ---
SECTOR_COLORS = {
    "食品": "#8bc34a", "医薬品": "#e91e63", "情報通信・サービスその他": "#3f51b5",
    "運輸・物流": "#ff9800", "小売": "#fdd835", "不動産": "#795548",
    "建設・資材": "#607d8b", "鉄鋼・非鉄": "#9e9e9e", "エネルギー資源": "#f44336",
    "商社・卸売": "#ff5722", "金融（除く銀行）": "#00bcd4", "素材・化学": "#673ab7",
    "機械": "#009688", "電機・精密": "#2196f3", "自動車・輸送機": "#03a9f4",
    "電力・ガス": "#ffc107", "銀行": "#4caf50", "その他": "#616161",
}

rng = random.Random(42)
sectors = sorted(set(n["sector"] for n in nodes))
n_sec = len(sectors)
# 各業種を球面上に配置
sector_centers = {}
for i, s in enumerate(sectors):
    phi = math.acos(1 - 2 * (i + 0.5) / n_sec)
    theta = math.pi * (1 + math.sqrt(5)) * (i + 0.5)
    R = 80.0
    sector_centers[s] = (R * math.sin(phi) * math.cos(theta),
                         R * math.cos(phi),
                         R * math.sin(phi) * math.sin(theta))

for n in nodes:
    cx, cy, cz = sector_centers[n["sector"]]
    # クラスタ内で球状に散布（半径はクラスタサイズ依存、簡易的に固定）
    # クラスタ半径を小さくして、ノードが重ならないようにする
    r_in = 12.0 * (0.3 + rng.random() * 0.7)
    u, v = rng.random(), rng.random()
    theta_in = 2 * math.pi * u
    phi_in = math.acos(2 * v - 1)
    n["x"] = round(cx + r_in * math.sin(phi_in) * math.cos(theta_in), 2)
    n["y"] = round(cy + r_in * math.cos(phi_in), 2)
    n["z"] = round(cz + r_in * math.sin(phi_in) * math.sin(theta_in), 2)
    n["color"] = SECTOR_COLORS.get(n["sector"], "#888888")
    # mcap -> size (log scale, 1.5-5.0) — より小さく、上限付き
    m = n["mcap"]
    raw_size = 1.5 + (1.5 * math.log10(max(m, 1e9) / 1e9) if m > 0 else 0)
    n["size"] = round(min(5.0, max(1.5, raw_size)), 2)

out = {
    "meta": {
        "generated": "2026-11-08",
        "nodes": len(nodes),
        "edges": len(edges),
        "source": "cyber-economy-map DB",
    },
    "sector_colors": SECTOR_COLORS,
    "nodes": nodes,
    "edges": edges,
}

import os
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"nodes={len(nodes)} edges={len(edges)} -> {OUT}")
