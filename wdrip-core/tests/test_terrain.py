"""Sprint 1.4 — 地形适配测试"""

import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wdrip.network import DripNetwork, SourceNode, Junction, EmitterNode, Pipe
from wdrip.terrain import (
    TerrainAdapter, DemReader,
    SlopeAnalyzer, PressureZoneAnalyzer, PrvRecommender,
)


class TestDemReader(unittest.TestCase):
    """1.4.1 DEM 读取测试"""

    def test_csv_fallback(self):
        """无 rasterio 时回退到 CSV 模式"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("x,y,elevation\n")
            f.write("0,0,100\n")
            f.write("10,0,105\n")
            f.write("0,10,95\n")
            csv_path = f.name
        
        try:
            reader = DemReader(csv_path)
            success = reader.open()
            self.assertTrue(success)
        finally:
            os.unlink(csv_path)

    def test_invalid_file(self):
        """无效文件应优雅报错"""
        reader = DemReader("/nonexistent/dem.tif")
        success = reader.open()
        self.assertFalse(success)


class TestTerrainAdapter(unittest.TestCase):
    """1.4.1 TerrainAdapter 测试"""

    def setUp(self):
        self.net = DripNetwork("test")
        self.net.add_node(SourceNode("S001", 0, 0, elevation=100))
        self.net.add_node(Junction("J001", 10, 10, elevation=105))
        self.net.add_node(Junction("J002", 20, 20, elevation=95))
        self.net.add_link(Pipe("P001", "S001", "J001"))

    def test_no_dem_returns_empty(self):
        adapter = TerrainAdapter()
        result = adapter.extract_elevations(self.net)
        self.assertEqual(result, {})

    def test_load_dem_failure(self):
        adapter = TerrainAdapter()
        success = adapter.load_dem("/nonexistent.tif")
        self.assertFalse(success)


class TestSlopeAnalyzer(unittest.TestCase):
    """1.4.2 坡度计算测试"""

    def setUp(self):
        self.net = DripNetwork("test")
        self.net.add_node(Junction("J001", 0, 0, elevation=100))
        self.net.add_node(Junction("J002", 10, 0, elevation=110))
        self.net.add_node(Junction("J003", 20, 0, elevation=90))
        self.net.add_link(Pipe("P001", "J001", "J002", length=100))
        self.net.add_link(Pipe("P002", "J002", "J003", length=100))

    def test_uphill_slope(self):
        results = SlopeAnalyzer().analyze(self.net)
        p001 = [r for r in results if r.link_id == "P001"][0]
        self.assertAlmostEqual(p001.slope_percent, 10.0)  # 10m / 100m = 10%
        self.assertTrue(p001.is_uphill)

    def test_downhill_slope(self):
        results = SlopeAnalyzer().analyze(self.net)
        p002 = [r for r in results if r.link_id == "P002"][0]
        self.assertAlmostEqual(p002.slope_percent, -20.0)  # -20m / 100m = -20%
        self.assertFalse(p002.is_uphill)

    def test_steep_detection(self):
        results = SlopeAnalyzer().analyze(self.net)
        p002 = [r for r in results if r.link_id == "P002"][0]
        self.assertTrue(p002.is_steep)  # 20% > 10%

    def test_summary(self):
        results = SlopeAnalyzer().analyze(self.net)
        summary = SlopeAnalyzer().get_summary(results)
        self.assertEqual(summary["total_links"], 2)
        self.assertGreater(summary["max_slope"], 0)


class TestPressureZoneAnalyzer(unittest.TestCase):
    """1.4.3 压力分区测试"""

    def test_single_zone(self):
        net = DripNetwork("test")
        net.add_node(Junction("J001", 0, 0, elevation=100))
        net.add_node(Junction("J002", 10, 0, elevation=105))
        net.add_node(Junction("J003", 20, 0, elevation=102))
        
        zones = PressureZoneAnalyzer(max_elevation_range=10).analyze(net)
        self.assertEqual(len(zones), 1)

    def test_multiple_zones(self):
        net = DripNetwork("test")
        net.add_node(Junction("J001", 0, 0, elevation=100))
        net.add_node(Junction("J002", 10, 0, elevation=120))  # +20m
        net.add_node(Junction("J003", 20, 0, elevation=80))   # -20m
        
        zones = PressureZoneAnalyzer(max_elevation_range=10).analyze(net)
        self.assertGreater(len(zones), 1)


class TestPrvRecommender(unittest.TestCase):
    """1.4.4 PRV 推荐测试"""

    def test_recommend_on_steep_downhill(self):
        net = DripNetwork("test")
        net.add_node(Junction("J001", 0, 0, elevation=200))
        net.add_node(Junction("J002", 10, 0, elevation=100))
        net.add_link(Pipe("P001", "J001", "J002", length=100))
        
        slopes = SlopeAnalyzer().analyze(net)
        recs = PrvRecommender(max_pressure_drop=30).recommend(net, slopes)
        self.assertGreater(len(recs), 0)
        self.assertEqual(recs[0].position_node, "J001")  # 上游节点

    def test_flat_terrain_no_recommendation(self):
        net = DripNetwork("test")
        net.add_node(Junction("J001", 0, 0, elevation=100))
        net.add_node(Junction("J002", 10, 0, elevation=101))
        net.add_link(Pipe("P001", "J001", "J002", length=100))
        
        slopes = SlopeAnalyzer().analyze(net)
        recs = PrvRecommender(max_pressure_drop=30).recommend(net, slopes)
        self.assertEqual(len(recs), 0)


if __name__ == "__main__":
    unittest.main()
