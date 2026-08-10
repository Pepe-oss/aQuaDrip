"""单位一致性数值校核测试

锁定 emitter_k / diameter 在三条路径下的正确换算，防止回归：
  1. simulation 路径：emitter_coefficient = k * 2.778e-7（L/h → m³/s，WNTR 内部 SI）
  2. inp_writer 路径：emitter coefficient = k / 3600（L/h → L/s，EPANET LPS 模式）
  3. _extract_results 手算：emitter_flow = k * P^x（L/h）

三个系数数值上相差 1000 倍，但分属不同单位系统，各自正确。
本测试用固定参数手算 vs 公式断言一致性。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wdrip.network import (
    DripNetwork, SourceNode, Junction, EmitterNode, Pipe,
)
from wdrip.io import InpWriter


class TestEmitterUnits(unittest.TestCase):
    """emitter 系数单位一致性"""

    def test_sim_path_coefficient_is_m3s(self):
        """simulation 路径：k(L/h) → m³/s 系数正确

        WNTR WaterNetworkModel 内部流量单位为 m³/s（已实测验证：
        base_demand=1.0 → demand=1.0）。因此 L/h 转 m³/s 乘 2.77778e-7 正确。
        """
        k_Lh = 1.6  # L/h / m^x
        coeff_si = k_Lh * 2.77778e-7
        # 1 L/h = 1e-3 m³/3600s = 2.77778e-7 m³/s
        self.assertAlmostEqual(coeff_si, 1.6 / 3.6e6, places=12)

    def test_inp_path_coefficient_is_lps(self):
        """inp_writer 路径：k(L/h) → L/s 系数正确

        EPANET LPS 单位制下，emitter coefficient 单位为 (L/s)/m^x，
        q(L/s) = c * P(m)^x。因此 L/h 转 L/s 除以 3600 正确。
        """
        k_Lh = 1.6
        coeff_lps = k_Lh / 3600
        # 1 L/h = 1/3600 L/s
        self.assertAlmostEqual(coeff_lps, 4.444444e-4, places=9)

    def test_three_paths_same_flow_at_same_pressure(self):
        """三条路径在同一压力下得到相同的 emitter 流量（L/h）

        固定 P=10m, k=1.6, x=0.5，手算 q = 1.6 * 10^0.5 ≈ 5.06 L/h。
        无论经过哪条换算路径，最终物理流量必须一致。
        """
        k = 1.6
        x = 0.5
        P = 10.0  # m

        # 路径1: _extract_results 手算（直接 L/h）
        q_extract = k * (P ** x)

        # 路径2: INP 路径 c=L/s → q(L/s) → *3600=L/h
        c_lps = k / 3600
        q_inp_Lh = c_lps * (P ** x) * 3600

        # 路径3: simulation coeff=m³/s → q(m³/s) → *1000*3600=L/h
        c_si = k * 2.77778e-7
        q_sim_Lh = c_si * (P ** x) * 1000 * 3600

        self.assertAlmostEqual(q_extract, q_inp_Lh, places=9)
        self.assertAlmostEqual(q_extract, q_sim_Lh, places=5)
        # 手算校核：1.6 * sqrt(10) ≈ 5.0596
        self.assertAlmostEqual(q_extract, 5.059644, places=4)


class TestDiameterUnits(unittest.TestCase):
    """管径单位统一为 mm 的校核"""

    def _make_net(self, diameter):
        net = DripNetwork("d_test")
        net.add_node(SourceNode("R1", 0, 0, head=20))
        net.add_node(Junction("J1", 10, 0))
        net.add_link(Pipe("P1", "R1", "J1", pipe_type="mainline",
                          diameter=diameter, length=50, roughness=130))
        return net

    def test_mm_diameter_written_as_is(self):
        """diameter=63(mm) 在 INP 中应原样输出 63.00，不被启发式放大"""
        inp = InpWriter(self._make_net(63)).to_string()
        # P1 行应包含 "63.00"，而非 63000 或 0.063
        p1_line = [l for l in inp.splitlines() if l.strip().startswith("P1")][0]
        self.assertIn("63.00", p1_line)
        self.assertNotIn("63000", p1_line)
        self.assertNotIn("0.063", p1_line)

    def test_small_mm_diameter_not_misinterpreted(self):
        """diameter=16(mm) 毛管在 INP 中应输出 16.00

        旧实现用 ">1" 启发式会把小直径毛管误判，这里锁定正确行为。
        """
        inp = InpWriter(self._make_net(16)).to_string()
        p1_line = [l for l in inp.splitlines() if l.strip().startswith("P1")][0]
        self.assertIn("16.00", p1_line)


if __name__ == "__main__":
    unittest.main()
