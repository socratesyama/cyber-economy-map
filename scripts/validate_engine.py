#!/usr/bin/env python3
"""イベント検証ハーネス — 実際に起きた過去事例でエンジンを検証する。

analysis/validation_events.json に登録された事例の入力をエンジンに与え、
観測された影響（公表値・出典付き）と比較する。

設計原則:
  1. 予測は常に「既定パラメータ」または「trainイベントで較正したパラメータ」で行う。
     検証対象イベント自体の観測値を較正に使った循環は禁止。
  2. 比較不能な指標は comparable=false とし、無理な対応を付けない。
  3. 結果は ratio（予測/実測）で報告し、誤差の方向と大きさを明示する。

Usage:
  python3 scripts/validate_engine.py                     # 全イベント検証
  python3 scripts/validate_engine.py --calibrate          # trainイベントでグリッドサーチ
  python3 scripts/validate_engine.py --sensitivity       # パラメータ感応度
"""
import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))

EVENTS_PATH = BASE / "analysis" / "validation_events.json"
REPORT_PATH = BASE / "analysis" / "validation_results.json"

WORKDAYS = 250  # 年間稼働日数（severityの基準）


def load_engine():
    import scenario_engine as se
    return se.Engine(), se


def apply_coeff_overrides(eng, overrides):
    """coeff_overrides: 特定の buyer←seller の入力係数を上書き（較正シナリオ仮定）。
    M[buyer, seller] = max(現行値, effective_input_share)"""
    changed = []
    for ov in overrides:
        bi = eng.ci_idx.get(ov["buyer_ci"])
        si = eng.ci_idx.get(ov["seller_ci"])
        if bi is None or si is None:
            print(f"  WARNING: override target not found {ov}")
            continue
        old = eng.M[bi, si]
        eng.M[bi, si] = max(old, ov["effective_input_share"])
        changed.append((ov["buyer_ci"], ov["seller_ci"], float(old), ov["effective_input_share"]))
    return changed


def restore_M(eng):
    eng._load_layerA.__func__  # noqa - 何もしない。Mは都度再構築する設計のため復元不要
    # 実際は呼び出し側で M を deepcopy して復元する


def layerA_loss(eng, se, scenario, params, overrides=None, iterations=1):
    """Layer A（国×産業）の伝播後損失を返す。確率的要素なしの決定論的計算。
    war_blockade は export_share が無いため firm ショック0で Layer A のみ。"""
    m_backup = eng.M.copy()
    try:
        if overrides:
            apply_coeff_overrides(eng, overrides)
        fn = {"war_blockade": eng.shock_war_blockade,
              "chokepoint": eng.shock_chokepoint,
              "oil_price": eng.shock_commodity_price}[scenario]
        kw = dict(params)
        if kw.get("countries") == "ALL":
            kw["countries"] = [c.split("_")[0] for c in eng.ci_names if "_" in c]
            kw["countries"] = sorted(set(kw["countries"]))
        firm_shock, ci_shock = fn(**kw)
        ci_loss = eng.propagate_ci(ci_shock) if getattr(ci_shock, "any", lambda: False)() else ci_shock
        return ci_loss, firm_shock
    finally:
        eng.M = m_backup


def firm_loss(eng, se, scenario, params, seed=7, iterations=80):
    """エンジン全体（Layer F含む）を実行しfirm別平均損失率を返す。"""
    rng = random.Random(seed)
    mean, std, prob = eng.run(scenario, rng, iterations=iterations, **params)
    return mean, prob


def pct(x):
    return f"{x*100:.2f}%"


