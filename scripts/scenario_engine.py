#!/usr/bin/env python3
"""What-if エンジン v1 — Layer F（企業）× Layer A（国×産業）統合伝播.

シナリオ:
  --scenario entity_failure --ticker 7203
  --scenario war_blockade --countries TW,CN --stop-rate 0.8
  --scenario chokepoint --route taiwan_strait --severity 0.5
  --scenario oil_price --multiplier 2.0
  --scenario port_closure --port "JP NGO" --severity 1.0

設計（docs/00_DATABASE_DESIGN.md §5）:
  - チャネル → 初期損失（企業ノード + 国×産業ノード）
  - Layer A: ICIO投入係数でLeontief型伝播（飽和付き）
  - Layer F: DebtRank式（各損失増分は各エッジを一度だけ流れる = 二重計上なし）
  - 会計整合（エッジ置換）: 企業に観測済み仕入エッジ（cost_share）がある場合、
    IO平均係数を置換し、残りにだけIO係数を適用。
    observed_cost_share + estimated残差 = 1 を強制。
  - 出力: 各社の損失率の分布（P50/P90/P99）、倒産確率。basis=observed_only/with_estimates
"""
import argparse, json, math, random, sqlite3, sys, datetime
from collections import defaultdict
import numpy as np

DB = "../db/cybermap.sqlite"
today = datetime.date.today().isoformat()

# ---------- 17業種(JPX) → ICIO 産業コード ----------
SECTOR2CI = {
    "食品": "C10T12", "医薬品": "C21", "情報通信・サービスその他": "J62_63",
    "運輸・物流": "H49", "小売": "G", "不動産": "L", "建設・資材": "F",
    "鉄鋼・非鉄": "C24", "エネルギー資源": "B07_08", "商社・卸売": "G",
    "金融（除く銀行）": "K", "素材・化学": "C20", "機械": "C28",
    "電機・精密": "C27", "自動車・輸送機": "C29", "電力・ガス": "D", "銀行": "K",
}
ENERGY_CIS = ("D", "C19", "B05_06", "B07_08", "B09")   # エネルギー供給源とみなすLayer Aノード
PASS_THROUGH = 0.5   # 価格上昇のコスト転嫁率（残りはマージン圧迫）

