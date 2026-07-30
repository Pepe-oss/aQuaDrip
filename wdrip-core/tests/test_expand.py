"""毛管展开（expand_lateral）与模拟闭环集成测试"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wdrip.network import (
    DripNetwork, FieldInfo, SourceNode, Junction, EmitterNode,
    Pipe, expand_lateral, expand_all_laterals,
)


def _make_net_with_lateral(length=10.0):
    """构造：水源 R1 ──干管M── J1 ──毛管L1── B（末端）"""
    net = DripNetwork("展开测试")
    net.add_node(SourceNode("R1", 0, 0, source_type="well", head=20))
    net.add_node(Junction("J1", 50, 0))
    net.add_node(Junction("B", 50, length))
    net.add_link(Pipe("M", "R1", "J1", pipe_type="mainline",
                      diameter=63, length=50, roughness=130))
    net.add_link(Pipe("L1", "J1", "B", pipe_type="lateral",
                      diameter=16, length=length, roughness=130))
    return net


class TestExpandLateral(unittest.TestCase):
    """毛管展开逻辑"""

    def test_basic_expand(self):
        """L=10, es=0.5 → 20 个滴头，21 条边？不：n 段 = n 条"""
        net = _make_net_with_lateral(10.0)
        n = expand_lateral(net, "L1", emitter_spacing=0.5)
        self.assertEqual(n, 20)

        # 节点：R1, J1, B + 19 个中间滴头 = 22（B 原地升级为第 20 个滴头）
        emitters = [nd for nd in net.nodes.values()
                    if isinstance(nd, EmitterNode)]
        self.assertEqual(len(emitters), 20)

        # 段数：L1（第一段）+ 19 个 seg = 20 段 lateral
        lateral_links = [l for l in net.links.values()
                         if getattr(l, "pipe_type", "") == "lateral"]
        self.assertEqual(len(lateral_links), 20)

    def test_first_segment_keeps_original_id(self):
        """第一段保留原 link_id（lateral_id 校验 + 结果回写匹配）"""
        net = _make_net_with_lateral(10.0)
        expand_lateral(net, "L1", emitter_spacing=0.5)
        link = net.get_link("L1")
        self.assertIsNotNone(link)
        self.assertEqual(link.from_node, "J1")
        self.assertTrue(link.to_node.startswith("E_L1_"))

    def test_emitter_positions_even(self):
        """滴头沿毛管等距分布，末端滴头在原 to_node 位置"""
        net = _make_net_with_lateral(10.0)
        expand_lateral(net, "L1", emitter_spacing=0.5)
        e1 = net.get_node("E_L1_001")
        self.assertAlmostEqual(e1.y, 0.5, places=6)
        b = net.get_node("B")
        self.assertIsInstance(b, EmitterNode)
        self.assertAlmostEqual(b.y, 10.0, places=6)

    def test_single_emitter_when_short(self):
        """L < es 时只生成 1 个滴头，原 Pipe 保留"""
        net = _make_net_with_lateral(0.2)
        n = expand_lateral(net, "L1", emitter_spacing=0.5)
        self.assertEqual(n, 1)
        b = net.get_node("B")
        self.assertIsInstance(b, EmitterNode)
        self.assertIsNotNone(net.get_link("L1"))  # 原 Pipe 保留

    def test_validate_passes_after_expand(self):
        """展开后 lateral_id 校验通过（无缺失毛管错误）"""
        net = _make_net_with_lateral(10.0)
        expand_lateral(net, "L1", emitter_spacing=0.5)
        errors = net.validate()
        lateral_errors = [e for e in errors if "毛管" in e]
        self.assertEqual(lateral_errors, [], f"lateral_id 校验失败: {lateral_errors}")

    def test_shared_end_node_keeps_references(self):
        """末端被支管共享时，保留为 Junction 不升级（交叉连接点不出水）"""
        net = _make_net_with_lateral(10.0)
        net.add_node(Junction("J2", 60, 10))
        net.add_link(Pipe("S1", "B", "J2", pipe_type="submain",
                          diameter=40, length=10, roughness=130))
        n = expand_lateral(net, "L1", emitter_spacing=0.5)
        # 支管 S1 仍引用 B，B 保留为 Junction（共享连接点不升级为滴头）
        s1 = net.get_link("S1")
        self.assertEqual(s1.from_node, "B")
        self.assertNotIsInstance(net.get_node("B"), EmitterNode)
        self.assertIsInstance(net.get_node("B"), Junction)
        # 滴头数比非共享时少 1（末端不放滴头）
        self.assertEqual(n, 19)

    def test_reject_non_lateral(self):
        net = _make_net_with_lateral(10.0)
        with self.assertRaises(ValueError):
            expand_lateral(net, "M", emitter_spacing=0.5)

    def test_reject_missing_link(self):
        net = _make_net_with_lateral(10.0)
        with self.assertRaises(KeyError):
            expand_lateral(net, "NOPE", emitter_spacing=0.5)

    def test_expand_all_laterals(self):
        net = _make_net_with_lateral(10.0)
        result = expand_all_laterals(net, default_spacing=0.5)
        self.assertEqual(result, {"L1": 20})


class TestExpandedSimulation(unittest.TestCase):
    """展开后的真实 WNTR 模拟闭环"""

    def test_simulation_with_emitters(self):
        try:
            import wntr  # noqa: F401
        except ImportError:
            self.skipTest("WNTR 未安装")

        from wdrip.simulation import DripSimulation
        from wdrip.analysis import UniformityAnalyzer

        net = _make_net_with_lateral(10.0)
        expand_lateral(net, "L1", emitter_spacing=0.5,
                       emitter_k=0.506, emitter_x=0.5)

        sim = DripSimulation(net)
        result = sim.run()

        self.assertTrue(result.success, f"模拟失败: {result.message}")

        # 滴头出水的直接证据：干管流量 = 所有滴头流量之和 > 0
        # （滴灌系统流量为 L/h 级，DN16 沿程损失仅毫米级，
        #   压力降不可测，不能用"压力 < 水源 head"作为出水判据）
        flow_m = result.get_flow_at("M")
        self.assertIsNotNone(flow_m)
        self.assertGreater(flow_m, 0, "管网无流量（滴头未出水）")

        # 压力物理合理：不超过水源 head，且为正
        p_j1 = result.get_pressure_at("J1")
        self.assertIsNotNone(p_j1)
        self.assertGreater(p_j1, 0.0)
        self.assertLessEqual(p_j1, 20.0)

        # 滴头流量非空且为正
        flows = [arr[0] for arr in result.emitter_flow.values() if len(arr) > 0]
        self.assertEqual(len(flows), 20)
        self.assertTrue(all(f > 0 for f in flows))

        # 均匀度在合理范围
        cu = UniformityAnalyzer.cu(flows)
        self.assertGreater(cu, 50.0)
        self.assertLessEqual(cu, 100.0)


if __name__ == "__main__":
    unittest.main()
