#!/usr/bin/env python3
"""OECD ICIO 2020 (SML) → sector_io 係数行列 + country_industry ノード.
io_coeff[buyer][seller] = buyerの総中間投入に占めるsellerからの投入比率
"""
import csv, json, sqlite3, datetime
import numpy as np

today = datetime.date.today().isoformat()
Z = "raw/icio/2020_SML.csv"

# read header
with open(Z, newline="") as f:
    reader = csv.reader(f)
    header = next(reader)
    col_labels = header[1:]  # V1 + labels
    row_labels, rows = [], []
    for rec in reader:
        row_labels.append(rec[0])
        rows.append([float(x) if x else 0.0 for x in rec[1:]])
M = np.array(rows)
print("matrix:", M.shape, "rows:", len(row_labels), "cols:", len(col_labels))

# intermediate-use block: rows that are country_industry, cols that are country_industry
def is_ci(s): return "_" in s and s not in ("TLS", "VA", "OUT", "TOT")
ci_cols = [i for i, c in enumerate(col_labels) if is_ci(c)]
ci_rows = [i for i, r in enumerate(row_labels) if is_ci(r)]
A = M[np.ix_(ci_rows, ci_cols)]          # intermediate flows Z[buyer? seller?]
# ICIO convention: rows = seller (origin), cols = buyer (use). Z[seller, buyer]
sellers = [row_labels[i] for i in ci_rows]
buyers = [col_labels[i] for i in ci_cols]
# fix: row labels correspond to columns? verify square
print("sellers:", len(sellers), "buyers:", len(buyers), "square:", A.shape)
total_inputs = A.sum(axis=0)             # buyerの総中間投入 (sum over sellers)
# io_coeff[seller, buyer] = Z[seller,buyer] / total_inputs[buyer]
with np.errstate(divide="ignore", invalid="ignore"):
    coeff = np.where(total_inputs > 0, A / total_inputs, 0.0)
print("coeff nonzero:", (coeff > 0.001).sum())

# save sparse npz for the engine
sel_s, sel_b = np.where(coeff > 0.0005)
vals = coeff[sel_s, sel_b]
np.savez_compressed("data/icio2020_coeff.npz",
                    sellers=np.array(sellers), buyers=np.array(buyers),
                    s=sel_s, b=sel_b, v=vals)
print("saved data/icio2020_coeff.npz edges:", len(vals))

# output totals for country_industry table
out_idx = col_labels.index("OUT") if "OUT" in col_labels else None
out_vals = {}
for i, r in enumerate(ci_rows):
    out_vals[row_labels[r]] = M[r, out_idx] if out_idx is not None else None

con = sqlite3.connect("db/cybermap.sqlite")
cur = con.cursor()
n = 0
for s in sellers:
    ctry, ind = s.split("_", 1)
    cur.execute("INSERT OR REPLACE INTO country_industry (ci_id, country, industry, industry_code_standard) VALUES (?,?,?,?)",
        (s, ctry, ind, "isic_rev4_icio45"))
    n += 1
# sector_io: Japan-relevant + 主要フローのみSQLiteへ（全体はnpz）
m = 0
th = 0.005
for k in range(len(vals)):
    if vals[k] < th: continue
    s_name, b_name = sellers[sel_s[k]], buyers[sel_b[k]]
    # 日本が買い手 or 売り手、または係数が大きい
    if s_name.startswith("JPN") or b_name.startswith("JPN") or vals[k] >= 0.05:
        cur.execute("INSERT OR REPLACE INTO sector_io (year, buyer_ci, seller_ci, io_coeff, source) VALUES (?,?,?,?,?)",
            (2020, b_name, s_name, float(vals[k]), "oecd_icio2023"))
        m += 1
con.commit()
print("country_industry:", n, "sector_io rows:", m)
con.close()
