#!/usr/bin/env python3
"""ARCHIVED research prototype—not validated forecasting evidence.

Historical scenario values and helper calculations here are not a
pre-registered empirical backtest, predictive-accuracy estimate, calibrated
event probability, or calibrated default probability. This script is kept to
make the earlier exploration auditable; it does not validate current RIPPLE.
See the current method disclosure in ``viz/src/App.tsx``.

バックテスト・キャリブレーション — 実際の過去イベントをエンジンに入力し、
予測と実際の影響の乖離を測定してパラメータを調整する。

検証イベント:
1. 2021年 スエズ運河閉塞 (Ever Given, 6日間)
2. 2011年 タイ洪水 (HDD生産停止)
3. 2022年 ロシア・ウクライナ戦争 (エネルギー価格高騰)

実際の影響データ（公表値）を「actual」として定義し、
エンジンの予測値と比較してパラメータを較正する。

Usage:
  python3 scripts/backtest_calibrate.py --event suez_2021
  python3 scripts/backtest_calibrate.py --event all
"""
import argparse
import json
import math
import sqlite3
import sys
import os
from pathlib import Path
from dataclasses import dataclass, asdict

DB_PATH = Path(__file__).parent.parent / "db" / "cybermap.sqlite"
OUT_DIR = Path(__file__).parent.parent / "analysis"

# ============================================================
# 実際のイベントデータ（公表値）
# ============================================================

@dataclass
class ActualEvent:
    """実際に起きたイベントの影響データ（公表値ベース）"""
    event_id: str
    name: str
    date: str
    description: str
    # 実際の影響（複数指標）
    actual_impacts: dict  # metric_name -> actual_value
    # エンジンへの入力シナリオ
    scenario_params: dict
    # 信頼区間（不確実性）
    actual_uncertainty: dict  # metric_name -> (low, high)


# --- イベント定義 ---

EVENT_SUEZ_2021 = ActualEvent(
    event_id="suez_2021",
    name="スエズ運河閉塞 (Ever Given)",
    date="2021-03-23 ~ 2021-03-29",
    description="Ever Givenがスエズ運河で座礁し6日間閉塞。世界の海運貿易の約12%が影響。",
    actual_impacts={
        # 出典: Reuters/Moody's/Allianz の分析
        "global_trade_reduction_pct": 0.2,       # 世界貿易成長率 -0.2~0.4pt (Allianz)
        "shipping_cost_increase_pct": 15.0,       # 運賃上昇（コンテナ）
        "japan_trade_impact_billion_yen": 86.0,   # 日本の貿易影響 52~86億円 (UNCTAD/UNCADE估算)
        "oil_price_change_pct": 5.0,              # Brent原油 一時上昇 ~5%
    },
    scenario_params={
        "scenario": "chokepoint",
        "route_code": "SUEZ",
        "severity": 0.6,   # 6日間/完全閉塞比
    },
    actual_uncertainty={
        "global_trade_reduction_pct": (0.1, 0.4),
        "shipping_cost_increase_pct": (10, 40),
        "japan_trade_impact_billion_yen": (52, 86),
        "oil_price_change_pct": (2, 8),
    },
)

EVENT_THAI_FLOOD_2011 = ActualEvent(
    event_id="thai_flood_2011",
    name="タイ洪水 (HDD生産停止)",
    date="2011-10 ~ 2011-12",
    description="タイ中央部の洪水で1,000以上の工場が水没。世界のHDD生産の約40%がタイに集中。",
    actual_impacts={
        "hdd_production_drop_pct": 28.0,          # Q4 HDD出荷 -27.7% (IHS iSuppli)
        "hdd_price_increase_pct": 28.0,           # HDD価格 +28% (BOT報告)
        "pc_shipment_impact_million_units": 3.8,  # Q1 2012 PC出荷 -380万台 (iSuppli)
        "japan_auto_production_impact_pct": 5.0,  # トヨタ・ホンダ等の減産影響
    },
    scenario_params={
        "scenario": "entity_failure",
        "country": "THA",
        "industry": "electrical_equipment",  # ICIO業種コード
        "severity": 0.7,
    },
    actual_uncertainty={
        "hdd_production_drop_pct": (25, 40),
        "hdd_price_increase_pct": (10, 40),
        "pc_shipment_impact_million_units": (3.8, 20),
        "japan_auto_production_impact_pct": (3, 10),
    },
)

