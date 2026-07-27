"""Sprint 1.1 — 数据模型单元测试（使用 unittest）"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wdrip.network import (
    SourceNode, Junction, EmitterNode,
    Pipe, Pump, Valve, ValveType, ValveStatus,
    EmitterSpec, BUILTIN_EMITTERS, list_manufacturers,
    FieldInfo, IrrigationSchedule, DripNetwork,
)
from wdrip.settings import SettingsManager


class TestNodes(unittest.TestCase):
    """1.1.1 节点模型"""

    def test_source_node(self):
        s = SourceNode("S001", 0, 0, source_type="well", head=30)
        self.assertEqual(s.id, "S001")
        self.assertEqual(s.source_type, "well")

    def test_junction(self):
        j = Junction("J001", 10, 10, demand=0.5)
        self.assertEqual(j.demand, 0.5)

    def test_emitter_node(self):
        e = EmitterNode("E001", 10, 10.3, emitter_k=0.506, emitter_x=0.5)
        self.assertIsInstance(e, Junction)


class TestLinks(unittest.TestCase):
    """1.1.2 链路模型"""

    def test_pipe(self):
        p = Pipe("P001", "J001", "J002", pipe_type="mainline", diameter=63)
        self.assertEqual(p.direction, "J001 → J002")

    def test_pump_is_link(self):
        pu = Pump("PU001", "J001", "J002", rated_head=30)
        self.assertTrue(hasattr(pu, "from_node"))

    def test_pump_reverse(self):
        pu = Pump("PU001", "J001", "J002", rated_head=30)
        pu.reverse()
        self.assertEqual(pu.from_node, "J002")

    def test_valve_direction(self):
        prv = Valve("V001", "J001", "J002", valve_type=ValveType.PRV)
        gate = Valve("V002", "J001", "J002", valve_type=ValveType.GATE)
        self.assertTrue(prv.has_direction)
        self.assertFalse(gate.has_direction)


class TestEmitterSpec(unittest.TestCase):
    """1.1.4 滴头规格"""

    def test_flow_calculation(self):
        spec = EmitterSpec("test", k=0.506, x=0.5)
        self.assertAlmostEqual(spec.flow_at_pressure(10), 1.60, delta=0.01)

    def test_builtin_emitters(self):
        self.assertGreaterEqual(len(BUILTIN_EMITTERS), 10)
        self.assertIn("Netafim", list_manufacturers())


class TestFieldInfo(unittest.TestCase):
    """1.1.5 农田参数"""

    def test_uniform_defaults(self):
        f = FieldInfo(area=10000)
        self.assertEqual(f.planting_pattern, "uniform")

    def test_ridge_count(self):
        f = FieldInfo(area=5000, planting_pattern="ridge_count", ridge_count=40)
        self.assertEqual(len(f.validate()), 0)

    def test_invalid_area(self):
        f = FieldInfo(area=0)
        self.assertGreater(len(f.validate()), 0)


class TestIrrigationSchedule(unittest.TestCase):
    """1.1.5 灌溉制度"""

    def test_shift_group(self):
        sched = IrrigationSchedule(total_duration_hours=2)
        sched.add_shift_group("A", ["V1"], 0, 0.5)
        self.assertEqual(sched.get_valve_schedule("V1"), (0, 0.5))

    def test_overlap_detection(self):
        sched = IrrigationSchedule(total_duration_hours=2)
        sched.add_shift_group("A", ["V1"], 0, 0.5)
        sched.add_shift_group("B", ["V2"], 0.5, 1.0)
        sched.add_shift_group("C", ["V3"], 0.3, 0.8)
        self.assertEqual(len(sched.validate()), 2)


class TestDripNetwork(unittest.TestCase):
    """1.1.3 + 1.1.6 管网+验证"""

    def setUp(self):
        self.net = DripNetwork("test")
        self.net.add_node(SourceNode("S001", 0, 0, head=30))
        self.net.add_node(Junction("J001", 10, 10))
        self.net.add_node(EmitterNode("E001", 10, 10.5, emitter_k=0.506,
                                      emitter_x=0.5, lateral_id="L001"))
        self.net.add_link(Pipe("P001", "S001", "J001", pipe_type="mainline"))

    def test_add_node(self):
        self.assertEqual(len(self.net.nodes), 3)

    def test_duplicate_node_raises(self):
        with self.assertRaises(KeyError):
            self.net.add_node(Junction("S001", 0, 0))

    def test_validation_detects_missing_lateral(self):
        errors = self.net.validate()
        lateral_errors = [e for e in errors if "L001" in e]
        self.assertGreater(len(lateral_errors), 0)

    def test_remove_node_cascades(self):
        self.net.remove_node("E001")
        self.assertNotIn("E001", self.net.nodes)

    def test_pipe_length_stats(self):
        stats = self.net.pipe_length_by_type
        self.assertIn("mainline", stats)


class TestSettings(unittest.TestCase):
    """1.1.7 配置管理"""

    def setUp(self):
        self.mgr = SettingsManager()

    def test_defaults(self):
        self.assertEqual(self.mgr.get("units"), "SI")

    def test_set_and_get(self):
        self.mgr.set("language", "en")
        self.assertEqual(self.mgr.get("language"), "en")
        self.mgr.reset()
        self.assertEqual(self.mgr.get("language"), "zh")


if __name__ == "__main__":
    unittest.main()
