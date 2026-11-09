#!/usr/bin/env python3
"""Export a compact, source-aware RIPPLE research snapshot from cybermap.sqlite.

Inputs stay unchanged. Run from any directory with Python, numpy and pyshp installed:
    python3 scripts/export_workbench.py
The output contains public listed-company identity/sector fields and reported
relationship provenance; it deliberately omits market values, financial amounts,
personal data, and guessed firm procurement dependencies.
"""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import struct
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import shapefile

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "db/cybermap.sqlite"
ICIO = ROOT / "data/icio2020_coeff.npz"
MAP_ZIP = ROOT / "raw/assets/ne_110m_admin_0_countries.zip"
LEGACY_GRAPH = ROOT / "archive/legacy-3d/data/graph.json"
OUT = ROOT / "viz/public/data"

SECTOR_TO_ICIO = {
    "食品": "C10T12", "医薬品": "C21", "情報通信・サービスその他": "J62_63",
    "運輸・物流": "H49", "小売": "G", "不動産": "L", "建設・資材": "F",
    "鉄鋼・非鉄": "C24", "エネルギー資源": "B07_08", "商社・卸売": "G",
    "金融（除く銀行）": "K", "素材・化学": "C20", "機械": "C28",
    "電機・精密": "C27", "自動車・輸送機": "C29", "電力・ガス": "D", "銀行": "K",
}
INDUSTRY_JA = {
    "A01_02": "農業・林業", "A03": "漁業", "B05_06": "石炭・原油・天然ガス",
    "B07_08": "金属鉱物等の採掘", "B09": "その他採掘", "C10T12": "食品・飲料",
    "C13T15": "繊維・衣服・皮革", "C16": "木材・木製品", "C17_18": "紙・印刷",
    "C19": "石油・石炭製品", "C20": "化学製品", "C21": "医薬品",
    "C22": "ゴム・プラスチック", "C23": "非金属鉱物製品", "C24": "基礎金属",
    "C25": "金属製品", "C26": "コンピュータ・電子製品", "C27": "電気機器",
    "C28": "機械", "C29": "自動車", "C30": "その他輸送機器",
    "C31T33": "その他製造・修理", "D": "電気・ガス", "E": "水道・廃棄物",
    "F": "建設", "G": "卸売・小売", "H49": "陸運・パイプライン",
    "H50": "水運", "H51": "航空運輸", "H52": "倉庫・輸送支援", "H53": "郵便・配達",
    "I": "宿泊・飲食", "J58T60": "出版・放送・映像", "J61": "通信",
    "J62_63": "IT・情報サービス", "K": "金融・保険", "L": "不動産",
    "M69T75": "専門・科学・技術", "M77T82": "事業支援サービス", "N": "行政・防衛",
    "O84": "公務・社会保障", "P85": "教育", "Q": "保健・社会福祉",
    "Q86T88": "保健・福祉", "R": "文化・娯楽", "R90T93": "芸術・娯楽",
    "S": "その他サービス", "S94T96": "その他サービス", "T": "家事サービス",
    "U": "域外組織",
}


def dump_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_world() -> tuple[int, str]:
    if not MAP_ZIP.is_file():
        raise FileNotFoundError(f"Natural Earth archive not found: {MAP_ZIP}")
    with zipfile.ZipFile(MAP_ZIP) as archive:
        parts = {Path(name).suffix.lower(): archive.read(name) for name in archive.namelist()
                 if Path(name).suffix.lower() in {".shp", ".shx", ".dbf"}}
    reader = shapefile.Reader(shp=io.BytesIO(parts[".shp"]),
                              shx=io.BytesIO(parts[".shx"]),
                              dbf=io.BytesIO(parts[".dbf"]))
    features = []
    for record in reader.iterShapeRecords():
        source = record.record.as_dict()
        code = source.get("ISO_A3_EH") or source.get("ADM0_A3") or ""
        if code == "-99":
            code = source.get("ADM0_A3") or ""
        shape = record.shape.__geo_interface__
        if shape.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        features.append({
            "type": "Feature",
            "id": code,
            "properties": {
                "iso3": str(code),
                "name": source.get("NAME_EN") or source.get("NAME") or "",
                "nameJa": source.get("NAME_JA") or "",
                "boundaryBasis": "Natural Earth Admin 0; de facto representation",
            },
            "geometry": shape,
        })
    payload = {"type": "FeatureCollection", "features": features}
    return len(features), dump_json(OUT / "world.geojson", payload)


