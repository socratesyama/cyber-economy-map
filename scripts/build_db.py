#!/usr/bin/env python3
"""Build cybermap.sqlite from collected raw data (Stage 1-2)."""
import csv, json, sqlite3, datetime, re, unicodedata, os

DB = "../db/cybermap.sqlite"
os.makedirs("../db", exist_ok=True)
if os.path.exists(DB): os.remove(DB)
con = sqlite3.connect(DB)
cur = con.cursor()
today = datetime.date.today().isoformat()

def ulid_seq():
    n = 0
    while True:
        n += 1
        yield f"C{n:08d}"
uid = ulid_seq()

# ---------- schema ----------
cur.executescript(open("schema.sql").read())

# ---------- 1. JPX listed companies ----------
jpx = list(csv.DictReader(open("../data/jpx_nodes_raw.csv", encoding="utf-8")))
code2id = {}
for r in jpx:
    cid = next(uid)
    code2id[r["code"]] = cid
    cur.execute("INSERT INTO company (company_id, legal_name, name_ja, listing_status, status, layer, sector_j33, country, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cid, r["name"], r["name"], "listed", "active", "F_jp", r["sector17"], "JP", today, today))
    cur.execute("INSERT INTO id_map (id_type, id_value, company_id, exchange, source) VALUES (?,?,?,?,?)",
        ("ticker", r["code"], cid, "TSE", "jpx_list"))
    cur.execute("INSERT INTO company_alias (alias, lang, alias_type, company_id, source, confidence) VALUES (?,?,?,?,?,?)",
        (r["name"], "ja", "legal", cid, "jpx_list", 1.0))
print("JPX companies:", len(jpx))

# ---------- 2. Wikidata id links for JP companies ----------
wt = json.load(open("../data/wikidata_tse.json"))["results"]["bindings"]
n = 0
for b in wt:
    qid = b["item"]["value"].split("/")[-1]; code = b["code"]["value"]
    if code in code2id:
        cur.execute("INSERT OR REPLACE INTO id_map (id_type, id_value, company_id, source) VALUES (?,?,?,?)",
            ("wikidata", qid, code2id[code], "wikidata_sparql")); n += 1
print("wikidata links:", n)

# ---------- 3. Relations (Wikidata) ----------
we = json.load(open("../data/wikidata_jp_edges.json"))["results"]["bindings"]
TYPE_MAP = {"parent_org":"ownership_parent_of","owned_by":"ownership_child_of",
            "part_of":"ownership_parent_of","has_subsidiary":"ownership_parent_of","owner_of":"ownership_child_of"}
qid2id = {}
# resolve target companies: create border nodes for non-JP entities
def norm_name(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"\s+", "", s)
n_edges = 0
for b in we:
    code = b["code"]["value"]
    if code not in code2id: continue
    src_qid = None
    # src is the listed company for parent/owned_by/part_of/has_subsidiary; for owner_of direction reversed
    rel = b["rel"]["value"]
    tgt_qid = b["target"]["value"].split("/")[-1]
    tgt_label = b.get("targetLabel", {}).get("value", "")
    if tgt_qid not in qid2id:
        existing = cur.execute("SELECT company_id FROM id_map WHERE id_type='wikidata' AND id_value=?", (tgt_qid,)).fetchone()
        if existing:
            qid2id[tgt_qid] = existing[0]
        else:
            cid = next(uid)
            qid2id[tgt_qid] = cid
            cur.execute("INSERT INTO company (company_id, legal_name, name_en, listing_status, status, layer, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (cid, tgt_label, tgt_label, "unknown", "active", "F_border", today, today))
            cur.execute("INSERT INTO id_map (id_type, id_value, company_id, source) VALUES (?,?,?,?)", ("wikidata", tgt_qid, cid, "wikidata_sparql"))
    # edge direction: parent owns child. For listed co with has_subsidiary: listed -> target (ownership_parent_of)
    if rel in ("has_subsidiary",):
        src, dst = code2id[code], qid2id[tgt_qid]
        rtype = "ownership_parent_of"
    elif rel in ("parent_org", "part_of"):
        src, dst = qid2id[tgt_qid], code2id[code]
        rtype = "ownership_parent_of"
    elif rel == "owned_by":
        src, dst = qid2id[tgt_qid], code2id[code]
        rtype = "ownership_parent_of"
    elif rel == "owner_of":
        src, dst = code2id[code], qid2id[tgt_qid]
        rtype = "ownership_parent_of"
    else: continue
    cur.execute("INSERT INTO relation (edge_id, src_id, dst_id, relation_type, dependency_status, as_of, source_tier, source_ref, extraction, confidence) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (f"E{n_edges+1:08d}", src, dst, rtype, "observed_binary", today, 3, b["target"]["value"], "structured_wiki", 0.75))
    n_edges += 1
print("relations:", n_edges)

# ---------- 4. financials + market snapshot from Yahoo ----------
nf = 0
for line in open("../data/yahoo_fundamentals.jsonl"):
    d = json.loads(line)
    code = d["ticker"].split(".")[0]
    if code not in code2id: continue
    cid = code2id[code]
    cur.execute("""INSERT OR REPLACE INTO financials
      (company_id, fiscal_year, period, currency, revenue, total_assets, equity, cash, interest_debt,
       current_assets, current_liabilities, inventory, cogs, employees, consolidation, source_tier, source, as_of)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (cid, 2026, "TTM", d.get("financialCurrency") or "JPY", d.get("totalRevenue"), None,
       None, d.get("totalCash"), d.get("totalDebt"), None, None, None, None,
       d.get("fullTimeEmployees"), "consolidated", 3, "yahoo_finance", today))
    nf += 1
print("financials:", nf)

nm = 0
for line in open("../data/yahoo_screener.jsonl"):
    d = json.loads(line)
    code = d.get("symbol", "").split(".")[0]
    if code not in code2id: continue
    cur.execute("INSERT INTO market_snapshot (company_id, snap_date, market_cap_jpy, price, currency, source) VALUES (?,?,?,?,?,?)",
        (code2id[code], today, d.get("marketCap"), d.get("regularMarketPrice"), d.get("currency"), "yahoo_screener"))
    nm += 1
print("market snapshots:", nm)

con.commit()
print("tables:", [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")])
for t in ["company","relation","financials","market_snapshot","id_map"]:
    print(t, cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
con.close()
