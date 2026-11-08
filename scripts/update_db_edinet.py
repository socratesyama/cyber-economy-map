#!/usr/bin/env python3
"""EDINET抽出データを cybermap.sqlite に反映 (tier 1).

- id_map: edinet_code, 法人番号(JCN)
- financials: 有報の連結財務（tier 1 で上書き）
- shareholding: 大株主の状況（tier 1・観測値）
- relation: 大株主が企業と解決できた場合、observed_value の ownership エッジを追加
- relation: 関係会社の状況（ヒューリスティック抽出・低信頼）
"""
import json, re, sqlite3, unicodedata, datetime

DB = "../db/cybermap.sqlite"
con = sqlite3.connect(DB)
cur = con.cursor()
today = datetime.date.today().isoformat()

def norm(s):
    if not s: return ""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    for pat in ["株式会社", "有限会社", "合同会社", "一般社団法人", "一般財団法人", "合資会社", "合名会社",
                "㈱", "（株）", "(株)", "㈲", "（有）", "(有)"]:
        s = s.replace(pat, "")
    return s

# ---------- doc_id -> (company_id, edinet_code, jcn, sec_code) ----------
idx = json.load(open("../data/edinet_yuho_index.json"))
doc2co = {}
for ec, v in idx.items():
    # EDINET secCode は 証券コード4桁+種別1桁（例: 30830 → 3083）
    sec4 = v["secCode"][:4] if v.get("secCode") else None
    if not sec4: continue
    r = cur.execute("SELECT company_id FROM id_map WHERE id_type='ticker' AND id_value=?", (sec4,)).fetchone()
    if r:
        doc2co[v["docID"]] = (r[0], ec, v.get("JCN"), v["secCode"])
print("doc->company matched:", len(doc2co))

# ---------- financials (tier 1) ----------
n = 0
for line in open("../data/edinet_financials.jsonl"):
    d = json.loads(line)
    if d["doc_id"] not in doc2co: continue
    cid, ec, jcn, sec = doc2co[d["doc_id"]]
    cur.execute("""INSERT OR REPLACE INTO financials
      (company_id, fiscal_year, period, currency, revenue, total_assets, cash,
       current_liabilities, liabilities, inventory, net_income, cogs, employees,
       consolidation, source_tier, source, as_of)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (cid, 2026, "FY", "JPY", d.get("revenue"), d.get("total_assets"), d.get("cash"),
       d.get("current_liabilities"), d.get("liabilities"), d.get("inventory"),
       d.get("net_income"), d.get("cogs"), d.get("employees"),
       "consolidated", 1, "edinet_xbrl", today))
    n += 1
print("financials (tier1):", n)

# ---------- name resolution cache ----------
alias2co = {}
for alias, cid in cur.execute("SELECT alias, company_id FROM company_alias"):
    alias2co[norm(alias)] = cid
for nm, cid in cur.execute("SELECT legal_name, company_id FROM company"):
    alias2co[norm(nm)] = cid

# ---------- shareholding (tier 1) ----------
n_sh = n_edge = 0
for line in open("../data/edinet_shareholders.jsonl"):
    d = json.loads(line)
    if d["doc_id"] not in doc2co: continue
    cid, ec, jcn, sec = doc2co[d["doc_id"]]
    nm = d.get("name") or ""
    holder_type = ("individual" if re.search(r"[　\s][一-龠]{2,4}$", nm) and "法人" not in nm and "組合" not in nm
                   else "other_corp")
    cur.execute("INSERT OR REPLACE INTO shareholding (company_id, holder_name_raw, holder_type, share_pct, rank, as_of, source_tier, source_ref) VALUES (?,?,?,?,?,?,1,?)",
        (cid, nm, holder_type, d.get("share_pct"), d.get("rank"), today, f"edinet:{d['doc_id']}"))
    n_sh += 1
    # 観測値付きownershipエッジ（ホルダーが既知企業に解決できた場合のみ）
    hkey = norm(nm)
    hid = alias2co.get(hkey)
    if hid and hid != cid and d.get("share_pct"):
        cur.execute("INSERT OR REPLACE INTO relation (edge_id, src_id, dst_id, relation_type, share_pct, dependency_status, as_of, source_tier, source_ref, extraction, confidence) VALUES (?,?,?,?,?,'observed_value',?,1,?,?,1.0)",
            (f"SH{d['doc_id']}-{d['rank']}", hid, cid, "ownership_parent_of", d["share_pct"], today, f"edinet:{d['doc_id']}", "api"))
        n_edge += 1
print("shareholdings:", n_sh, "resolved ownership edges:", n_edge)

# ---------- affiliates (low confidence, heuristic) ----------
n_af = 0
for line in open("../data/edinet_affiliates.jsonl"):
    d = json.loads(line)
    if d["doc_id"] not in doc2co: continue
    cid, ec, jcn, sec = doc2co[d["doc_id"]]
    nm = d.get("name") or ""
    akey = norm(nm)
    aid = alias2co.get(akey)
    if aid and aid != cid:
        cur.execute("INSERT OR REPLACE INTO relation (edge_id, src_id, dst_id, relation_type, share_pct, dependency_status, as_of, source_tier, source_ref, extraction, confidence) VALUES (?,?,?,?,?,'observed_value',?,1,?,?,0.35)",
            (f"AF{d['doc_id']}-{n_af}", cid, aid, "ownership_parent_of", d.get("share_pct"), today, f"edinet:{d['doc_id']}", "nlp_news"))
        n_af += 1
print("affiliate edges (resolved):", n_af)

con.commit()
for t in ["shareholding", "relation"]:
    print(t, cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
con.close()