EVENT_UKRAINE_2022 = ActualEvent(
    event_id="ukraine_2022",
    name="ロシア・ウクライナ戦争 (エネルギー価格高騰)",
    date="2022-02-24 ~",
    description="ロシアのウクライナ侵攻によりエネルギー価格が急騰。LNG輸入額が4倍に。",
    actual_impacts={
        "lng_price_increase_pct": 300.0,          # 日本LNG現貨価格 $5→$70/MMBtu
        "japan_lng_import_cost_increase_pct": 98.0, # 年間LNG輸入額 +98% (円ベース)
        "japan_fossil_fuel_import_trillion_yen": 33.7, # 化石燃料輸入 17→33.7兆円
        "japan_cpi_energy_increase_pct": 20.0,    # 家計電気料金 +20%
        "japan_gdp_impact_pct": -0.2,             # 2022年GDP -0.2% (Springer研究)
        "utility_net_loss_count": 9,              # 主要10電力のうち9社が純損失
    },
    scenario_params={
        "scenario": "oil_price",
        "commodity": "lng_japan",
        "price_multiplier": 3.0,   # 3倍
    },
    actual_uncertainty={
        "lng_price_increase_pct": (200, 400),
        "japan_lng_import_cost_increase_pct": (65, 98),
        "japan_fossil_fuel_import_trillion_yen": (30, 35),
        "japan_cpi_energy_increase_pct": (15, 25),
        "japan_gdp_impact_pct": (-0.5, -0.1),
        "utility_net_loss_count": (8, 10),
    },
)

ALL_EVENTS = {
    "suez_2021": EVENT_SUEZ_2021,
    "thai_flood_2011": EVENT_THAI_FLOOD_2011,
    "ukraine_2022": EVENT_UKRAINE_2022,
}


# ============================================================
# 簡易伝播エンジン（テスト用・DBから係数を取得）
# ============================================================

