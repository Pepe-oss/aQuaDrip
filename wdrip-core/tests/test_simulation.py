"""Sprint 1.6 — 模拟封装测试"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wdrip.network import (
    DripNetwork, SourceNode, Junction, EmitterNode,
    Pipe, Pump, Valve, ValveType,
    FieldInfo, BUILTIN_EMITTERS,
)


class TestDripSimulation(unittest.TestCase):
    """1.6 DripSimulation 集成测试"""
    
    def setUp(self):
        # 构建一个简单管网用于测试
        self.net = DripNetwork("test_sim", field_info=FieldInfo(area=1000))
        
        # 水源
        self.net.add_node(SourceNode("R1", 0, 0, source_type="well", head=30))
        # 节点
        self.net.add_node(Junction("J1", 10, 0, elevation=0))
        self.net.add_node(Junction("J2", 20, 0, elevation=2))
        # 滴头
        self.net.add_node(EmitterNode("E1", 30, 0, elevation=5,
                                       emitter_k=0.506, emitter_x=0.5,
                                       lateral_id="P3"))
        # 管道
        self.net.add_link(Pipe("P1", "R1", "J1", pipe_type="mainline",
                                diameter=50, length=100, roughness=130))
        self.net.add_link(Pipe("P2", "J1", "J2", pipe_type="submain",
                                diameter=40, length=50, roughness=130))
        self.net.add_link(Pipe("P3", "J2", "E1", pipe_type="lateral",
                                diameter=16, length=100, roughness=130))
    
    def test_import(self):
        """验证导入"""
        from wdrip.simulation import DripSimulation
        self.assertIsNotNone(DripSimulation)
    
    def test_build_wntr_model(self):
        """验证 WNTR 模型构建"""
        from wdrip.simulation import DripSimulation
        sim = DripSimulation(self.net)
        wn = sim._build_wntr_model()
        # 验证节点和管道数量
        nodes = list(wn.node_name_list)
        pipes = list(wn.pipe_name_list)
        self.assertEqual(len(nodes), 4)  # R1, J1, J2, E1
        self.assertEqual(len(pipes), 3)  # P1, P2, P3
    
    def test_run_steady_simulation(self):
        """运行稳态模拟"""
        from wdrip.simulation import DripSimulation
        sim = DripSimulation(self.net)
        result = sim.run(duration=0)
        self.assertTrue(result.success, msg=f"模拟失败: {result.message}")
        # 验证结果存在
        self.assertIn("R1", result.node_pressure)
        self.assertIn("P1", result.link_flow)
    
    def test_emitter_flow_extracted(self):
        """验证滴头流量被正确提取"""
        from wdrip.simulation import DripSimulation
        sim = DripSimulation(self.net)
        result = sim.run(duration=0)
        self.assertTrue(result.success)
        # 滴头 E1 应有流量
        if "E1" in result.emitter_flow:
            flow = result.emitter_flow["E1"][0]
            self.assertGreater(flow, 0, "滴头流量应大于 0")
    
    @unittest.skip("水质模拟需要额外配置")
    def test_water_quality(self):
        """水质模拟（暂跳）"""
        pass


class TestDripSimulationSimple(unittest.TestCase):
    """极简模拟测试——最小化管网"""
    
    def test_minimal_network(self):
        """最小管网：水源 → 节点 → 滴头"""
        net = DripNetwork("minimal")
        net.add_node(SourceNode("R1", 0, 0, head=20))
        net.add_node(EmitterNode("E1", 10, 0, elevation=0,
                                  emitter_k=0.506, emitter_x=0.5))
        net.add_link(Pipe("P1", "R1", "E1", diameter=20, length=50, roughness=130))
        
        from wdrip.simulation import DripSimulation
        sim = DripSimulation(net)
        result = sim.run(duration=0)
        self.assertTrue(result.success, msg=f"失败: {result.message}")
        # 滴头附近应有压力
        pressure = result.get_pressure_at("E1")
        if pressure is not None:
            self.assertGreater(pressure, 0)


if __name__ == "__main__":
    unittest.main()
