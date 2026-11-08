#!/usr/bin/env python3
"""EDINET 有報CSV(type=5)から大株主・関係会社・財務を抽出 → JSONL 3種."""
import json, os, re, sys, zipfile
from collections import defaultdict

CSVDIR = "raw/edinet/csv"
OUT = "data"

def split_line(l):
    return [p.strip('"') for p in l.split('"\t"')]

def parse_csv_text(text):
    rows = []
    for l in text.splitlines():
        parts = split_line(l)
        if len(parts) >= 9:
            rows.append(parts)  # [tag, label, context, context_label, ..., value=parts[8]]
    return rows

def get_file_rows(z):
    names = [n for n in z.namelist() if "jpcrp030000" in n]
    if not names: return None
    text = z.read(names[0]).decode("utf-16", errors="replace")
    return parse_csv_text(text)

def num(x):
    if x in (None, "", "－", "-", "－"): return None
    try: return float(str(x).replace(",", "").replace("－", ""))
    except ValueError: return None

# ---------- 大株主 ----------
def extract_shareholders(rows):
    names, ratios, shares = {}, {}, {}
    for p in rows:
        tag, ctx, val = p[0], p[2], p[8]
        m = re.search(r"No(\d+)MajorShareholdersMember", ctx)
        if not m: continue
        n = int(m.group(1))
        if tag == "jpcrp_cor:NameMajorShareholders": names[n] = val
        elif tag == "jpcrp_cor:ShareholdingRatio":
            r_ = num(val)
            ratios[n] = (r_ * 100) if (r_ is not None and r_ <= 1.0) else r_
        elif tag == "jpcrp_cor:NumberOfSharesHeld": shares[n] = num(val)
    out = []
    for n in sorted(set(names) | set(ratios)):
        out.append({"rank": n, "name": names.get(n), "share_pct": ratios.get(n), "shares": shares.get(n)})
    return out

# ---------- 関係会社 (テキストブロックからヒューリスティック抽出) ----------
LEGAL_FORMS = r"(株式会社|有限会社|合同会社|一般社団法人|一般財団法人|社会福祉法人|学校法人|医療法人|特定非営利活動法人|合資会社|合名会社|株式会社)"
def extract_affiliates(rows):
    text = None
    for p in rows:
        if p[0] == "jpcrp_cor:OverviewOfAffiliatedEntitiesTextBlock":
            text = p[8]; break
    if not text: return []
    # 名称っぽいトークン + 議決権割合
    PREF = r"(札幌市|仙台市|さいたま市|横浜市|川崎市|名古屋市|京都市|大阪市|神戸市|広島市|北九州市|福岡市|北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|埼玉県|千葉県|東京都|神奈川県|新潟県|富山県|石川県|福井県|山梨県|長野県|岐阜県|静岡県|愛知県|三重県|滋賀県|京都府|大阪府|兵庫県|奈良県|和歌山県|鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|高知県|福岡県|佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県)"
    STOP = r"(?=" + PREF + r"|[0-9０-９千百万億円％%]|住所|資本金|事業の内容|議決権|関係内容|所在地|工場|支店|営業所)"
    names = []
    for m in re.finditer(LEGAL_FORMS + r"([^\s、。「」（）()【】]{1,40}?" + STOP + r"|[^\s、。「」（）()【】]{1,40})", text):
        nm = m.group(0)
        nm = re.sub(STOP + r".*$", "", nm) if re.search(STOP, nm) else nm
        nm = nm.strip()
        if re.match(LEGAL_FORMS + r"[はをがにのもと]", nm): continue
        if len(nm) >= 5 and nm not in names and not any(c in nm for c in ("％", "%", "千円")):
            names.append(nm)
    pcts = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)％", text)]
    # 前から順に名称と割合を対応付ける（近似。信頼度は低く設定）
    out = []
    for i, nm in enumerate(names[:len(pcts)] if len(names) > len(pcts) else names):
        pct = pcts[i] if i < len(pcts) else None
        out.append({"name": nm, "share_pct": pct})
    return out, text[:2000]

