#!/usr/bin/env python3
"""ARCHIVED legacy prototype — do not use as the current RIPPLE engine.

This file and its previous assumptions/outputs are preserved for code-history
reproducibility. It is not used by the RIPPLE UI. Its firm-edge, monetary-loss
and calibration logic is not a validated forecast or calibrated probability
model. The active workbench logic is in ``viz/src/engine/`` and deliberately
withholds company-loss and default-probability conclusions that its data cannot
support.

Historical what-if prototype v2 — Layer F（企業）× Layer A（国×産業）統合伝播.

シナリオ:
  --scenario entity_failure --ticker 7203
  --scenario war_blockade --countries TWN,CN --stop-rate 0.8
  --scenario chokepoint --route taiwan_strait --severity 0.5
  --scenario oil_price --multiplier 2.0
  --scenario port_closure --port "JP NGO" --severity 1.0

v2 の変更点:
  - パスをスクリプト位置基準の絶対パスに修正（どこからでも実行可能）
  - Layer A 伝播を scipy.sparse でベクトル化（約100倍高速化）
  - Layer F へのショック反映もベクトル化
  - --export-viz でビューア用 JSON を一括生成

設計（docs/00_DATABASE_DESIGN.md §5）:
  - チャネル → 初期損失（企業ノード + 国×産業ノード）
  - Layer A: ICIO投入係数でLeontief型伝播（飽和付き）
  - Layer F: DebtRank式（各損失増分は各エッジを一度だけ流れる = 二重計上なし）
  - 会計整合（エッジ置換）: 企業に観測済み仕入エッジ（cost_share）がある場合、
    IO平均係数を置換し、残りにだけIO係数を適用。
  - 出力: 各社の損失率の分布（P50/P90）、巻き込まれ確率
"""
if __name__ == "__main__":
    raise SystemExit(
        "This is an archived, unvalidated prototype and its CLI is disabled. "
        "It must not be interpreted as a corporate loss, bankruptcy, or economic forecast. "
        "See the current scope and limitations in the repository-root README.md."
    )

import argparse, json, random, sqlite3, sys, datetime
from collections import defaultdict
from pathlib import Path

import numpy as np
import scipy.sparse as sp

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "db" / "cybermap.sqlite"
NPZ = BASE / "data" / "icio2020_coeff.npz"
ICIO_CSV = BASE / "raw" / "icio" / "2020_SML.csv"
VIZ_SCENARIOS = BASE / "viz" / "data" / "scenarios.json"
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
PROP_DAMP = 0.4      # Layer A伝播の減衰係数（代替調達・在庫・価格調整を表す）


