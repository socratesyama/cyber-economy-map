#!/usr/bin/env python3
"""Download EDINET XBRL CSV documents without putting the API key in a URL."""
from __future__ import annotations

import concurrent.futures
import json
import os
import pathlib
import urllib.parse
import urllib.request

KEY = os.environ.get("EDINET_API_KEY") or os.environ.get("EDINET_KEY")
if not KEY:
    raise SystemExit("Set EDINET_API_KEY through a protected environment mechanism.")

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/edinet_yuho_index.json"
OUTPUT = ROOT / "raw/edinet/csv"
OUTPUT.mkdir(parents=True, exist_ok=True)
index = json.loads(INDEX.read_text(encoding="utf-8"))
todo = [(doc_id, record) for record in index.values()
        if (doc_id := record.get("docID")) and not (OUTPUT / f"{doc_id}.zip").exists()]
print("documents queued:", len(todo), flush=True)


def download(item: tuple[str, dict]) -> tuple[str, str]:
    doc_id, _record = item
    query = urllib.parse.urlencode({"type": 5})
    url = f"https://api.edinet-fsa.go.jp/api/v2/documents/{doc_id}?{query}"
    request = urllib.request.Request(
        url,
        headers={"Ocp-Apim-Subscription-Key": KEY, "User-Agent": "CyberEconomyMap/0.2"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            (OUTPUT / f"{doc_id}.zip").write_bytes(response.read())
        return doc_id, "ok"
    except Exception as error:
        # Error bodies and URL strings may contain private request details; print only status type.
        code = getattr(error, "code", None)
        return doc_id, f"http-{code}" if code else type(error).__name__


completed = 0
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    for document_id, status in pool.map(download, todo):
        completed += 1
        if status != "ok":
            print(document_id, status, flush=True)
        if completed % 50 == 0:
            print(f"progress: {completed}/{len(todo)}", flush=True)
print("complete:", completed, flush=True)