class Engine:
    def __init__(self):
        self.con = sqlite3.connect(DB)
        self.con.row_factory = sqlite3.Row
        self._load_firms()
        self._load_layerA()

    # ---------- データロード ----------
    def _load_firms(self):
        self.nodes = {r["company_id"]: dict(r) for r in self.con.execute(
            "SELECT * FROM company WHERE layer='F_jp'")}
        for r in self.con.execute("SELECT company_id, market_cap_jpy FROM market_snapshot"):
            if r["company_id"] in self.nodes and r["market_cap_jpy"]:
                self.nodes[r["company_id"]]["mcap"] = r["market_cap_jpy"]
        for r in self.con.execute(
                "SELECT company_id, revenue, equity, cash, employees, cogs FROM financials WHERE period='FY' AND source_tier=1"):
            if r["company_id"] in self.nodes:
                self.nodes[r["company_id"]].update(
                    revenue=r["revenue"], equity=r["equity"], cash=r["cash"],
                    employees=r["employees"], cogs=r["cogs"])
        # 17業種 → CI
        for cid, n in self.nodes.items():
            n["ci"] = "JPN_" + SECTOR2CI.get(n["sector_j33"], "S") if n["sector_j33"] != "-" else None
        # 企業グラフ（資本関係）+ 観測仕入エッジ（現在はEDINETの関係会社由来は僅少）
        self.edges = defaultdict(list)
        for r in self.con.execute("SELECT * FROM relation"):
            if r["src_id"] in self.nodes or r["dst_id"] in self.nodes:
                self.edges[r["src_id"]].append((r["dst_id"], r["relation_type"], r["confidence"], r["share_pct"]))
        # 観測済み cost_share エッジ（置換ルール用）: supply_buyer_of
        self.obs_supply = defaultdict(list)  # buyer -> [(seller_ci, cost_share)]
        for r in self.con.execute("SELECT * FROM relation WHERE relation_type='supply_buyer_of' AND cost_share IS NOT NULL"):
            self.obs_supply[r["src_id"]].append((r["dst_id"], r["cost_share"]))

    def _load_layerA(self):
        d = np.load("../data/icio2020_coeff.npz", allow_pickle=True)
        self.sellers = list(map(str, d["sellers"])); self.buyers = list(map(str, d["buyers"]))
        self.s_idx = {s: i for i, s in enumerate(self.sellers)}
        self.b_idx = {b: i for i, b in enumerate(self.buyers)}
        self.io_s, self.io_b, self.io_v = d["s"], d["b"], d["v"]
        # 高速アクセス用: buyer -> [(seller_idx, coeff)]
        self.io_by_buyer = defaultdict(list)
        for k in range(len(self.io_v)):
            self.io_by_buyer[self.buyers[self.io_b[k]]].append((self.io_s[k], float(self.io_v[k])))
        # JPN産業別: 輸出先別最終需要シェア（推定地理暴露の代替）
        self.exp_share = defaultdict(dict)   # (JPN_ind) -> {country: share}
        self.out_total = {}
        # 産業別エネルギー強度
        self.energy_int = {}
        for b, lst in self.io_by_buyer.items():
            if not b.startswith("JPN_"): continue
            tot = sum(v for _, v in lst)
            if tot > 0:
                self.energy_int[b] = sum(v for si, v in lst if self.sellers[si].split("_", 1)[1] in ENERGY_CIS)
        # 輸出シェア: JPN_ind → 各国最終需要列 (HFCE/GGFC/GFCF/INVNT等)
        self._load_export_shares()

    def _load_export_shares(self):
        """ICIOから JPN_ind → 国c 最終需要 のシェアを計算（観測geo_exposureが無い場合の推定暴露）。"""
        import csv
        # 生のICIO表をもう一度読む（最終需要列が必要なため）
        Z = "../raw/icio/2020_SML.csv"
        try:
            with open(Z, newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
                col_labels = header[1:]
                rows = []
                for rec in reader:
                    if rec[0].startswith("JPN_") and "_" in rec[0]:
                        rows.append((rec[0], [float(x) if x else 0.0 for x in rec[1:]]))
        except FileNotFoundError:
            print("WARNING: raw ICIO csv not found; export exposure unavailable", file=sys.stderr)
            return
        fd_cols = {}   # col idx -> (country, fd_type)
        for i, c in enumerate(col_labels):
            if "_" in c:
                country, tail = c.split("_", 1)
                if tail in ("HFCE", "GGFC", "GFCF", "INVNT", "DPABR", "NPISH", "P33"):
                    fd_cols[i] = (country, tail)
        for name, vals in rows:
            tot = sum(vals[i] for i in fd_cols) + 0  # 最終需要合計
            if tot <= 0: continue
            ctry_sum = defaultdict(float)
            for i, (ctry, _t) in fd_cols.items():
                ctry_sum[ctry] += vals[i]
            self.exp_share[name] = {c: v / tot for c, v in ctry_sum.items() if v / tot > 0.0002}

    # ---------- チャネル変換 ----------
    def shock_entity_failure(self, seed_id):
        return {seed_id: 1.0}, {}

    def shock_war_blockade(self, countries, stop_rate):
        """countries の生産・貿易が stop_rate で停止。
        Layer A: 当該国全産業の損失 = stop_rate
        Layer F: 日本企業は推定輸出暴露（ICIO由来・estimated）× stop_rate"""
        firm_shock, ci_shock = {}, {}
        for c in countries:
            for s in self.sellers:
                if s.startswith(c + "_"):
                    ci_shock[s] = stop_rate
        for cid, n in self.nodes.items():
            ci = n.get("ci")
            if not ci: continue
            share_c = sum(v for c, v in self.exp_share.get(ci, {}).items() if c in countries)
            if share_c > 0:
                firm_shock[cid] = share_c * stop_rate
        return firm_shock, ci_shock

    def shock_chokepoint(self, route_id, severity):
        """チョークポイント閉塞: 通過貿易のうち severity の割合が停止 + 迂回コスト。
        簡易実装: 全CI買い手ノードの輸入依存度 × route_share × severity を初期損失とし、
        迂回コスト分はエネルギー価格上昇と同型のコストショックとして加算。"""
        r = self.con.execute("SELECT * FROM shipping_route WHERE route_id=?", (route_id,)).fetchone()
        if not r: sys.exit(f"route {route_id} not found")
        cap = r["world_capacity_share"] * severity
        firm_shock, ci_shock = {}, {}
        for b, lst in self.io_by_buyer.items():
            # 輸入係数合計 × ルートシェア × severity
            imports = sum(v for si, v in lst if not self.sellers[si].split("_")[0] == b.split("_")[0])
            l = imports * cap
            if l > 0.005:
                ci_shock[b] = min(0.9, l)
        # 日本企業は産業ノード経由（下の伝播で処理）。追加コストは5%相当の一律コストショック
        cost = r["alt_route_cost_mult"] * severity * 0.05
        for b in list(ci_shock):
            ci_shock[b] = min(0.9, ci_shock[b] + cost * self.energy_int.get(b, 0))
        return {}, ci_shock

    def shock_commodity_price(self, commodity, multiplier):
        """エネルギー価格 ×multiplier → CI買い手のエネルギー強度 × (m-1) × 転嫁率"""
        firm_shock, ci_shock = {}, {}
        delta = (multiplier - 1.0) * PASS_THROUGH
        for b, e in self.energy_int.items():
            l = min(0.9, e * delta)
            if l > 0.003:
                ci_shock[b] = l
        return firm_shock, ci_shock

    def shock_port_closure(self, port_id, severity):
        r = self.con.execute("SELECT * FROM port WHERE port_id=?", (port_id,)).fetchone()
        if not r: sys.exit(f"port {port_id} not found")
        share = r["country_container_share"] * severity
        # 輸出・輸入の container share 分が一時停止 → 全日本企業に一律の貿易暴露損失
        firm_shock = {}
        for cid, n in self.nodes.items():
            ci = n.get("ci")
            if not ci: continue
            # 産業の輸出+輸入最終需要シェア（概算）× port share
            exports = sum(self.exp_share.get(ci, {}).values())
            l = min(0.9, (exports * 0.5 + 0.1) * share)
            if l > 0.003:
                firm_shock[cid] = l
        return firm_shock, {}

    # ---------- 会計整合（エッジ置換ルール） ----------
    def ci_shock_to_firm(self, cid, ci_shock, rng, basis):
        """企業の初期損失へのLayer Aショックの反映。
        置換ルール: 観測済み cost_share エッジがある供給元は観測値を採用し、
        残り (1-Σobs) にだけ IO平均ショックを適用 → 二重計上なし。"""
        n = self.nodes[cid]
        ci = n.get("ci")
        if not ci or ci not in ci_shock: return 0.0
        io_shock = ci_shock[ci]
        obs = self.obs_supply.get(cid, [])
        if not obs:
            return io_shock
        covered = sum(cs for _, cs in obs)
        residual = max(0.0, 1.0 - covered)
        s = 0.0
        for seller_id, cs in obs:
            seller_ci = self.nodes.get(seller_id, {}).get("ci")
            if seller_ci and seller_ci in ci_shock:
                s += cs * ci_shock[seller_ci]
        s += residual * io_shock
        return s

    # ---------- 伝播 ----------
    def propagate_firm(self, firm_loss, rng, n_rounds=10):
        """DebtRank式（増分は各エッジを一度だけ）。株主→被保有方向とその逆。"""
        loss = dict(firm_loss)
        h = dict(firm_loss)
        active = set(firm_loss)
        for _ in range(n_rounds):
            nxt = set()
            for i in list(active):
                hi = h.get(i, 0.0); h[i] = 0.0
                if hi <= 1e-9: continue
                for (j, rtype, conf, spct) in self.edges.get(i, []):
                    if j not in self.nodes: continue
                    dep = min(1.0, spct / 100.0) if spct is not None else rng.betavariate(1, 3)
                    p = conf * min(1.0, dep / 0.05)
                    if rng.random() > p: continue
                    s = dep * (0.5 if rtype == "ownership_parent_of" else 0.3)
                    add = s * hi * (1.0 - loss.get(j, 0.0))
                    if add > 1e-6:
                        loss[j] = loss.get(j, 0.0) + add
                        h[j] = h.get(j, 0.0) + add
                        nxt.add(j)
            active = nxt
        return loss

    def propagate_ci(self, ci_shock, n_rounds=8):
        """Layer A: Leontief型。買い手jの追加損失 = Σ_i coeff[i,j] × ΔL_i × (1-L_j)。"""
        loss = dict(ci_shock)
        h = dict(ci_shock)
        for _ in range(n_rounds):
            new_h = defaultdict(float)
            for i, hi in h.items():
                if hi <= 1e-9: continue
                # i の生産減 → i を買う全ノードに波及
                for b, lst in [(i, self.io_by_buyer.get(i, []))]:
                    pass
                # i は seller。i を使う buyers を引く: 逆引きが必要
                for bi, coeff in self._buyers_of(i):
                    add = coeff * hi * (1.0 - loss.get(bi, 0.0))
                    if add > 1e-6:
                        loss[bi] = loss.get(bi, 0.0) + add
                        new_h[bi] += add
            h = dict(new_h)
            if not h: break
        return loss

    def _buyers_of(self, seller_ci):
        si = self.s_idx.get(seller_ci)
        if si is None: return []
        out = []
        # io_by_buyer を seller->buyers に変換したキャッシュ
        if not hasattr(self, "_rev"):
            self._rev = defaultdict(list)
            for b, lst in self.io_by_buyer.items():
                for s2, v in lst:
                    self._rev[self.sellers[s2]].append((b, v))
        return self._rev.get(seller_ci, [])

    # ---------- メイン ----------
    def run(self, scenario, rng, iterations=300, **kw):
        all_results = defaultdict(list)
        for it in range(iterations):
            firm_shock, ci_shock = getattr(self, f"shock_{scenario}")(**kw) if False else self._shock(scenario, kw, rng)
            # Layer A 伝播
            ci_loss = self.propagate_ci(ci_shock) if ci_shock else {}
            # Layer A → Layer F（置換ルール付き）
            firm_loss = dict(firm_shock)
            for cid in self.nodes:
                l = self.ci_shock_to_firm(cid, ci_loss, rng, None)
                if l > 0:
                    firm_loss[cid] = firm_loss.get(cid, 0.0) + l
                    firm_loss[cid] = min(1.0, firm_loss[cid])
            # Layer F 伝播
            firm_loss = self.propagate_firm(firm_loss, rng)
            # 倒産判定（財務バッファ）→ 二次伝播は省略（v1）
            for cid, l in firm_loss.items():
                all_results[cid].append(min(1.0, l))
        return all_results

    def _shock(self, scenario, kw, rng):
        # モンテカルロ: stop_rate / severity / multiplier に不確実性を付加
        kw2 = dict(kw)
        if "stop_rate" in kw2:
            sr = min(0.99, max(0.01, kw["stop_rate"]))
            kw2["stop_rate"] = rng.betavariate(sr * 10, (1 - sr) * 10)
        if "severity" in kw2:
            sv = min(0.99, max(0.01, kw["severity"]))
            kw2["severity"] = rng.betavariate(sv * 10, (1 - sv) * 10)
        if "multiplier" in kw2:
            kw2["multiplier"] = max(1.0, kw["multiplier"] * rng.gauss(1.0, 0.1))
        fn = {"entity_failure": self.shock_entity_failure,
              "war_blockade": self.shock_war_blockade,
              "chokepoint": self.shock_chokepoint,
              "oil_price": self.shock_commodity_price,
              "port_closure": self.shock_port_closure}[scenario]
        return fn(**kw2)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True,
                    choices=["entity_failure", "war_blockade", "chokepoint", "oil_price", "port_closure"])
    ap.add_argument("--ticker"); ap.add_argument("--countries"); ap.add_argument("--stop-rate", type=float, default=0.8)
    ap.add_argument("--route"); ap.add_argument("--severity", type=float, default=0.5)
    ap.add_argument("--multiplier", type=float, default=2.0)
    ap.add_argument("--port"); ap.add_argument("--iterations", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--out")
    args = ap.parse_args()
    eng = Engine()
    rng = random.Random(args.seed)
    kw = {}
    if args.scenario == "entity_failure":
        if not args.ticker: ap.error("--ticker required")
        r = eng.con.execute("SELECT company_id FROM id_map WHERE id_type='ticker' AND id_value=?", (args.ticker,)).fetchone()
        if not r: sys.exit("ticker not found")
        kw = dict(seed_id=r["company_id"])
    elif args.scenario == "war_blockade":
        if not args.countries: ap.error("--countries required (comma ISO3)")
        kw = dict(countries=args.countries.split(","), stop_rate=args.stop_rate)
    elif args.scenario == "chokepoint":
        kw = dict(route_id=args.route or "taiwan_strait", severity=args.severity)
    elif args.scenario == "oil_price":
        kw = dict(commodity="brent", multiplier=args.multiplier)
    elif args.scenario == "port_closure":
        kw = dict(port_id=args.port or "JP NGO", severity=args.severity)

    print(f"scenario: {args.scenario} {kw} iterations={args.iterations}", flush=True)
    res = eng.run(args.scenario, rng, iterations=args.iterations, **kw)
    rows = []
    for cid, losses in res.items():
        n = eng.nodes[cid]
        ls = sorted(losses)
        rows.append({
            "name": n["legal_name"], "ticker": eng.con.execute(
                "SELECT id_value FROM id_map WHERE id_type='ticker' AND company_id=?", (cid,)).fetchone(),
            "sector": n["sector_j33"], "mcap": n.get("mcap"),
            "direct": ls[0], "mean": sum(ls) / len(ls),
            "p50": ls[len(ls) // 2], "p90": ls[int(0.9 * len(ls))],
            "affected_prob": sum(1 for l in ls if l > 0.01) / len(ls),
        })
    for r in rows:
        if isinstance(r["ticker"], sqlite3.Row): r["ticker"] = r["ticker"][0]
    rows.sort(key=lambda r: -(r["mean"] * (r["mcap"] or 0)))
    print(f"\n{'企業':<28} {'業種':<12} {'平均損失':>8} {'P90':>8} {'巻き込まれ':>8}")
    for r in rows[:args.top]:
        print(f"{r['name'][:26]:<28} {str(r['sector'])[:10]:<12} {r['mean']*100:7.2f}% {r['p90']*100:7.2f}% {r['affected_prob']*100:7.1f}%")
    out = {"scenario": args.scenario, "params": {k: str(v) for k, v in kw.items()},
           "model_version": "v1.0-layered", "iterations": args.iterations, "results": rows}
    path = args.out or f"../analysis/scenario_{args.scenario}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(f"\n-> {path}")

if __name__ == "__main__":
    main()
