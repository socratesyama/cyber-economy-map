#!/usr/bin/env python3
"""海運チョークポイント・港湾の公表値を投入（出典付き・推定フラグ）.
出典: UNCTAD Review of Maritime Transport, EIA World Oil Transit Chokepoints,
IMF PortWatch, 各港の公表スループット統計。値は公表推定値（tier 2）。"""
import sqlite3

ROUTES = [
    # id, name, chokepoint(1=代替困難), world_capacity_share(世界海上貿易量比), alt_cost_mult, alt_days_add, source
    ("suez", "スエズ運河（紅海経由込み）", 1, 0.12, 1.15, 12,
     "UNCTAD 2023: 世界貿易の12%、コンテナ輸送の30%。迂回=喜望峰、+10〜14日"),
    ("hormuz", "ホルムズ海峡", 1, 0.20, 1.30, 20,
     "EIA: 石油液類の世界消費の約20%（約2,000万b/d）、LNG貿易の約20〜25%。パイプライン代替は僅少"),
    ("malacca", "マラッカ海峡", 1, 0.30, 1.05, 4,
     "EIA/UNCTAD: 海上貿易の約30%、石油約2,300万b/d。迂回=ロンボク/スンダ水道 +3〜5日"),
    ("taiwan_strait", "台湾海峡", 1, 0.20, 1.10, 7,
     "Bloomberg/CSIS 2022: 世界貿易の約20%、大型コンテナ船の約半数が通過。迂回=台湾東岸 +数日"),
    ("panama", "パナマ運河", 0, 0.05, 1.20, 15,
     "UNCTAD: 世界貿易の約5%、米コンテナ輸送の約40%（2023干ばん時は通過枠制限）"),
    ("bab_el_mandeb", "バブ・エル・マンデブ海峡", 1, 0.10, 1.15, 12,
     "UNCTAD 2023: スエズ経由量の約3割が通過、紅海危機で迂回増"),
]
PORTS = [
    # id, name, country, lat, lon, teu(万TEU/年), share(日本コンテナ輸送比), source
    ("JP TYO", "東京港", "JP", 35.6167, 139.7833, 486, 0.18, "東京都港湾局 2023公表値"),
    ("JP YOK", "横浜港", "JP", 35.4500, 139.6667, 289, 0.11, "横浜市港湾局 2023公表値"),
    ("JP NGO", "名古屋港", "JP", 35.0500, 136.8833, 275, 0.10, "名古屋港管理組合 2023公表値"),
    ("JP KOBE","神戸港", "JP", 34.6833, 135.1833, 275, 0.10, "神戸市 2023公表値"),
    ("JP OSA", "大阪港", "JP", 34.6500, 135.4333, 230, 0.09, "大阪市 2023公表値"),
    ("JP HAK", "博多港", "JP", 33.6167, 130.4000, 120, 0.04, "福岡市 2023公表値"),
]
con = sqlite3.connect("db/cybermap.sqlite")
cur = con.cursor()
for r in ROUTES:
    cur.execute("""INSERT OR REPLACE INTO shipping_route
      (route_id, name, chokepoint, world_capacity_share, alt_route_cost_mult, alt_route_days_add, source)
      VALUES (?,?,?,?,?,?,?)""", r)
for p in PORTS:
    cur.execute("""INSERT OR REPLACE INTO port
      (port_id, name, country, lat, lon, teu_annual, country_container_share, source)
      VALUES (?,?,?,?,?,?,?,?)""",
      (p[0], p[1], p[2], p[3], p[4], p[5]*1e4, p[6], p[7]))
con.commit()
print("shipping_route:", cur.execute("SELECT COUNT(*) FROM shipping_route").fetchone()[0])
print("port:", cur.execute("SELECT COUNT(*) FROM port").fetchone()[0])
con.close()