def export_ownership_layout(company_ids: set[str], ownership_records: list[dict[str, object]]) -> tuple[int, str, dict[str, int]]:
    """Project only the archived 3D display coordinates to a stable 2D PCA layout.

    Company identity and ownership evidence are exported independently above. The
    legacy display's market values, size, colors and edge payload are not used here.
    The resulting coordinates have no geographic or economic interpretation.
    """
    if not LEGACY_GRAPH.is_file():
        raise FileNotFoundError(f"Archived mesh layout not found: {LEGACY_GRAPH}")
    graph = json.loads(LEGACY_GRAPH.read_text(encoding="utf-8"))
    source_nodes = graph.get("nodes", [])
    source_edges = graph.get("edges", [])
    by_id: dict[str, dict[str, object]] = {}
    for node in source_nodes:
        node_id = str(node.get("id", ""))
        if not node_id or node_id in by_id:
            raise ValueError("Archived mesh has an empty or duplicate company id")
        by_id[node_id] = node
    if set(by_id) != company_ids:
        missing = company_ids - set(by_id)
        extra = set(by_id) - company_ids
        raise ValueError(f"Archived mesh/company IDs differ (missing={len(missing)}, extra={len(extra)})")

    archived_pairs = {(str(edge["src"]), str(edge["dst"])) for edge in source_edges}
    ownership_pairs = {(str(edge["src_id"]), str(edge["dst_id"])) for edge in ownership_records}
    if archived_pairs != ownership_pairs:
        raise ValueError("Archived mesh ownership pairs no longer match the current ownership snapshot")
    visible_pairs = {pair for pair in ownership_pairs if pair[0] in company_ids and pair[1] in company_ids}
    visible_records = sum(1 for edge in ownership_records if (str(edge["src_id"]), str(edge["dst_id"])) in visible_pairs)
    relationship_counts = {
        "legacyMeshRelationshipRecords": len(source_edges),
        "ownershipUniquePairs": len(ownership_pairs),
        "ownershipMeshVisiblePairs": len(visible_pairs),
        "ownershipMeshOutOfMeshPairs": len(ownership_pairs - visible_pairs),
        "ownershipMeshVisibleEvidenceRecords": visible_records,
    }

    ordered_ids = sorted(company_ids)
    coordinates = np.asarray(
        [[float(by_id[company_id][axis]) for axis in ("x", "y", "z")] for company_id in ordered_ids],
        dtype=np.float64,
    )
    if coordinates.ndim != 2 or coordinates.shape != (len(ordered_ids), 3):
        raise ValueError("Archived mesh must provide three display coordinates for every company")
    if not np.isfinite(coordinates).all():
        raise ValueError("Archived mesh display coordinates must be finite")

    centered = coordinates - coordinates.mean(axis=0)
    _, singular_values, components = np.linalg.svd(centered, full_matrices=False)
    if len(singular_values) < 2 or singular_values[1] <= 1e-12:
        raise ValueError("Archived mesh does not span a 2D projection")
    projected = centered @ components[:2].T
    # PCA signs are arbitrary. Fix each component's dominant source axis so the
    # same inputs produce the same left/right and top/bottom orientation.
    for component_index in range(2):
        dominant_axis = int(np.argmax(np.abs(components[component_index])))
        if components[component_index, dominant_axis] < 0:
            projected[:, component_index] *= -1

    layout = [
        {"id": company_id, "x": round(float(point[0]), 8), "y": round(float(point[1]), 8)}
        for company_id, point in zip(ordered_ids, projected, strict=True)
    ]
    return len(layout), dump_json(OUT / "ownership-layout.json", layout), relationship_counts