# ---------- 財務 ----------
# ローカル名（プレフィックス不問）→ フィールド。IFRSタグを含む。
FIN_LOCAL = {
    "revenue": ["NetSales", "NetSalesIFRS", "TotalNetRevenuesIFRS", "OperatingRevenuesIFRS",
                "NetSalesSummaryOfBusinessResults", "NetSalesIFRSSummaryOfBusinessResults"],
    "total_assets": ["Assets", "AssetsIFRS", "TotalAssetsSummaryOfBusinessResults", "TotalAssetsIFRSSummaryOfBusinessResults"],
    "equity": ["StockholdersEquity", "EquityIFRS", "TotalStockholdersEquity"],
    "liabilities": ["Liabilities", "LiabilitiesIFRS"],
    "current_liabilities": ["CurrentLiabilities", "CurrentLiabilitiesIFRS"],
    "cash": ["CashAndCashEquivalents", "CashAndDeposits", "CashAndCashEquivalentsIFRS"],
    "inventory": ["Inventories", "InventoriesIFRS"],
    "net_income": ["NetIncomeLoss", "ProfitLossIFRS", "NetIncomeLossSummaryOfBusinessResults"],
    "employees": ["NumberOfEmployees"],
    "cogs": ["CostOfSales", "CostOfSalesIFRS"],
}
LOCAL2FIELD = {l: f for f, ls in FIN_LOCAL.items() for l in ls}

def ctx_rank(ctx):
    """CurrentYear連結が最優先、セグメント文脈と単体・前期は格下げ."""
    if ctx in ("CurrentYearDuration", "CurrentYearInstant"):
        return 3
    if ctx.startswith("CurrentYear") and "NonConsolidated" not in ctx and "jpcrp" not in ctx:
        return 2
    if ctx.startswith("CurrentYear"):
        return 1
    return 0

def extract_financials(rows):
    best = {}  # field -> (rank, value)
    for p in rows:
        tag, ctx, val = p[0], p[2], p[8]
        if "TextBlock" in tag: continue
        local = tag.split(":")[-1]
        field = LOCAL2FIELD.get(local)
        if not field: continue
        v = num(val)
        if v is None: continue
        r = ctx_rank(ctx)
        if field not in best or r > best[field][0]:
            best[field] = (r, v)
    return {f: v for f, (r, v) in best.items()}

def main():
    files = sorted(os.listdir(CSVDIR))
    n_sh = n_af = n_fin = 0
    fsh = open(f"{OUT}/edinet_shareholders.jsonl", "w")
    faf = open(f"{OUT}/edinet_affiliates.jsonl", "w")
    ffn = open(f"{OUT}/edinet_financials.jsonl", "w")
    for fn in files:
        try:
            z = zipfile.ZipFile(f"{CSVDIR}/{fn}")
            rows = get_file_rows(z)
            if not rows: continue
            doc_id = fn.replace(".zip", "")
            base = None
            for p in rows:
                if p[0].endswith("FilingDateInstant") and "CoverPage" in p[0]:
                    pass
            # EDINETコードはファイル名から
            sh = extract_shareholders(rows)
            for s in sh:
                if s.get("name"):
                    fsh.write(json.dumps({"doc_id": doc_id, **s}, ensure_ascii=False) + "\n"); n_sh += 1
            try:
                af, raw_text = extract_affiliates(rows)
                for a in af:
                    if a.get("name"):
                        faf.write(json.dumps({"doc_id": doc_id, **a}, ensure_ascii=False) + "\n"); n_af += 1
            except ValueError:
                pass
            fin = extract_financials(rows)
            if fin:
                ffn.write(json.dumps({"doc_id": doc_id, **fin}, ensure_ascii=False) + "\n"); n_fin += 1
        except Exception as e:
            print("ERR", fn, str(e)[:60], file=sys.stderr)
    for f in (fsh, faf, ffn): f.close()
    print(f"files={len(files)} shareholders={n_sh} affiliates={n_af} financials={n_fin}")

if __name__ == "__main__":
    main()