def compare(pred, actual, name):
    ratio = pred / actual if actual else None
    return {"name": name, "predicted": round(pred, 4), "actual": round(actual, 4),
            "ratio": round(ratio, 3) if ratio else None,
            "log_error": round(abs(np.log(max(pred, 1e-9) / max(actual, 1e-9))), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true", help="trainイベントでパラメータをグリッドサーチ")
    ap.add_argument("--sensitivity", action="store_true", help="パラメータ感応度分析")
    ap.add_argument("--out", default=str(REPORT_PATH))
    args = ap.parse_args()

    with open(EVENTS_PATH, encoding="utf-8") as f:
        registry = json.load(f)

    eng, se = load_engine()
    results = {"generated": se.today, "engine_params": {"pass_through": se.PASS_THROUGH,
                                                        "prop_damp": se.PROP_DAMP},
               "events": {}}

    print("=" * 72)
    print(f"イベント検証ハーネス — {len(registry['events'])}事例")
    print(f"engine params: pass_through={se.PASS_THROUGH:.3f} prop_damp={se.PROP_DAMP:.3f}")
    print("=" * 72)

    for ev in registry["events"]:
        eid = ev["event_id"]
        scenario = ev.get("scenario")
        if scenario is None:
            results["events"][eid] = {"status": "reference_only", "observed": ev.get("observed", [])}
            print(f"\n[{eid}] 参考（エンジン対象外）")
            continue
        params = dict(ev["scenario_params"])
        overrides = ev.get("coeff_overrides")
        out = {"split": ev.get("split"), "params": params}

        if scenario in ("war_blockade", "chokepoint", "oil_price"):
            ci_loss, firm_shock = layerA_loss(eng, se, scenario, params, overrides)
            jpn_idx = [i for i, c in enumerate(eng.ci_names) if c.startswith("JPN_")]
            jpn_mean = float(ci_loss[jpn_idx].mean())
            out["layerA"] = {
                "jpn_mean_loss_pct": round(jpn_mean * 100, 3),
                "jpn_c29_loss_pct": round(float(ci_loss[eng.ci_idx["JPN_C29"]]) * 100, 3) if "JPN_C29" in eng.ci_idx else None,
                "jpn_d_loss_pct": round(float(ci_loss[eng.ci_idx["JPN_D"]]) * 100, 3) if "JPN_D" in eng.ci_idx else None,
                "jpn_c26_loss_pct": round(float(ci_loss[eng.ci_idx["JPN_C26"]]) * 100, 3) if "JPN_C26" in eng.ci_idx else None,
            }
            # 伝播増幅率: 全JPN損失 / 直接衝撃
            direct = params.get("stop_rate") or 0
            if scenario == "war_blockade" and direct:
                out["layerA"]["amplification"] = round(jpn_mean / direct, 3)
            print(f"\n[{eid}] ({ev.get('split')}) scenario={scenario} {params}")
            print(f"  JPN平均損失: {jpn_mean*100:.3f}%  C29: {out['layerA']['jpn_c29_loss_pct']}%  D: {out['layerA']['jpn_d_loss_pct']}%")

        elif scenario == "entity_failure":
            # ticker -> company_id
            ticker = params.pop("ticker")
            watch_tickers = params.pop("watch_tickers", [])
            r = eng.con.execute(
                "SELECT company_id FROM id_map WHERE id_type='ticker' AND id_value=?", (ticker,)).fetchone()
            if not r:
                out["status"] = "ticker_not_found"
                results["events"][eid] = out
                print(f"\n[{eid}] ticker {ticker} not found")
                continue
            kw = dict(seed_id=r["company_id"], **params)
            rng = random.Random(7)
            mean, std, prob = eng.run("entity_failure", rng, iterations=80, **kw)
            i = eng.firm_idx[r["company_id"]]
            out["firm"] = {
                "seed_ticker": ticker,
                "seed_mean_loss_pct": round(float(mean[i]) * 100, 3),
                "suppliers_mean_loss_pct": round(float(mean[np.arange(len(mean)) != i].mean()) * 100, 4),
                "firms_affected_gt1pct": int((mean > 0.01).sum()),
            }
            # 特定企業の損失率を記録（伝播先の検証用）
            for wt in watch_tickers:
                w = eng.con.execute(
                    "SELECT company_id FROM id_map WHERE id_type='ticker' AND id_value=?", (wt,)).fetchone()
                if w and w["company_id"] in eng.firm_idx:
                    j = eng.firm_idx[w["company_id"]]
                    out["firm"].setdefault("watch_losses_pct", {})[wt] = round(float(mean[j]) * 100, 3)
            print(f"\n[{eid}] ({ev.get('split')}) entity_failure {ticker} severity={params.get('severity')}")
            print(f"  seed損失: {out['firm']['seed_mean_loss_pct']}%  他社平均: {out['firm']['suppliers_mean_loss_pct']}%  影響>1%: {out['firm']['firms_affected_gt1pct']}社")
            for wt, v in out["firm"].get("watch_losses_pct", {}).items():
                print(f"  watch {wt}: {v}%")

        # 比較（comparisonsで定義されたもののみ）
        comps = []
        for c in ev.get("comparisons", []):
            entry = {"key": c.get("key"), "comparable": bool(c.get("comparable")), "note": c.get("note", "")}
            # 自動比較: actual_value_pct + predict_from が定義された比較は予測/実測比を機械計算する
            if c.get("actual_value_pct") is not None and c.get("predict_from"):
                try:
                    pred = out
                    for p in c["predict_from"].split("."):
                        pred = pred[p] if isinstance(pred, dict) else None
                    if pred is not None:
                        pred = float(pred)
                        actual = float(c["actual_value_pct"])
                        entry.update({
                            "predicted_pct": round(pred, 3),
                            "actual_pct": actual,
                            "ratio": round(pred / actual, 3) if actual else None,
                            "log_error": round(abs(np.log(max(pred, 1e-9) / max(actual, 1e-9))), 3),
                        })
                except (KeyError, TypeError, ValueError):
                    entry["auto_compare_error"] = True
            comps.append(entry)
        out["comparisons"] = comps
        results["events"][eid] = out

    # ---------- 較正（trainイベントでグリッドサーチ） ----------
    if args.calibrate:
        print("\n" + "=" * 72)
        print("パラメータ較正 — trainイベント（thai_flood_2011, ukraine_2022）でグリッドサーチ")
        print("目標: thai → JPN_C29損失 ≈ 10%（トヨタ国内生産 約11%/愛知IP ▲9.1%の中間）")
        print("      ukraine → JPN_D損失 ≈ 4.2%（東京電力FY2022経常減益率）")
        print("=" * 72)
        thai_ov = [{"buyer_ci": "JPN_C29", "seller_ci": "THA_C26", "effective_input_share": 0.22}]
        grid_pt = [0.03, 0.05, 0.066, 0.1, 0.2, 0.5]
        grid_pd = [0.1, 0.2, 0.3, 0.4, 0.6, 0.8, 1.0]
        best = None
        rows = []
        for pt in grid_pt:
            for pd in grid_pd:
                se.PASS_THROUGH, se.PROP_DAMP = pt, pd
                # thai: JPN_C29損失
                ci_t, _ = layerA_loss(eng, se, "war_blockade",
                                        {"countries": ["THA"], "stop_rate": 0.4}, thai_ov)
                c29 = float(ci_t[eng.ci_idx["JPN_C29"]])
                # ukraine: JPN_D損失
                ci_u, _ = layerA_loss(eng, se, "oil_price",
                                       {"commodity": "lng_japan", "multiplier": 2.04})
                d_loss = float(ci_u[eng.ci_idx["JPN_D"]])
                err = abs(np.log(max(c29, 1e-6) / 0.10)) + abs(np.log(max(d_loss, 1e-6) / 0.042))
                rows.append({"pass_through": pt, "prop_damp": pd,
                            "thai_c29_pct": round(c29 * 100, 2), "ukr_d_pct": round(d_loss * 100, 2),
                            "log_error": round(err, 3)})
                if best is None or err < best["log_error"]:
                    best = rows[-1]
        print(f"  {'pt':>6} {'pd':>5} | {'C29%':>7} {'D%':>7} | {'err':>6}")
        for r in rows:
            mark = " ← best" if r is best else ""
            print(f"  {r['pass_through']:>6} {r['prop_damp']:>5} | {r['thai_c29_pct']:>7} {r['ukr_d_pct']:>7} | {r['log_error']:>6}{mark}")
        results["calibration_grid"] = rows
        results["calibration_best"] = best

    # ---------- 感応度分析 ----------
    if args.sensitivity:
        print("\n" + "=" * 72)
        print("感応度分析 — pass_through × prop_damp のJPN平均損失への影響")
        print("=" * 72)
        grid = {"pass_through": [0.05, 0.1, 0.3, 0.5], "prop_damp": [0.1, 0.4, 0.9]}
        sens = []
        for pt in grid["pass_through"]:
            for pd in grid["prop_damp"]:
                se.PASS_THROUGH, se.PROP_DAMP = pt, pd
                ci_loss, _ = layerA_loss(eng, se, "oil_price",
                                          {"commodity": "lng_japan", "multiplier": 2.04})
                jpn_idx = [i for i, c in enumerate(eng.ci_names) if c.startswith("JPN_")]
                v = float(ci_loss[jpn_idx].mean()) * 100
                sens.append({"pass_through": pt, "prop_damp": pd, "jpn_mean_loss_pct": round(v, 3)})
                print(f"  pt={pt:.2f} pd={pd:.2f} → JPN平均 {v:.3f}%")
        results["sensitivity_oil2x"] = sens
        # thai flood too
        sens2 = []
        for pd in grid["prop_damp"]:
            se.PASS_THROUGH, se.PROP_DAMP = se.PASS_THROUGH, pd
            ci_loss, _ = layerA_loss(eng, se, "war_blockade",
                                      {"countries": ["THA"], "stop_rate": 0.4},
                                      overrides=[{"buyer_ci": "JPN_C29", "seller_ci": "THA_C26", "effective_input_share": 0.22}])
            v = float(ci_loss[eng.ci_idx["JPN_C29"]]) * 100
            sens2.append({"prop_damp": pd, "jpn_c29_loss_pct": round(v, 3)})
            print(f"  thai pd={pd:.2f} → JPN_C29 {v:.3f}%")
        results["sensitivity_thai_flood"] = sens2

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
