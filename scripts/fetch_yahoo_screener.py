#!/usr/bin/env python3
"""Fetch all JPX-listed equities via Yahoo screener (bulk, 250/page)."""
import json, time, yfinance as yf

out_path = "../data/yahoo_screener.jsonl"
q = yf.EquityQuery('eq', ['exchange','JPX'])
seen = {}
offset = 0
page = 1
while True:
    try:
        res = yf.screen(q, size=250, sortField='intradaymarketcap', sortAsc=False, offset=offset)
    except Exception as e:
        print(f"page {page} error: {e}; retry once after 30s")
        time.sleep(30)
        try:
            res = yf.screen(q, size=250, sortField='intradaymarketcap', sortAsc=False, offset=offset)
        except Exception as e2:
            print(f"page {page} failed twice: {e2}"); break
    quotes = res.get('quotes', [])
    if not quotes: break
    for qt in quotes:
        sym = qt.get('symbol')
        if sym and sym not in seen:
            seen[sym] = qt
    print(f"page {page}: +{len(quotes)} (unique {len(seen)}) total={res.get('total')}", flush=True)
    offset += len(quotes)
    if offset >= res.get('total', 0): break
    page += 1
    time.sleep(3)
with open(out_path, 'w') as f:
    for sym, qt in seen.items():
        f.write(json.dumps(qt, default=str) + "\n")
print("saved", len(seen), "->", out_path)
