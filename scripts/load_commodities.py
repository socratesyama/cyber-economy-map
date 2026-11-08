#!/usr/bin/env python3
"""世界銀行Pink Sheet月次商品価格 → commodity_price テーブル.
主要商品（エネルギー・金属・食料）の直近10年分を投入。"""
import datetime, sqlite3, openpyxl

CONV = {  # 列名 → commodity_id (unit付き)
    "Crude oil, average": ("crude_avg", "$/bbl"),
    "Crude oil, Brent": ("brent", "$/bbl"),
    "Coal, Australian": ("coal_australia", "$/mt"),
    "Natural gas, Europe": ("gas_europe", "$/mmbtu"),
    "Liquefied natural gas, Japan": ("lng_japan", "$/mmbtu"),
    "Aluminum": ("aluminum", "$/mt"),
    "Iron ore, cfr spot": ("iron_ore", "$/mt"),
    "Copper": ("copper", "$/mt"),
    "Nickel": ("nickel", "$/mt"),
    "Wheat, US HRW": ("wheat_hrw", "$/mt"),
    "Maize": ("maize", "$/mt"),
    "Rice, Thai 5% ": ("rice_thai", "$/mt"),
    "Soybeans": ("soybeans", "$/mt"),
    "Cotton, A Index": ("cotton", "$/mt"),
    "Rubber, TSR20 **": ("rubber_tsr20", "$/mt"),
    "Urea ": ("urea", "$/mt"),
    "Phosphate rock": ("phosphate_rock", "$/mt"),
    "Potassium chloride **": ("potassium_chloride", "$/mt"),
    "Gold": ("gold", "$/toz"),
}
wb = openpyxl.load_workbook("raw/commodities/cmo_monthly.xlsx", read_only=True)
ws = wb["Monthly Prices"]
rows = list(ws.iter_rows(values_only=True))
names = rows[4]
colmap = {}  # col idx -> commodity_id, unit
for j, n in enumerate(names):
    if n and str(n).strip() in CONV:
        colmap[j] = CONV[str(n).strip()]
con = sqlite3.connect("db/cybermap.sqlite")
cur = con.cursor()
n = 0
cutoff = "2016"
for r in rows[6:]:
    if not r or not r[0]: continue
    date_raw = str(r[0])
    if not date_raw[:4] >= cutoff: continue
    # 1960M01形式 → YYYY-MM-DD
    if "M" in date_raw:
        y, m = date_raw.split("M")
        date = f"{y}-{int(m):02d}-28"
    else:
        continue
    for j, (cid, unit) in colmap.items():
        v = r[j] if j < len(r) else None
        if v is None or v == "…" or not isinstance(v, (int, float)): continue
        cur.execute("INSERT OR REPLACE INTO commodity_price (commodity_id, price_date, price, unit, currency, source) VALUES (?,?,?,?,?,?)",
            (cid, date, float(v), unit, "USD", "world_bank_pink_sheet"))
        n += 1
con.commit()
print("commodity_price rows:", n, "commodities:", len(colmap))
# 最新値の確認
for cid in ["brent", "lng_japan", "copper", "wheat_hrw"]:
    r = cur.execute("SELECT price_date, price FROM commodity_price WHERE commodity_id=? ORDER BY price_date DESC LIMIT 1", (cid,)).fetchone()
    print(cid, r)
con.close()
