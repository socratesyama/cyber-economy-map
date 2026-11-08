#!/usr/bin/env python3
"""What-if エンジン プロトタイプ（スモークテスト）.

現状の cybermap.sqlite (日本上場企業 + 資本関係エッジ + 市場時価総額) の上で
「特定企業の倒産」シナリオの損失伝播をモンテカルロで走らせる。
※ 資本関係エッジは dependency_status='observed_binary'（持分比率は未観測）のため、
   依存度は観測値ではなく「デモ用の幅広い事前分布」からサンプルする。
   本番では EDINET の関係会社データで share_pct を観測値に置き換える。
   → 出力はエンジン動作確認用であって、科学的な予測ではない。

使い方:
  python3 simulate_demo.py --company トヨタ   (名称部分一致)
  python3 simulate_demo.py --ticker 7203
"""
import argparse, json, math, random, sqlite3, statistics, sys
from collections import defaultdict

DB = "../db/cybermap.sqlite"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

def load_graph():
    nodes = {r["company_id"]: dict(r) for r in con.execute(
        "SELECT c.*, m.id_value AS ticker FROM company c LEFT JOIN id_map m ON m.company_id=c.company_id AND m.id_type='ticker'")}
    # 市場時価総額をノードに付与
    for r in con.execute("SELECT company_id, market_cap_jpy FROM market_snapshot"):
        if r["company_id"] in nodes and r["market_cap_jpy"]:
            nodes[r["company_id"]]["mcap"] = r["market_cap_jpy"]
    edges = defaultdict(list)  # src_id -> [(dst_id, type, confidence)]
    for r in con.execute("SELECT * FROM relation WHERE relation_type='ownership_parent_of'"):
        edges[r["src_id"]].append((r["dst_id"], r["relation_type"], r["confidence"]))
        # 資本の逆方向（子→親は親の損失が子に波及する意味で双方向に弱く伝播）
        edges[r["dst_id"]].append((r["src_id"], "ownership_child_of", r["confidence"] * 0.5))
    return nodes, edges

def propagate(nodes, edges, seed_id, rng, n_iter=1000):
    """DebtRank風カスケード + モンテカルロ。loss率の分布を返す。"""
    results = defaultdict(list)
    for it in range(n_iter):
        loss = {seed_id: 1.0}
        active = {seed_id}
        round_no = 0
        while active and round_no < 10:
            nxt = set()
            for i in list(active):
                for (j, rtype, conf) in edges[i]:
                    # observed_binary: 依存度は未観測 → デモ用事前分布 Beta(1,3)
                    dep = rng.betavariate(1, 3)
                    p = conf * min(1, dep / 0.05)
                    if rng.random() > p: continue
                    if rtype == "ownership_parent_of":
                        s = dep * 0.5          # 親の損失が子の価値を毀損
                    else:
                        s = dep * 0.3          # 子の損失が親に及ぶ（持分経由・弱め）
                    new = loss.get(j, 0.0) + s * loss[i] * (1 - loss.get(j, 0.0))
                    if new > loss.get(j, 0.0) + 1e-6:
                        loss[j] = min(1.0, new)
                        nxt.add(j)
            active = nxt
            round_no += 1
        for cid, l in loss.items():
            results[cid].append(l)
    return results

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker"); ap.add_argument("--company")
    ap.add_argument("--iterations", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    if not (args.ticker or args.company):
        ap.error("--ticker か --company を指定してください")
    nodes, edges = load_graph()
    seed_id = None
    if args.ticker:
        r = con.execute("SELECT company_id FROM id_map WHERE id_type='ticker' AND id_value=?", (args.ticker,)).fetchone()
        seed_id = r["company_id"] if r else None
    else:
        for n in nodes.values():
            if n["legal_name"] and args.company in n["legal_name"]:
                seed_id = n["company_id"]; break
    if not seed_id: sys.exit("対象企業が見つかりません")
    seed = nodes[seed_id]
    print(f"シナリオ: {seed['legal_name']} ({seed.get('ticker','?')}) 倒産")
    print(f"時価総額: {seed.get('mcap', 0)/1e12:.1f} 兆円\n")
    rng = random.Random(args.seed)
    res = propagate(nodes, edges, seed_id, rng, args.iterations)
    rows = []
    for cid, losses in res.items():
        if cid == seed_id: continue
        n = nodes[cid]
        rows.append({
            "name": n["legal_name"], "ticker": n.get("ticker"),
            "layer": n["layer"],
            "mean_loss": statistics.mean(losses),
            "p90": sorted(losses)[int(0.9 * len(losses))],
            "affected_prob": sum(1 for l in losses if l > 0.01) / len(losses),
        })
    ticker2id = {n["ticker"]: n["company_id"] for n in nodes.values() if n.get("ticker")}
    def key(r):
        cid = ticker2id.get(r["ticker"]) if r["ticker"] else None
        m = nodes.get(cid, {}).get("mcap", 0) or 0
        return -(r["mean_loss"] * m)   # 期待損失額（率×時価総額）順
    rows.sort(key=key)
    print(f"{'企業':<30} {'層':<8} {'平均損失率':>8} {'P90':>8} {'巻き込まれ確率':>10}")
    for r in rows[:args.top]:
        print(f"{r['name'][:28]:<30} {r['layer']:<8} {r['mean_loss']*100:7.2f}% {r['p90']*100:7.2f}% {r['affected_prob']*100:9.1f}%")
    out = {"seed": seed["legal_name"], "ticker": seed.get("ticker"),
           "model_version": "v0.1-demo", "iterations": args.iterations, "results": rows}
    with open("../analysis/demo_entity_failure.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n-> analysis/demo_entity_failure.json に保存 (basis: demo — 観測値ではなく事前分布使用)")

if __name__ == "__main__":
    main()