def main() -> None:
    if not DB.is_file() or not ICIO.is_file():
        raise FileNotFoundError("Expected db/cybermap.sqlite and data/icio2020_coeff.npz")
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in ("trade-flows.json", "commodities.json", "routes.json"):
        (OUT / stale).unlink(missing_ok=True)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    hashes: dict[str, str] = {}

    ticks = {r["company_id"]: r["id_value"] for r in conn.execute(
        "SELECT company_id,id_value FROM id_map WHERE id_type='ticker' AND company_id IN (SELECT company_id FROM company WHERE layer='F_jp')")}
    fcounts = {r["company_id"]: r["n"] for r in conn.execute(
        "SELECT company_id,count(*) AS n FROM financials WHERE source_tier=1 GROUP BY company_id")}
    rows = conn.execute("""SELECT company_id,legal_name,sector_j33,listing_status,country
                           FROM company WHERE layer='F_jp' ORDER BY legal_name,company_id""").fetchall()
    companies = []
    for r in rows:
        sector = r["sector_j33"] or ""
        io_industry = SECTOR_TO_ICIO.get(sector)
        companies.append({
            "id": r["company_id"], "name": r["legal_name"], "ticker": ticks.get(r["company_id"]),
            "sector": sector or None, "listingStatus": r["listing_status"],
            "country": r["country"], "industryNode": f"JPN_{io_industry}" if io_industry else None,
            "tier1FinancialRecordCount": fcounts.get(r["company_id"], 0),
        })
    hashes["companies.json"] = dump_json(OUT / "companies.json", companies)
    rels = [dict(r) for r in conn.execute("""SELECT edge_id,src_id,dst_id,relation_type,share_pct,
                dependency_status,as_of,source_tier,source_ref,extraction,confidence
                FROM relation WHERE src_id IN (SELECT company_id FROM company WHERE layer IN ('F_jp','F_border'))
                AND dst_id IN (SELECT company_id FROM company WHERE layer IN ('F_jp','F_border'))
                ORDER BY edge_id""")]
    layout_count, hashes["ownership-layout.json"], ownership_mesh_counts = export_ownership_layout(
        {company["id"] for company in companies}, rels
    )
    # Ownership is observable; it is never re-labeled as a sales or procurement edge.
    hashes["ownership.json"] = dump_json(OUT / "ownership.json", rels)

    with np.load(ICIO, allow_pickle=False) as source:
        sellers = source["sellers"].astype(str)
        buyers = source["buyers"].astype(str)
        s = source["s"].astype(np.int64)
        b = source["b"].astype(np.int64)
        v = source["v"].astype(np.float32)
    if not (len(s) == len(b) == len(v)):
        raise ValueError("ICIO sparse arrays have mismatched lengths")
    if np.any(s < 0) or np.any(s >= len(sellers)) or np.any(b < 0) or np.any(b >= len(buyers)):
        raise ValueError("ICIO sparse index outside its labelled node list")
    production_names = set(sellers.tolist())
    node_names = sorted(production_names | set(buyers.tolist()))
    if len(node_names) >= 65535:
        raise ValueError("Compact flow index exceeds uint16 capacity")
    ids = {name: i for i, name in enumerate(node_names)}
    flow_dtype = np.dtype([("buyer", "<u2"), ("seller", "<u2"), ("coefficient", "<f4")])
    flows = np.empty(len(v), dtype=flow_dtype)
    flows["buyer"] = np.fromiter((ids[x] for x in buyers[b]), dtype=np.uint16, count=len(b))
    flows["seller"] = np.fromiter((ids[x] for x in sellers[s]), dtype=np.uint16, count=len(s))
    flows["coefficient"] = v
    flow_path = OUT / "icio2020-flows.bin"
    flows.tofile(flow_path)
    hashes[flow_path.name] = hashlib.sha256(flow_path.read_bytes()).hexdigest()

    nodes = []
    for key in node_names:
        country, _, industry = key.partition("_")
        nodes.append({"id": key, "country": country, "industry": industry,
                      "industryJa": INDUSTRY_JA.get(industry, industry),
                      "isRow": country == "ROW", "isFinalDemand": key not in production_names})
    hashes["industries.json"] = dump_json(OUT / "industries.json", nodes)

    # Port points are individually attributed public facts in this source snapshot.
    # Trade rows, route summaries, and commodity time series stay out of the public
    # app bundle until the exact source-level permission and intended public-use case
    # are reviewed. They are not inputs to the currently implemented engine.
    ports = [dict(r) for r in conn.execute("SELECT port_id,name,country,lat,lon,teu_annual,source FROM port ORDER BY country,port_id")]
    hashes["ports.json"] = dump_json(OUT / "ports.json", ports)
    route_count = conn.execute("SELECT count(*) FROM shipping_route").fetchone()[0]
    trade_count = conn.execute("SELECT count(*) FROM trade_flows").fetchone()[0]
    commodity_count = conn.execute("SELECT count(*) FROM commodity_price").fetchone()[0]

    financial_rows = conn.execute("SELECT count(*) FROM financials").fetchone()[0]
    tier1_firms = conn.execute("SELECT count(DISTINCT company_id) FROM financials WHERE source_tier=1").fetchone()[0]
    relation_by_status = {r["dependency_status"]: r["n"] for r in conn.execute(
        "SELECT dependency_status,count(*) AS n FROM relation GROUP BY dependency_status")}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    world_count, hashes["world.geojson"] = export_world()
    manifest = {
        "schemaVersion": "1.1.0", "generatedAt": now,
        "datasetSnapshot": "cyber-economy-map@81379cdd8996dfe3c567a80f0737a3cc160a981b",
        "boundaryVintage": "Natural Earth 1:110m Admin 0; de facto representation",
        "ioModelDefinition": {
            "source": "OECD ICIO 2023 release, 2020 year; source recorded in the originating database",
            "coefficient": "a[seller,buyer] = Z[seller,buyer] / sum_s Z[s,buyer]; the denominator is the buyer's total intermediate inputs",
            "includedSparseCoefficientMinimum": 0.0005,
            "terminalDemandColumns": "Six final-demand columns per country are transmission sinks, not production industries; excluded from industry rankings and country exposure.",
            "countryAggregation": "Within each sensitivity draw, the unweighted arithmetic mean across represented affected production sectors; not a monetary or GDP loss estimate.",
        },
        "counts": {
            "japanListedCompanies": len(companies), "ownershipRelationships": len(rels),
            "ownershipLayoutNodes": layout_count,
            **ownership_mesh_counts,
            "relationshipsByStatus": relation_by_status, "ioNodes": len(production_names),
            "geographicProductionNodes": sum(key.partition("_")[0] != "ROW" for key in production_names),
            "ioTerminalDemandNodes": len(node_names) - len(production_names),
            "ioFlows": len(flows), "financialRecords": financial_rows,
            "tier1FinancialCompanies": tier1_firms, "bilateralTradeFlowsReviewOnly": trade_count,
            "ports": len(ports), "shippingRouteRowsReviewOnly": route_count,
            "commodityObservationsReviewOnly": commodity_count,
            "worldBoundaryFeatures": world_count,
        },
        "dataCatalog": [
            {"id": "jpx-listed", "label": "Japan-listed company master", "period": "Repository snapshot; source as recorded in DB", "source": "https://www.jpx.co.jp/english/term-of-use/index.html", "license": "JPX terms prohibit commercial collection or secondary use without permission; these rows are not Apache-2.0 data", "role": "Company identity, ticker and broad sector only; no modeled trade or loss"},
            {"id": "edinet", "label": "EDINET corporate filings", "period": "Per record; see source DB", "source": "https://disclosure2.edinet-fsa.go.jp/", "license": "EDINET Terms of Use / Digital Agency PDL 1.0: attribute, identify edits and author; API access required", "role": "Some reported relationship records and finance-record coverage counts; filing values are not propagated"},
            {"id": "wikidata", "label": "Wikidata", "period": "As recorded in source DB", "source": "https://www.wikidata.org/", "license": "CC0 for structured data", "role": "Some ownership relationships; relation status and confidence retained"},
            {"id": "legacy-mesh-layout", "label": "Archived corporate-mesh display coordinates", "period": "Display layout only; no time-series vintage", "source": "archive/legacy-3d/data/graph.json", "license": "Derived layout only; original source and dataset terms still apply, with no additional data license implied", "role": "Reads only entity ID and x/y/z display coordinates, then projects them to the first two principal components. The archived 5,836 relation records contain 5,573 distinct pairs; only 2,002 pairs have both listed-company endpoints in the 3,893-node layout. The other 3,571 pairs are off-mesh and are not assigned invented coordinates. Does not export legacy market values, node sizes, edge payload or colors; not geographic or economic coordinates."},
            {"id": "icio", "label": "OECD ICIO 2020 table", "period": "2020; edition/vintage described in the source database", "source": "https://www.oecd.org/en/data/datasets/inter-country-input-output-tables.html", "license": "OECD Terms & Conditions permit data use subject to any dataset-specific or third-party restrictions; cite the exact dataset", "role": "International country-by-industry input share proxy; not firm procurement"},
            {"id": "comtrade", "label": "UN Comtrade bilateral flows", "period": "2023, selected Japanese trade flows", "source": "https://uncomtrade.org/docs/re-dissemination-of-data/", "license": "Original row data intentionally not shipped in the public app bundle; data policy applies", "role": "758 repository rows reviewed for coverage only; not used as a firm or route edge"},
            {"id": "pink-sheet", "label": "World Bank commodity-price series", "period": "2016-2024 in the source DB", "source": "https://www.worldbank.org/en/research/commodity-markets", "license": "Not exported to the app bundle; verify World Bank dataset terms before use", "role": "Historical series is not connected to this engine"},
            {"id": "natural-earth", "label": "Natural Earth Admin 0 country boundaries", "period": "Natural Earth release bundled in raw/assets", "source": "https://www.naturalearthdata.com/about/terms-of-use/", "license": "Public domain per Natural Earth terms of use", "role": "Country outline / choropleth geometry; not a supply route layer"},
            {"id": "route-port", "label": "Six Japanese port reference points; shipping-route records", "period": "Per source note in DB", "source": "Source authority or report named in the row; see DB `port` table", "license": "Port facts are attributed per record; route aggregates are not exported until each source is reviewed", "role": "Ports are only geographic markers; no company, shipment, industry or route exposure is inferred"},
        ],
        "checksumsSha256": hashes,
        "exclusions": ["No market capitalization or monetary loss estimate is exported.",
                       "Ownership links are never treated as procurement, revenue-share or credit links.",
                       "Unknown company dependencies remain unknown.",
                       "758 selected UN Comtrade rows, 1,835 World Bank commodity price observations, and six aggregate route records are withheld from the static app bundle pending source-specific review.",
                       "The DB currently has no company-to-port link, facility layer, country-risk series or macro FX/rate series.",
                       "The company-mesh edges are ownership relations only and are never used to transmit scenario shocks; only pairs with both endpoints in the listed-company display population are drawn, while off-mesh endpoints remain undisplayed.",
                       "Within the company-mesh dataset, repeated source records for the same directed company pair remain separate in the evidence table but are drawn as one unique relation."],
    }
    hashes["manifest.json"] = dump_json(OUT / "manifest.json", manifest)
    conn.close()
    print(json.dumps({"out": str(OUT), "counts": manifest["counts"], "files": hashes}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
