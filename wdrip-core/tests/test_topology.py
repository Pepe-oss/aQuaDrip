"""Sprint 1.2 + 1.3 — 拓扑引擎 + 管网构建器测试"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wdrip.topology import TopologyGraph, TopologyNode, TopologyEdge, TopologyLevel
from wdrip.network import FieldInfo, DripNetwork, SourceNode, Junction, Pipe
from wdrip.builder import LayoutParams, RectangularLayoutBuilder


class TestTopologyGraph(unittest.TestCase):
    """1.2 拓扑引擎测试"""

    def setUp(self):
        self.g = TopologyGraph()

    def test_add_node(self):
        n = self.g.add_node("J001")
        self.assertIn("J001", self.g.nodes)
        self.assertEqual(self.g.nodes["J001"].degree, 0)

    def test_add_edge_auto_creates_nodes(self):
        e = self.g.add_edge("P001", "J001", "J002")
        self.assertIn("J001", self.g.nodes)
        self.assertIn("J002", self.g.nodes)
        self.assertIn("P001", self.g.edges)
        # 邻接关系更新
        self.assertIn("J002", self.g.nodes["J001"].adjacent)
        self.assertIn("J001", self.g.nodes["J002"].adjacent)

    def test_remove_edge(self):
        self.g.add_edge("P001", "J001", "J002")
        self.g.remove_edge("P001")
        self.assertNotIn("P001", self.g.edges)
        self.assertNotIn("J002", self.g.nodes["J001"].adjacent)

    def test_remove_node_cascades(self):
        self.g.add_edge("P001", "J001", "J002")
        self.g.add_edge("P002", "J002", "J003")
        self.g.remove_node("J002")
        self.assertNotIn("J002", self.g.nodes)
        self.assertNotIn("P001", self.g.edges)
        self.assertNotIn("P002", self.g.edges)

    def test_validate_isolated_node(self):
        self.g.add_node("ISOLATED")
        errors = self.g.validate()
        self.assertTrue(any("孤立" in e for e in errors))

    def test_hierarchy(self):
        self.g.add_edge("P001", "A", "B", level=TopologyLevel.MAINLINE)
        self.g.add_edge("P002", "B", "C", level=TopologyLevel.SUBMAIN)
        h = self.g.hierarchy()
        self.assertIn("P001", h[TopologyLevel.MAINLINE])
        self.assertIn("P002", h[TopologyLevel.SUBMAIN])

    def test_build_from_network(self):
        net = DripNetwork("test")
        net.add_node(SourceNode("S001", 0, 0))
        net.add_node(Junction("J001", 10, 10))
        net.add_link(Pipe("P001", "S001", "J001", pipe_type="mainline"))
        
        g = TopologyGraph().build_from_network(net)
        self.assertEqual(g.node_count, 2)
        self.assertEqual(g.edge_count, 1)

    def test_is_tree(self):
        # 3 nodes, 2 edges = tree
        self.g.add_edge("P001", "A", "B")
        self.g.add_edge("P002", "B", "C")
        self.assertTrue(self.g.is_tree())


class TestRectangularBuilder(unittest.TestCase):
    """1.3 管网构建器测试"""

    def setUp(self):
        self.builder = RectangularLayoutBuilder()
        self.field = FieldInfo(area=5000, crop_type="corn")

    def test_uniform_pattern(self):
        params = LayoutParams(
            planting_pattern="uniform",
            row_spacings=[0.5],
            emitter_spacing=0.3,
        )
        graph = self.builder.build_topology(self.field, params)
        self.assertGreater(graph.node_count, 0)
        self.assertGreater(graph.edge_count, 0)

    def test_wide_narrow_pattern(self):
        params = LayoutParams(
            planting_pattern="wide_narrow",
            row_spacings=[0.3, 0.15],
            emitter_spacing=0.3,
        )
        graph = self.builder.build_topology(self.field, params)
        self.assertGreater(graph.node_count, 0)

    def test_ridge_count_pattern(self):
        params = LayoutParams(
            planting_pattern="ridge_count",
            ridge_count=40,
            emitter_spacing=0.3,
        )
        graph = self.builder.build_topology(self.field, params)
        self.assertGreater(graph.node_count, 0)

    def test_custom_pattern(self):
        params = LayoutParams(
            planting_pattern="custom",
            row_spacings=[5, 10, 15, 20, 25, 30, 35, 40, 45],
            emitter_spacing=0.3,
        )
        graph = self.builder.build_topology(self.field, params)
        self.assertGreater(graph.node_count, 0)

    def test_topology_valid(self):
        """生成的拓扑图应通过基础验证"""
        params = LayoutParams(planting_pattern="uniform", row_spacings=[0.5])
        graph = self.builder.build_topology(self.field, params)
        errors = graph.validate()
        # 应该没有孤立节点（干管连接正常）
        isolated = [e for e in errors if "孤立" in e]
        self.assertEqual(len(isolated), 0, f"存在孤立节点: {isolated}")

    def test_hierarchy_contains_all_levels(self):
        params = LayoutParams(planting_pattern="uniform", row_spacings=[0.5])
        graph = self.builder.build_topology(self.field, params)
        h = graph.hierarchy()
        # 应该包含干管、支管、毛管三层
        has_mainline = len(h[TopologyLevel.MAINLINE]) > 0
        has_submain = len(h[TopologyLevel.SUBMAIN]) > 0
        has_lateral = len(h[TopologyLevel.LATERAL]) > 0
        self.assertTrue(has_mainline, "缺少干管层")
        self.assertTrue(has_submain, "缺少支管层")
        self.assertTrue(has_lateral, "缺少毛管层")


if __name__ == "__main__":
    unittest.main()
