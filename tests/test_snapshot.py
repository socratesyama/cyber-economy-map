from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "viz/public/data"


class PublicSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))

    def test_manifest_sha256_entries_match_exported_payloads(self) -> None:
        for filename, expected in self.manifest["checksumsSha256"].items():
            actual = hashlib.sha256((DATA / filename).read_bytes()).hexdigest()
            self.assertEqual(expected, actual, filename)

    def test_production_and_final_demand_nodes_remain_separate(self) -> None:
        nodes = json.loads((DATA / "industries.json").read_text(encoding="utf-8"))
        production = [node for node in nodes if not node["isFinalDemand"]]
        terminal = [node for node in nodes if node["isFinalDemand"]]
        self.assertEqual(len(production), 3465)
        self.assertEqual(sum(not node["isRow"] for node in production), 3420)
        self.assertEqual(len(terminal), 462)
        self.assertEqual(self.manifest["counts"]["ioNodes"], 3465)
        self.assertEqual(len(production), self.manifest["counts"]["ioNodes"])
        self.assertEqual(sum(not node["isRow"] for node in production), self.manifest["counts"]["geographicProductionNodes"])
        self.assertEqual(self.manifest["counts"]["geographicProductionNodes"], 3420)
        self.assertEqual(self.manifest["counts"]["ioTerminalDemandNodes"], 462)
        self.assertEqual(self.manifest["ioModelDefinition"]["includedSparseCoefficientMinimum"], 0.0005)

    def test_2d_mesh_layout_is_a_finite_display_only_projection_for_listed_companies(self) -> None:
        layout = json.loads((DATA / "ownership-layout.json").read_text(encoding="utf-8"))
        companies = json.loads((DATA / "companies.json").read_text(encoding="utf-8"))
        self.assertEqual(len(layout), 3893)
        self.assertEqual(len(layout), self.manifest["counts"]["ownershipLayoutNodes"])
        self.assertEqual(len(layout), self.manifest["counts"]["japanListedCompanies"])
        self.assertEqual({point["id"] for point in layout}, {company["id"] for company in companies})
        self.assertTrue(all(np.isfinite([point["x"], point["y"]]).all() for point in layout))
        self.assertTrue(all(set(point) == {"id", "x", "y"} for point in layout))
        ownership = json.loads((DATA / "ownership.json").read_text(encoding="utf-8"))
        company_ids = {company["id"] for company in companies}
        ownership_pairs = {(edge["src_id"], edge["dst_id"]) for edge in ownership}
        visible_pairs = {(src, dst) for src, dst in ownership_pairs if src in company_ids and dst in company_ids}
        legacy = json.loads((ROOT / "archive/legacy-3d/data/graph.json").read_text(encoding="utf-8"))
        legacy_pairs = {(edge["src"], edge["dst"]) for edge in legacy["edges"]}
        self.assertEqual(ownership_pairs, legacy_pairs)
        self.assertEqual(len(ownership), 5836)
        self.assertEqual(len(ownership_pairs), 5573)
        self.assertEqual(len(visible_pairs), 2002)
        source = next(row for row in self.manifest["dataCatalog"] if row["id"] == "legacy-mesh-layout")
        self.assertIn("not geographic", source["role"])
        self.assertIn("first two principal components", source["role"])
        self.assertIn("legacy market values", source["role"])
        self.assertEqual(self.manifest["counts"]["ownershipRelationships"], 5836)
        self.assertEqual(self.manifest["counts"]["legacyMeshRelationshipRecords"], 5836)
        self.assertEqual(self.manifest["counts"]["ownershipUniquePairs"], 5573)
        self.assertEqual(self.manifest["counts"]["ownershipMeshVisiblePairs"], 2002)
        self.assertEqual(self.manifest["counts"]["ownershipMeshOutOfMeshPairs"], 3571)

    def test_sparse_flows_are_unique_finite_and_within_labelled_indices(self) -> None:
        nodes = json.loads((DATA / "industries.json").read_text(encoding="utf-8"))
        flows = np.fromfile(DATA / "icio2020-flows.bin", dtype=np.dtype([
            ("buyer", "<u2"), ("seller", "<u2"), ("coefficient", "<f4")
        ]))
        self.assertEqual(len(flows), self.manifest["counts"]["ioFlows"])
        self.assertTrue(np.all(flows["buyer"] < len(nodes)))
        self.assertTrue(np.all(flows["seller"] < len(nodes)))
        self.assertTrue(np.all(np.isfinite(flows["coefficient"])))
        self.assertTrue(np.all(flows["coefficient"] >= 0))
        pairs = np.stack((flows["buyer"], flows["seller"]), axis=1)
        self.assertEqual(len(np.unique(pairs, axis=0)), len(flows), "duplicate flow cell would be counted twice")

    def test_unapproved_unused_raw_series_are_not_in_public_bundle(self) -> None:
        for name in ("trade-flows.json", "commodities.json", "routes.json"):
            self.assertFalse((DATA / name).exists(), name)
        self.assertIn("bilateralTradeFlowsReviewOnly", self.manifest["counts"])
        self.assertIn("commodityObservationsReviewOnly", self.manifest["counts"])

    def test_manifest_keeps_company_links_distinct_from_trade(self) -> None:
        catalog = {row["id"]: row for row in self.manifest["dataCatalog"]}
        self.assertIn("not firm procurement", catalog["icio"]["role"].lower())
        self.assertIn("Apache-2.0", catalog["jpx-listed"]["license"])
        self.assertIn("no modeled trade", catalog["jpx-listed"]["role"])


if __name__ == "__main__":
    unittest.main()