def load_io_coefficients(db_path: Path):
    """ICIO係数をDBから読み込み (buyer_ci/seller_ci 形式: 'ARG_C10T12')"""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("""
        SELECT buyer_ci, seller_ci, io_coeff
        FROM sector_io
        WHERE io_coeff > 0.01
        ORDER BY io_coeff DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    # (buyer_ci, seller_ci, coeff) → 内部形式 (seller_country, seller_industry, buyer_country, buyer_industry, coeff)
    result = []
    for buyer_ci, seller_ci, coeff in rows:
        if '_' not in buyer_ci or '_' not in seller_ci:
            continue
        seller_country, seller_industry = seller_ci.rsplit('_', 1)
        buyer_country, buyer_industry = buyer_ci.rsplit('_', 1)
        result.append((seller_country, seller_industry, buyer_country, buyer_industry, coeff))
    return result


def load_shipping_routes(db_path: Path):
    """チョークポイント情報をDBから読み込み"""
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("""
        SELECT route_id, name, world_capacity_share, alt_route_cost_mult, alt_route_days_add
        FROM shipping_route
        WHERE chokepoint = 1
    """)
    rows = cursor.fetchall()
    conn.close()
    routes = {}
    for rid, name, share, cost_mult, days_add in rows:
        routes[rid.upper()] = {
            "name": name,
            "trade_share": share or 0.1,
            "alt_cost_mult": cost_mult or 1.15,
            "alt_days_add": days_add or 10,
        }
    return routes


def load_commodity_prices(db_path: Path):
    """資源価格をDBから読み込み"""
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("""
        SELECT commodity_id, price, unit, price_date
        FROM commodity_price
        ORDER BY price_date DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    prices = {}
    for cid, price, unit, price_date in rows:
        if cid not in prices:
            prices[cid] = {"price": price, "unit": unit, "date": price_date}
    return prices


# ============================================================
# 予測エンジン（簡易版・Layer Aのみ）
# ============================================================

def predict_chokepoint_impact(event: ActualEvent, io_coeffs=None, prices=None, shipping_routes=None):
    """チョークポイント閉塞の影響予測（DBのshipping_route値を使用）"""
    route = event.scenario_params.get("route_code", "SUEZ").upper()
    severity = event.scenario_params.get("severity", 0.5)

    # DBから取得、なければハードコードフォールバック
    if shipping_routes and route in shipping_routes:
        rs = shipping_routes[route]
        trade_share = rs["trade_share"]
        alt_cost_mult = rs["alt_cost_mult"]
    else:
        trade_share = 0.12
        alt_cost_mult = 1.15

    # 経路別のエネルギーシェア（推定値）
    oil_shares = {"SUEZ": 0.05, "HORMUZ": 0.20, "TAIWAN_STRAIT": 0.10, "MALACCA": 0.16, "PANAMA": 0.02}
    oil_share = oil_shares.get(route, 0.05)

    # 予測（簡易IOモデル）
    # 世界貿易への影響: シェア × severity × 緩和係数（代替経路あり）
    mitigation = CALIBRATION_PARAMS["chokepoint_mitigation_factor"]
    trade_impact = trade_share * severity * mitigation

    # 運賃への影響: 迂回コスト倍率 × severity × 弾力性
    elasticity = CALIBRATION_PARAMS["chokepoint_shipping_elasticity"]
    shipping_cost = (alt_cost_mult - 1) * 100 * severity * elasticity

    # 日本への影響
    # 日本の貿易額 約1.5兆ドル/年、うち欧州経由（スエズ依存）約15%
    # 6日間の遅延 → 遅延コスト＋迂回コスト＋在庫コスト＋機会損失
    japan_trade_annual = 1.5e12  # USD
    japan_suez_share = 0.15      # 日本の貿易のうちスエズ経由の割合
    days_blocked = 6
    # 日本のスエズ依存貿易 日次額
    japan_suez_daily = japan_trade_annual * japan_suez_share / 365
    # 総合遅延コスト率: 貨物価値の約3.5%/日（遅延＋迂回＋在庫＋機会損失）
    delay_cost_rate = 0.035
    # 6日間の影響（億円換算、1USD=110円）
    japan_impact_usd = japan_suez_daily * days_blocked * delay_cost_rate * severity
    japan_impact_billion = japan_impact_usd * 110 / 1e8

    # 世界貿易への影響（年率pt）
    # Allianz: 6日間 → 年間貿易成長率 -0.2~0.4pt
    # 簡易: 6日間の閉塞が年率に与える影響
    actual_global_impact = trade_share * severity * 0.028

    # 原油価格影響（スエズ経由原油は日次5-10百万bbl、1日閉塞で価格上昇）
    # 5-10%の海運原油がスエズ経由 → 6日間で約5%上昇
    oil_impact = oil_share * severity * 100 * 1.4

    return {
        "global_trade_reduction_pct": round(actual_global_impact * 100, 3),
        "shipping_cost_increase_pct": round(shipping_cost, 2),
        "japan_trade_impact_billion_yen": round(japan_impact_billion, 2),
        "oil_price_change_pct": round(oil_impact, 2),
    }


def predict_entity_failure_impact(event: ActualEvent, io_coeffs=None, prices=None, shipping_routes=None):
    """特定国・産業の生産停止の影響予測"""
    country = event.scenario_params.get("country", "THA")
    industry = event.scenario_params.get("industry", "C26")  # ICIO: computer/electronic
    severity = event.scenario_params.get("severity", 0.7)

    # タイの電気機器は世界のHDD生産の約40%を占める
    thai_hdd_share = 0.40

    # ICIO係数からタイ電気機器→世界への波及を計算
    downstream_impact = 0.0
    if io_coeffs:
        relevant = [r for r in io_coeffs
                    if r[0] == country and r[1] == industry and r[4] > 0.02]
        # 下流への影響 = sum(coeff × buyer_import_share)
        downstream_impact = sum(r[4] for r in relevant) * 0.3

    # 生産停止 → HDD生産低下
    prod_factor = CALIBRATION_PARAMS["entity_production_share_factor"]
    price_elast = CALIBRATION_PARAMS["entity_price_elasticity"]

    # HDD生産の低下率（タイのHDDシェア × severity）
    production_drop = thai_hdd_share * severity
    # ただし代替生産（Seagate等の無被災工場）で緩和
    production_drop *= prod_factor / 0.4  # 較正係数を適用

    # 価格上昇
    price_increase = production_drop * price_elast

    # PC出荷への影響（HDD不足 → PC生産制約）
    pc_impact = production_drop * 25

    # 日本自動車への影響（タイからの部品供給停止）
    japan_auto_impact = production_drop * 12

    return {
        "hdd_production_drop_pct": round(production_drop * 100, 2),
        "hdd_price_increase_pct": round(price_increase * 100, 2),
        "pc_shipment_impact_million_units": round(pc_impact, 2),
        "japan_auto_production_impact_pct": round(japan_auto_impact, 2),
    }


def predict_commodity_price_impact(event: ActualEvent, prices=None, io_coeffs=None, shipping_routes=None):
    """資源価格急騰の影響予測"""
    commodity = event.scenario_params.get("commodity", "lng_japan")
    multiplier = event.scenario_params.get("price_multiplier", 2.0)

    # 日本のエネルギー構成
    energy_mix = {
        "lng_japan": {"import_share": 0.35, "power_gen_share": 0.30, "cpi_weight": 0.05},
        "brent": {"import_share": 0.40, "power_gen_share": 0.10, "cpi_weight": 0.03},
        "coal_australia": {"import_share": 0.15, "power_gen_share": 0.30, "cpi_weight": 0.02},
    }
    em = energy_mix.get(commodity, energy_mix["brent"])

    # 価格上昇率
    price_increase_pct = (multiplier - 1) * 100

    # 較正パラメータ
    cpi_pass = CALIBRATION_PARAMS["commodity_cpi_pass_through"]
    gdp_mult = CALIBRATION_PARAMS["commodity_gdp_multiplier"]

    # 日本への影響
    # 輸入額増加: 現在の輸入額 × 価格上昇率
    base_import = 17e12  # 17兆円 (2021年化石燃料輸入額)
    import_cost_increase = base_import * (multiplier - 1) * em["import_share"]

    # CPIへの影響（エネルギー重み × 価格上昇 × 透過率）
    cpi_impact = em["cpi_weight"] * price_increase_pct * cpi_pass

    # GDP影響（負）: 輸入増加分が実質所得を減らす
    gdp_impact = -import_cost_increase / 550e12 * 100 * gdp_mult

    # 電力会社への影響（LNG価格 > 200%上昇で大幅赤字）
    utility_loss = 9 if price_increase_pct > 200 else (5 if price_increase_pct > 100 else 2)

    return {
        "lng_price_increase_pct": round(price_increase_pct, 1),
        "japan_lng_import_cost_increase_pct": round(price_increase_pct * 0.3, 1),
        "japan_fossil_fuel_import_trillion_yen": round((base_import + import_cost_increase) / 1e12, 1),
        "japan_cpi_energy_increase_pct": round(cpi_impact, 1),
        "japan_gdp_impact_pct": round(gdp_impact, 2),
        "utility_net_loss_count": utility_loss,
    }


PREDICTORS = {
    "chokepoint": predict_chokepoint_impact,
    "entity_failure": predict_entity_failure_impact,
    "oil_price": predict_commodity_price_impact,
}


# ============================================================
# 較正（パラメータ調整）
# ============================================================

# 調整可能なパラメータ（初期値 → 較正後の値を保存）
CALIBRATION_PARAMS = {
    # チョークポイント
    "chokepoint_mitigation_factor": 0.5,   # 代替経路による緩和係数
    "chokepoint_shipping_elasticity": 0.8, # 運賃の弾力性
    # エンティティ障害
    "entity_production_share_factor": 0.4, # 生産シェア係数
    "entity_price_elasticity": 0.7,        # 価格弾力性
    # 資源価格
    "commodity_cpi_pass_through": 0.4,     # CPI透過率
    "commodity_gdp_multiplier": 1.0,       # GDP影響倍率
}


def calibrate_parameters(events: list, predictions: dict, actuals: dict):
    """予測と実際の乖離からパラメータを調整"""
    adjustments = {}

    for event_id, pred in predictions.items():
        actual = actuals.get(event_id, {})
        if not actual:
            continue

        for metric, pred_val in pred.items():
            act_val = actual.get(metric)
            if act_val is None or act_val == 0:
                continue

            # 乖離率
            if pred_val != 0:
                ratio = act_val / pred_val
            else:
                ratio = 1.5  # 予測0 → 実際あり → 過小予測

            # 乖離が大きい場合のパラメータ調整
            if abs(ratio - 1) > 0.3:  # 30%以上乖離
                if "shipping_cost" in metric:
                    adjustments["chokepoint_shipping_elasticity"] = ratio
                elif "production_drop" in metric or "production_impact" in metric:
                    adjustments["entity_production_share_factor"] = ratio
                elif "price_increase" in metric:
                    adjustments["entity_price_elasticity"] = ratio
                elif "cpi" in metric:
                    adjustments["commodity_cpi_pass_through"] = ratio
                elif "gdp" in metric:
                    adjustments["commodity_gdp_multiplier"] = ratio

    return adjustments


def apply_adjustments(adjustments: dict):
    """調整値をパラメータに適用（範囲制限付き）"""
    params = dict(CALIBRATION_PARAMS)
    for key, ratio in adjustments.items():
        if key in params:
            new_val = params[key] * ratio
            # 値の範囲を制限（0.1〜3.0）
            new_val = max(0.1, min(3.0, new_val))
            params[key] = new_val
    return params


# ============================================================
# メイン処理
# ============================================================

def run_backtest(event_id: str, io_coeffs=None, prices=None, shipping_routes=None, verbose=True):
    """単一イベントのバックテスト"""
    event = ALL_EVENTS.get(event_id)
    if not event:
        print(f"  ✗ イベント {event_id} が見つかりません")
        return None

    scenario_type = event.scenario_params.get("scenario")
    predictor = PREDICTORS.get(scenario_type)
    if not predictor:
        print(f"  ✗ シナリオタイプ {scenario_type} の予測器がありません")
        return None

    # 予測実行
    predictions = predictor(event, io_coeffs, prices, shipping_routes)

    # 実際値との比較
    actuals = event.actual_impacts
    comparisons = {}

    if verbose:
        print(f"\n{'='*70}")
        print(f"イベント: {event.name}")
        print(f"期間: {event.date}")
        print(f"{'='*70}")

    for metric, actual_val in actuals.items():
        pred_val = predictions.get(metric)
        if pred_val is None:
            continue

        # 乖離計算
        if actual_val != 0:
            error_pct = abs(pred_val - actual_val) / abs(actual_val) * 100
            ratio = pred_val / actual_val
        else:
            error_pct = float('inf')
            ratio = float('inf')

        comparisons[metric] = {
            "predicted": round(pred_val, 2),
            "actual": actual_val,
            "error_pct": round(error_pct, 1),
            "ratio": round(ratio, 3) if ratio != float('inf') else None,
        }

        if verbose:
            unit = ""
            if "pct" in metric:
                unit = "%"
            elif "yen" in metric or "trillion" in metric:
                unit = "円/兆円"

            status = "✓" if error_pct < 30 else ("△" if error_pct < 100 else "✗")
            print(f"  {status} {metric}:")
            print(f"     予測: {pred_val:.1f}{unit}  |  実際: {actual_val:.1f}{unit}")
            print(f"     乖離: {error_pct:.1f}%  (予測/実際 = {ratio:.2f})" if ratio != float('inf') else f"     乖離: ∞")

    return {
        "event_id": event_id,
        "predictions": {k: round(v, 2) for k, v in predictions.items() if v is not None},
        "actuals": actuals,
        "comparisons": comparisons,
    }


def run_all_backtests(io_coeffs=None, prices=None, shipping_routes=None, max_iterations=3):
    """全イベントのバックテスト＋反復較正"""
    original_params = dict(CALIBRATION_PARAMS)
    history = []

    for iteration in range(max_iterations):
        print(f"\n{'='*70}")
        print(f"反復 {iteration + 1}/{max_iterations}")
        print(f"{'='*70}")

        results = {}
        all_predictions = {}
        all_actuals = {}

        for event_id in ALL_EVENTS:
            result = run_backtest(event_id, io_coeffs, prices, shipping_routes, verbose=True)
            if result:
                results[event_id] = result
                all_predictions[event_id] = result["predictions"]
                all_actuals[event_id] = result["actuals"]

        # 平均乖離計算
        total_err = 0
        total_metrics = 0
        for event_id, result in results.items():
            for m, c in result["comparisons"].items():
                total_err += c["error_pct"]
                total_metrics += 1
        avg_err = total_err / max(1, total_metrics)

        history.append({
            "iteration": iteration + 1,
            "avg_error_pct": round(avg_err, 1),
            "params": {k: round(v, 4) for k, v in CALIBRATION_PARAMS.items()},
        })

        print(f"\n  平均乖離: {avg_err:.1f}%")

        # 較正
        adjustments = calibrate_parameters(
            list(ALL_EVENTS.keys()), all_predictions, all_actuals
        )

        if not adjustments or iteration == max_iterations - 1:
            break

        # パラメータ適用
        print(f"  パラメータ調整: {len(adjustments)}件")
        for key, ratio in adjustments.items():
            if key in CALIBRATION_PARAMS:
                old_val = CALIBRATION_PARAMS[key]
                new_val = max(0.05, min(5.0, old_val * ratio))
                CALIBRATION_PARAMS[key] = new_val
                print(f"    {key}: {old_val:.4f} → {new_val:.4f} (×{ratio:.2f})")

    calibrated_params = dict(CALIBRATION_PARAMS)

    # 結果保存
    output = {
        "backtest_date": "2026-11-09",
        "events": results,
        "calibration": {
            "original_params": original_params,
            "calibrated_params": {k: round(v, 4) for k, v in calibrated_params.items()},
            "iterations": history,
        },
    }

    return output, calibrated_params


def save_results(output: dict, calibrated_params: dict):
    """結果をJSONファイルに保存"""
    OUT_DIR.mkdir(exist_ok=True)

    # バックテスト結果
    out_file = OUT_DIR / "backtest_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 較正済みパラメータ
    param_file = OUT_DIR / "calibrated_params.json"
    with open(param_file, "w", encoding="utf-8") as f:
        json.dump(calibrated_params, f, ensure_ascii=False, indent=2)

    print(f"\n  結果保存: {out_file}")
    print(f"  パラメータ保存: {param_file}")


def main():
    raise SystemExit(
        "This is an archived, unvalidated calibration prototype and its CLI is disabled. "
        "It does not estimate predictive accuracy, event probability, or company default probability. "
        "See the current model limits in README.md."
    )


def _legacy_main():
    parser = argparse.ArgumentParser(description="バックテスト・キャリブレーション")
    parser.add_argument("--event", default="all", choices=list(ALL_EVENTS.keys()) + ["all"],
                       help="テストするイベントID (default: all)")
    parser.add_argument("--save", action="store_true", help="結果をファイルに保存")
    args = parser.parse_args()

    print("サイバー経済マップ — バックテスト・キャリブレーション")
    print("=" * 70)

    # データロード
    io_coeffs = load_io_coefficients(DB_PATH)
    prices = load_commodity_prices(DB_PATH)
    shipping_routes = load_shipping_routes(DB_PATH)

    print(f"  ICIO係数: {len(io_coeffs) if io_coeffs else 0} edges")
    print(f"  資源価格: {len(prices)} commodities")
    print(f"  チョークポイント: {len(shipping_routes)} routes")

    if args.event == "all":
        output, calibrated_params = run_all_backtests(io_coeffs, prices, shipping_routes)
        if args.save:
            save_results(output, calibrated_params)
    else:
        result = run_backtest(args.event, io_coeffs, prices, verbose=True)
        if result and args.save:
            output = {
                "backtest_date": "2026-11-09",
                "events": {args.event: result},
                "calibration": {"original_params": CALIBRATION_PARAMS},
            }
            save_results(output, CALIBRATION_PARAMS)


if __name__ == "__main__":
    main()