class Engine:
    def __init__(self):
        self.con = sqlite3.connect(str(DB))
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

        # --- ベクトル化用の固定配列 ---
        self.firm_ids = list(self.nodes.keys())          # firm index -> cid
        self.firm_idx = {c: i for i, c in enumerate(self.firm_ids)}
        self.firm_mcap = np.array([self.nodes[c].get("mcap") or 0.0 for c in self.firm_ids])

        # 企業グラフ（資本関係）: エッジ配列化
        edges = []   # (src_firm_idx, dst_firm_idx, conf, spct_or_None, factor)
        for r in self.con.execute("SELECT * FROM relation"):
            i, j = self.firm_idx.get(r["src_id"]), self.firm_idx.get(r["dst_id"])
            if i is None or j is None: continue
            factor = 0.5 if r["relation_type"] == "ownership_parent_of" else 0.3
            edges.append((i, j, r["confidence"] or 0.5, r["share_pct"], factor))
        self.e_src = np.array([e[0] for e in edges], dtype=np.int32)
        self.e_dst = np.array([e[1] for e in edges], dtype=np.int32)
        self.e_conf = np.array([e[2] for e in edges], dtype=np.float64)
        self.e_spct = np.array([np.nan if e[3] is None else e[3] for e in edges], dtype=np.float64)
        self.e_factor = np.array([e[4] for e in edges], dtype=np.float64)
        self.e_rand_dep = np.isnan(self.e_spct)     # share_pct 未観測 → 毎回ランダム
        self.e_dep_obs = np.where(self.e_rand_dep, 0.5, np.minimum(1.0, self.e_spct / 100.0))

        # 観測仕入エッジ（置換ルール用）: ほぼ存在しないが互換性のため保持
        self.obs_supply = defaultdict(list)
        for r in self.con.execute("SELECT * FROM relation WHERE relation_type='supply_buyer_of' AND cost_share IS NOT NULL"):
            self.obs_supply[r["src_id"]].append((r["dst_id"], r["cost_share"]))

        # ティッカー（結果表示用に一括ロード）
        self.tickers = {}
        for r in self.con.execute("SELECT company_id, id_value FROM id_map WHERE id_type='ticker'"):
            self.tickers[r["company_id"]] = r["id_value"]

    def _load_layerA(self):
        d = np.load(NPZ, allow_pickle=True)
        sellers = list(map(str, d["sellers"])); buyers = list(map(str, d["buyers"]))
        s_arr, b_arr, v_arr = d["s"], d["b"], d["v"]

        # CIノードインデックス（sellers ∪ buyers）
        ci_names = sorted(set(sellers) | set(buyers))
        self.ci_idx = {c: i for i, c in enumerate(ci_names)}
        self.ci_names = ci_names
        n_ci = len(ci_names)

        # 係数行列 M[buyer, seller] = coeff（buyerの投入に占めるsellerの割合）
        rows = np.array([self.ci_idx[buyers[b_arr[k]]] for k in range(len(v_arr))], dtype=np.int32)
        cols = np.array([self.ci_idx[sellers[s_arr[k]]] for k in range(len(v_arr))], dtype=np.int32)
        self.M = sp.csr_matrix((v_arr, (rows, cols)), shape=(n_ci, n_ci))

        # 産業別エネルギー強度（JPNノード）: JPN_ind の投入中エネルギー比率
        energy_mask = np.zeros(n_ci, dtype=bool)
        for c in ci_names:
            ind = c.split("_", 1)[1] if "_" in c else ""
            if ind in ENERGY_CIS: energy_mask[self.ci_idx[c]] = True
        col_energy = energy_mask[cols]          # seller がエネルギー
        is_jpn_row = np.array([b.startswith("JPN_") for b in ci_names])
        num = np.zeros(n_ci); den = np.zeros(n_ci)
        np.add.at(num, rows[col_energy], v_arr[col_energy])
        np.add.at(den, rows, v_arr)
        self.energy_int = np.where(den > 0, num / np.maximum(den, 1e-12), 0.0)
        self.energy_int[~is_jpn_row] = 0.0

        # 輸入係数合計（chokepoint用）: seller国 != buyer国 の係数和
        seller_ctry = np.array([s.split("_")[0] for s in ci_names])
        buyer_ctry = np.array([b.split("_")[0] for b in ci_names])
        cross = seller_ctry[cols] != buyer_ctry[rows]
        imports = np.zeros(n_ci)
        np.add.at(imports, rows[cross], v_arr[cross])
        self.import_share = imports

        # JPN産業の輸出先別最終需要シェア（geo暴露の推定）
        self.exp_share = {}
        self._load_export_shares()

        # 企業 → CIインデックス配列
        self.firm_ci = np.array(
            [self.ci_idx[self.nodes[c]["ci"]] if self.nodes[c].get("ci") in self.ci_idx else -1
             for c in self.firm_ids], dtype=np.int32)

    def _load_export_shares(self):
        """ICIO最終需要列から JPN_ind → 国c の輸出シェアを計算."""
        import csv
        try:
            with open(ICIO_CSV, newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
                col_labels = header[1:]
                fd_cols = {}
                for i, c in enumerate(col_labels):
                    if "_" in c:
                        country, tail = c.split("_", 1)
                        if tail in ("HFCE", "GGFC", "GFCF", "INVNT", "DPABR", "NPISH", "P33"):
                            fd_cols[i] = country
                rows = []
                for rec in reader:
                    if rec[0].startswith("JPN_"):
                        rows.append((rec[0], [float(x) if x else 0.0 for x in rec[1:]]))
        except FileNotFoundError:
            print("WARNING: raw ICIO csv not found; export exposure unavailable", file=sys.stderr)
            return
        for name, vals in rows:
            tot = sum(vals[i] for i in fd_cols)
            if tot <= 0: continue
            ctry_sum = defaultdict(float)
            for i, ctry in fd_cols.items():
                ctry_sum[ctry] += vals[i]
            self.exp_share[name] = {c: v / tot for c, v in ctry_sum.items() if v / tot > 0.0002}

    # ---------- チャネル変換（ベクトル） ----------
    def shock_entity_failure(self, seed_id):
        v = np.zeros(len(self.ci_names))
        f = np.zeros(len(self.firm_ids))
        f[self.firm_idx[seed_id]] = 1.0
        return f, v

    def shock_war_blockade(self, countries, stop_rate):
        ci_v = np.zeros(len(self.ci_names))
        for c in countries:
            mask = np.array([s.startswith(c + "_") for s in self.ci_names])
            ci_v[mask] = stop_rate
        # 日本企業: 輸出暴露 × stop_rate
        f = np.zeros(len(self.firm_ids))
        for i, cid in enumerate(self.firm_ids):
            ci = self.nodes[cid].get("ci")
            if not ci: continue
            share_c = sum(v for cc, v in self.exp_share.get(ci, {}).items() if cc in countries)
            if share_c > 0:
                f[i] = share_c * stop_rate
        return f, ci_v

    def shock_chokepoint(self, route_id, severity):
        r = self.con.execute("SELECT * FROM shipping_route WHERE route_id=?", (route_id,)).fetchone()
        if not r: sys.exit(f"route {route_id} not found")
        cap = r["world_capacity_share"] * severity
        l = self.import_share * cap
        l = np.where(l > 0.005, np.minimum(0.9, l), 0.0)
        cost = r["alt_route_cost_mult"] * severity * 0.05
        l = np.minimum(0.9, l + cost * self.energy_int)
        return np.zeros(len(self.firm_ids)), l

    def shock_commodity_price(self, commodity, multiplier):
        delta = (multiplier - 1.0) * PASS_THROUGH
        l = np.minimum(0.9, self.energy_int * delta)
        l = np.where(l > 0.003, l, 0.0)
        return np.zeros(len(self.firm_ids)), l

    def shock_port_closure(self, port_id, severity):
        r = self.con.execute("SELECT * FROM port WHERE port_id=?", (port_id,)).fetchone()
        if not r: sys.exit(f"port {port_id} not found")
        share = r["country_container_share"] * severity
        f = np.zeros(len(self.firm_ids))
        for i, cid in enumerate(self.firm_ids):
            ci = self.nodes[cid].get("ci")
            if not ci: continue
            exports = sum(self.exp_share.get(ci, {}).values())
            l = min(0.9, (exports * 0.5 + 0.1) * share)
            if l > 0.003:
                f[i] = l
        return f, np.zeros(len(self.ci_names))

    # ---------- 伝播（ベクトル化） ----------
    def propagate_ci(self, ci_shock, n_rounds=8):
        """Layer A: Leontief型（減衰付き）。
        ΔL_buyer = PROP_DAMP × Σ_seller coeff × ΔL_seller × (1-L_buyer).
        PROP_DAMP は代替調達・在庫バッファ・価格調整による減衰を表す。"""
        loss = ci_shock.copy()
        h = ci_shock.copy()
        for _ in range(n_rounds):
            if not h.any(): break
            add = (self.M @ h) * PROP_DAMP
            add = add * np.maximum(0.0, 1.0 - loss)
            add[add < 1e-6] = 0.0
            if not add.any(): break
            loss = np.minimum(1.0, loss + add)
            h = add
        return loss

    def propagate_firm(self, firm_loss, rng, n_rounds=10):
        """DebtRank式（増分は各エッジを一度だけ）。エッジ配列で高速化."""
        loss = firm_loss.copy()
        h = firm_loss.copy()
        # エッジ依存度の抽選（share_pct未観測のエッジのみ毎回ランダム）
        dep = self.e_dep_obs.copy()
        if self.e_rand_dep.any():
            dep[self.e_rand_dep] = [rng.betavariate(1, 3) for _ in range(self.e_rand_dep.sum())]
        p = np.minimum(1.0, self.e_conf * dep / 0.05)
        active = h > 1e-9
        for _ in range(n_rounds):
            if not active.any(): break
            # activeな送り元のエッジのみ
            mask = active[self.e_src]
            if not mask.any(): break
            hi = h[self.e_src[mask]]
            add = self.e_factor[mask] * dep[mask] * hi * (1.0 - loss[self.e_dst[mask]])
            u = np.array([rng.random() for _ in range(int(mask.sum()))])
            hit = (u <= p[mask]) & (add > 1e-6)
            dst = self.e_dst[mask][hit]
            if dst.size:
                np.add.at(loss, dst, add[hit])
                np.add.at(h, dst, add[hit])
                active = np.zeros_like(active)
                active[dst] = True
                # 送り元の h を消費（増分は一度だけ流れる）
                h_mask_idx = np.unique(self.e_src[mask])
                h[h_mask_idx] = 0.0
            else:
                break
        return loss

    # ---------- メイン ----------
    def run(self, scenario, rng, iterations=300, **kw):
        n_f = len(self.firm_ids)
        sums = np.zeros(n_f); sqs = np.zeros(n_f)
        counts = np.zeros(n_f, dtype=np.int32)
        affected = np.zeros(n_f, dtype=np.int32)
        fn = {"entity_failure": self.shock_entity_failure,
              "war_blockade": self.shock_war_blockade,
              "chokepoint": self.shock_chokepoint,
              "oil_price": self.shock_commodity_price,
              "port_closure": self.shock_port_closure}[scenario]
        for it in range(iterations):
            kw2 = self._perturb(kw, rng)
            firm_shock, ci_shock = fn(**kw2)
            # Layer A 伝播
            ci_loss = self.propagate_ci(ci_shock) if ci_shock.any() else ci_shock
            # Layer A → Layer F（置換ルールは観測エッジがほぼ無いため簡略: CI損失をそのまま加算）
            firm_loss = firm_shock.copy()
            if ci_loss.any():
                fl = ci_loss[self.firm_ci]        # -1 は末尾要素を参照してしまう対策
                valid = self.firm_ci >= 0
                firm_loss[valid] = np.minimum(1.0, firm_loss[valid] + fl[valid])
            # Layer F 伝播
            firm_loss = self.propagate_firm(firm_loss, rng)
            firm_loss = np.minimum(1.0, firm_loss)
            sums += firm_loss; sqs += firm_loss ** 2
            counts += 1
            affected += (firm_loss > 0.01)
        mean = sums / np.maximum(counts, 1)
        std = np.sqrt(np.maximum(sqs / np.maximum(counts, 1) - mean ** 2, 0))
        return mean, std, affected / np.maximum(counts, 1)

    def _perturb(self, kw, rng):
        kw2 = dict(kw)
        if "stop_rate" in kw2:
            sr = min(0.99, max(0.01, kw["stop_rate"]))
            kw2["stop_rate"] = rng.betavariate(sr * 10, (1 - sr) * 10)
        if "severity" in kw2:
            sv = min(0.99, max(0.01, kw["severity"]))
            kw2["severity"] = rng.betavariate(sv * 10, (1 - sv) * 10)
        if "multiplier" in kw2:
            kw2["multiplier"] = max(1.0, kw["multiplier"] * rng.gauss(1.0, 0.1))
        return kw2

    def rows_from(self, mean, prob, top=50, min_prob=0.05):
        """結果をJSON用の行に変換（時価総額×損失の大きい順）."""
        impact = mean * self.firm_mcap
        order = np.argsort(-impact)
        rows = []
        for i in order[:top * 10]:
            if mean[i] <= 0 and prob[i] <= 0: continue
            cid = self.firm_ids[i]
            n = self.nodes[cid]
            rows.append({
                "id": cid, "name": n["legal_name"], "ticker": self.tickers.get(cid, ""),
                "sector": n["sector_j33"], "mcap": n.get("mcap"),
                "mean": round(float(mean[i]), 4),
                "p_mean_pct": round(float(mean[i]) * 100, 2),
                "prob": round(float(prob[i]), 3),
                "impact_jpy_oku": round(float(impact[i]) / 1e8, 1),
            })
            if len(rows) >= top: break
        return rows

    def aggregate(self, mean, prob):
        """全体集計."""
        aff = prob > 0.3
        return {
            "firms_affected_30pct": int(aff.sum()),
            "firms_total": len(self.firm_ids),
            "total_impact_t yen": None,  # 下で計算
            "mean_loss_all": round(float(mean.mean()) * 100, 3),
            "total_impact_oku": round(float((mean * self.firm_mcap).sum()) / 1e8, 0),
        }


# ---------- プリセット（ビューア用） ----------
PRESETS = [
    # (key, scenario, kwargs, label, description)
    ("oil_2x", "oil_price", {"commodity": "brent", "multiplier": 2.0},
     "原油価格2倍", "Brent原油が2倍に上昇。エネルギー強度の高い産業から波及。"),
    ("oil_3x", "oil_price", {"commodity": "brent", "multiplier": 3.0},
     "原油価格3倍", "Brent原油が3倍に上昇（2022年ウクライナ級のショック）。"),
    ("lng_3x", "oil_price", {"commodity": "lng_japan", "multiplier": 3.0},
     "LNG価格3倍", "日本向けLNG現貨価格が3倍（2022年エネルギー危機級）。"),
    ("war_taiwan", "war_blockade", {"countries": ["TWN"], "stop_rate": 0.8},
     "台湾有事（生産停止80%）", "台湾の半導体生産が80%停止。日本企業への輸出暴露から波及。"),
    ("war_china", "war_blockade", {"countries": ["CHN"], "stop_rate": 0.6},
     "中国制裁（生産停止60%）", "中国との貿易が60%停止する制裁シナリオ。"),
    ("suez", "chokepoint", {"route_id": "suez", "severity": 0.6},
     "スエズ運河閉塞", "スエズ運河が閉塞（2021年Ever Given級）。欧州・中東との貿易に遅延。"),
    ("hormuz", "chokepoint", {"route_id": "hormuz", "severity": 0.7},
     "ホルムズ海峡封鎖", "ホルムズ海峡が封鎖。原油・LNGの主要ルートが遮断。"),
    ("malacca", "chokepoint", {"route_id": "malacca", "severity": 0.5},
     "マラッカ海峡閉塞", "日本のエネルギー輸入の生命線マラッカ海峡が閉塞。"),
    ("taiwan_strait", "chokepoint", {"route_id": "taiwan_strait", "severity": 0.5},
     "台湾海峡閉塞", "台湾海峡が閉塞。東アジアの海上貿易全体に遅延。"),
    ("quake_nagoya", "port_closure", {"port_id": "JP NGO", "severity": 1.0},
     "名古屋港閉鎖（南海地震）", "日本最大級の貿易港・名古屋港が完全閉鎖。"),
    ("quake_yokohama", "port_closure", {"port_id": "JP YOK", "severity": 1.0},
     "横浜港閉鎖（首都直下地震）", "首都圏の物流拠点・横浜港が完全閉鎖。"),
]


def export_presets(eng, iterations=200, out_path=VIZ_SCENARIOS):
    out = {"generated": today, "model_version": "v2.0-layered", "scenarios": {}}
    rng = random.Random(7)
    for key, scenario, kw, label, desc in PRESETS:
        t0 = datetime.datetime.now()
        mean, std, prob = eng.run(scenario, rng, iterations=iterations, **kw)
        rows = eng.rows_from(mean, prob, top=200)
        agg = eng.aggregate(mean, prob)
        agg.pop("total_impact_t yen", None)
        # 全企業の損失マップ（ビューアのノード着色用・compact）
        loss_map = {}
        for i, cid in enumerate(eng.firm_ids):
            if mean[i] > 0.002:
                loss_map[cid] = round(float(mean[i]), 4)
        out["scenarios"][key] = {
            "label": label, "description": desc, "scenario": scenario,
            "params": {k: v for k, v in kw.items()},
            "iterations": iterations,
            "aggregate": agg,
            "companies": rows,
            "loss_map": loss_map,
        }
        dt = (datetime.datetime.now() - t0).total_seconds()
        print(f"  {key}: {len(rows)}社 / 影響{agg['firms_affected_30pct']}社 / {dt:.1f}s", flush=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"-> {out_path}")
    return out_path


def main():
    raise SystemExit(
        "This is an archived, unvalidated prototype and its CLI is disabled. "
        "It must not be interpreted as a corporate loss, bankruptcy, or economic forecast. "
        "See the current scope and limitations in README.md."
    )


def _legacy_main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=["entity_failure", "war_blockade", "chokepoint", "oil_price", "port_closure"])
    ap.add_argument("--ticker"); ap.add_argument("--countries"); ap.add_argument("--stop-rate", type=float, default=0.8)
    ap.add_argument("--route"); ap.add_argument("--severity", type=float, default=0.5)
    ap.add_argument("--multiplier", type=float, default=2.0)
    ap.add_argument("--port"); ap.add_argument("--iterations", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--out")
    ap.add_argument("--export-viz", action="store_true", help="プリセット全シナリオを実行しビューア用JSONを生成")
    args = ap.parse_args()

    eng = Engine()

    if args.export_viz:
        export_presets(eng, iterations=args.iterations)
        return

    if not args.scenario:
        ap.error("--scenario が必要（または --export-viz）")
    rng = random.Random(args.seed)
    kw = {}
    if args.scenario == "entity_failure":
        if not args.ticker: ap.error("--ticker required")
        r = eng.con.execute("SELECT company_id FROM id_map WHERE id_type='ticker' AND id_value=?", (args.ticker,)).fetchone()
        if not r: sys.exit("ticker not found")
        kw = dict(seed_id=r["company_id"])
    elif args.scenario == "war_blockade":
        if not args.countries: ap.error("--countries required (comma ISO3, 例: TWN or CHN)")
        kw = dict(countries=args.countries.split(","), stop_rate=args.stop_rate)
    elif args.scenario == "chokepoint":
        kw = dict(route_id=args.route or "taiwan_strait", severity=args.severity)
    elif args.scenario == "oil_price":
        kw = dict(commodity="brent", multiplier=args.multiplier)
    elif args.scenario == "port_closure":
        kw = dict(port_id=args.port or "JP NGO", severity=args.severity)

    print(f"scenario: {args.scenario} {kw} iterations={args.iterations}", flush=True)
    mean, std, prob = eng.run(args.scenario, rng, iterations=args.iterations, **kw)
    rows = eng.rows_from(mean, prob, top=args.top)
    agg = eng.aggregate(mean, prob)
    print(f"\n影響を受ける企業（巻き込まれ確率>30%）: {agg['firms_affected_30pct']} / {agg['firms_total']}社")
    print(f"全企業平均損失: {agg['mean_loss_all']}%  総影響額: {agg['total_impact_oku']:,.0f}億円")
    print(f"\n{'企業':<28} {'業種':<12} {'平均損失':>8} {'巻き込まれ':>8}")
    for r in rows[:args.top]:
        print(f"{r['name'][:26]:<28} {str(r['sector'])[:10]:<12} {r['p_mean_pct']:7.2f}% {r['prob']*100:7.1f}%")
    out = {"scenario": args.scenario, "params": {k: str(v) for k, v in kw.items()},
           "model_version": "v2.0-layered", "iterations": args.iterations,
           "aggregate": agg, "results": rows}
    path = args.out or (BASE / "analysis" / f"scenario_{args.scenario}.json")
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
