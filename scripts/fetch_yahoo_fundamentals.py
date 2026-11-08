#!/usr/bin/env python3
"""Fetch fundamental data (market cap, revenue, employees, etc.) for all JPX-listed
domestic stocks from Yahoo Finance via yfinance. Resumable via JSONL append."""
import csv, json, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf

DATA = "../data"
FIELDS = ["shortName","longName","marketCap","totalRevenue","fullTimeEmployees",
          "currentRatio","quickRatio","debtToEquity","returnOnAssets","returnOnEquity",
          "country","sector","industry","website","currency","financialCurrency",
          "totalCash","totalDebt","freeCashflow","profitMargins"]

def load_done(path):
    done = set()
    try:
        with open(path) as f:
            for line in f:
                try: done.add(json.loads(line)["ticker"])
                except Exception: pass
    except FileNotFoundError:
        pass
    return done

def main():
    tickers = []
    with open(f"{DATA}/jpx_nodes_raw.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tickers.append(row["ticker"])
    out_path = f"{DATA}/yahoo_fundamentals.jsonl"
    done = load_done(out_path)
    todo = [t for t in tickers if t not in done]
    print(f"total={len(tickers)} done={len(done)} todo={len(todo)}", flush=True)
    lock_write = open(out_path, "a")
    def fetch(tk):
        try:
            info = yf.Ticker(tk).info or {}
            rec = {"ticker": tk, "fetchedAt": time.strftime("%Y-%m-%d")}
            for k in FIELDS:
                rec[k] = info.get(k)
            return rec, None
        except Exception as e:
            return None, str(e)
    n_ok = n_err = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fetch, tk): tk for tk in todo}
        for i, fut in enumerate(as_completed(futs)):
            rec, err = fut.result()
            if rec and (rec.get("marketCap") or rec.get("totalRevenue")):
                lock_write.write(json.dumps(rec, ensure_ascii=False) + "\n"); lock_write.flush(); n_ok += 1
            else:
                n_err += 1
            if (i+1) % 250 == 0:
                print(f"{i+1}/{len(todo)} ok={n_ok} err={n_err}", flush=True)
    lock_write.close()
    print(f"FINISHED ok={n_ok} err={n_err}")

if __name__ == "__main__":
    main()
