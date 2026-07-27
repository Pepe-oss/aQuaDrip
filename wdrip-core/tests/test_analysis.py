"""Sprint 1.7 — 结果分析器测试"""

import os, sys, math
import numpy as np
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wdrip.analysis import (
    UniformityAnalyzer,
    FertigationAnalyzer,
    CalibrationAnalyzer,
)
from wdrip.network import DripNetwork, SourceNode, Junction, Pipe


class TestUniformityAnalyzer(unittest.TestCase):
    """1.7.1 均匀度测试"""
    
    def test_cu_perfect(self):
        flows = np.array([2.0, 2.0, 2.0, 2.0, 2.0])
        self.assertEqual(UniformityAnalyzer.cu(flows), 100.0)
    
    def test_cu_with_variation(self):
        flows = np.array([2.0, 1.9, 2.0, 1.8, 2.0])
        cu = UniformityAnalyzer.cu(flows)
        self.assertLess(cu, 100.0)
        self.assertGreater(cu, 90.0)
    
    def test_cu_empty(self):
        self.assertEqual(UniformityAnalyzer.cu(np.array([])), 0.0)
    
    def test_du(self):
        """DU: 低四分之一均匀度"""
        flows = np.array([2.0, 1.9, 2.0, 1.8, 2.0, 1.7, 2.0, 1.6])
        du = UniformityAnalyzer.du(flows)
        self.assertLess(du, 100.0)
        self.assertGreater(du, 80.0)
    
    def test_evaluate(self):
        self.assertEqual(UniformityAnalyzer.evaluate(96)["等级"], "优秀")
        self.assertEqual(UniformityAnalyzer.evaluate(87)["等级"], "合格")
        self.assertEqual(UniformityAnalyzer.evaluate(78)["等级"], "较差")
        self.assertEqual(UniformityAnalyzer.evaluate(50)["等级"], "不可接受")
    
    def test_analyze_all(self):
        flows = {"E1": np.array([2.0]), "E2": np.array([1.8]), "E3": np.array([1.9])}
        pressures = {"E1": np.array([15.0]), "E2": np.array([12.0]), "E3": np.array([13.0])}
        result = UniformityAnalyzer.analyze_all(flows, pressures)
        self.assertIn("CU", result)
        self.assertIn("DU", result)
        self.assertIn("EU", result)
        self.assertIn("CU评价", result)


class TestFertigationAnalyzer(unittest.TestCase):
    """1.7.2 水肥分析测试"""
    
    def test_concentration_curve(self):
        quality = {"E1": np.array([0, 0.1, 0.5, 0.8, 1.0, 1.0])}
        result = FertigationAnalyzer.concentration_curve(quality, "E1")
        self.assertEqual(result["节点"], "E1")
        self.assertAlmostEqual(result["最终浓度"], 1.0)
    
    def test_missing_node(self):
        result = FertigationAnalyzer.concentration_curve({}, "E1")
        self.assertIn("error", result)
    
    def test_uniformity(self):
        conc = np.array([1.0, 0.9, 1.0, 0.95])
        u = FertigationAnalyzer.uniformity(conc)
        self.assertGreater(u, 90.0)
    
    def test_analyze(self):
        quality = {
            "E1": np.array([0, 0.5, 1.0]),
            "E2": np.array([0, 0.4, 0.9]),
            "E3": np.array([0, 0.45, 0.95]),
        }
        result = FertigationAnalyzer.analyze(quality, emitter_nodes=["E1", "E2", "E3"])
        self.assertIn("平均浓度", result)
        self.assertIn("浓度均匀度", result)
        self.assertIn("滴头处浓度均匀度", result)


class TestCalibrationAnalyzer(unittest.TestCase):
    """1.7.3 校准测试"""
    
    def test_compare_perfect(self):
        measured = {"J1": 15.0, "J2": 14.5}
        simulated = {"J1": 15.0, "J2": 14.5}
        result = CalibrationAnalyzer.compare(measured, simulated)
        self.assertAlmostEqual(result["统计"]["RMSE"], 0.0)
    
    def test_compare_with_error(self):
        measured = {"J1": 15.0, "J2": 14.5}
        simulated = {"J1": 16.0, "J2": 13.5}
        result = CalibrationAnalyzer.compare(measured, simulated)
        self.assertGreater(result["统计"]["RMSE"], 0.0)
        self.assertEqual(len(result["节点对比"]), 2)
    
    def test_suggest_roughness(self):
        measured = {"J1": 15.0}
        simulated = {"J1": 10.0}  # 模拟偏低
        net = DripNetwork("test")
        net.add_node(Junction("J1", 0, 0))
        net.add_node(Junction("J2", 10, 0))
        net.add_link(Pipe("P1", "J1", "J2", roughness=130))
        
        suggestions = CalibrationAnalyzer.suggest_roughness_adjustment(
            measured, simulated, net
        )
        self.assertGreater(len(suggestions), 0)
    
    def test_report(self):
        measured = {"J1": 15.0, "J2": 14.0}
        simulated = {"J1": 15.5, "J2": 13.5}
        report = CalibrationAnalyzer.report(measured, simulated)
        self.assertIn("评价", report)
        self.assertIn("统计", report)
        self.assertIn("节点详情", report)


if __name__ == "__main__":
    unittest.main()
