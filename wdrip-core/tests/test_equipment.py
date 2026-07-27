"""Sprint 1.5 — 设备系统测试"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wdrip.equipment import (
    Well, Reservoir, Canal, Outlet,
    PumpSpec, VfdSpec,
    SandFilter, ScreenFilter, DiscFilter,
    FertilizerTank, Injector,
    ValveSpec, PrvSpec, SolenoidSpec, FcvSpec, PsvSpec,
    PressureGauge, FlowMeter, EcProbe, PhProbe,
    EquipmentSet,
)
from wdrip.network import DripNetwork, Junction, Pump, Valve, ValveType


class TestSource(unittest.TestCase):
    def test_well(self):
        w = Well(name="W01", depth=50, yield_rate=20)
        self.assertEqual(w.yield_rate, 20)

    def test_reservoir(self):
        r = Reservoir(capacity=500, water_level=3.0)
        self.assertEqual(r.capacity, 500)

    def test_outlet(self):
        o = Outlet(name="O01", diameter=63, pressure=15)
        self.assertTrue(o.is_control is False)


class TestPumping(unittest.TestCase):
    def test_pump_spec(self):
        ps = PumpSpec(name="IS65-40-200", manufacturer="南方泵业",
                      rated_head=45, rated_flow=25)
        params = ps.to_link_params()
        self.assertEqual(params["rated_head"], 45)
        self.assertEqual(params["rated_flow"], 25)


class TestFiltration(unittest.TestCase):
    def test_sand_filter(self):
        sf = SandFilter(name="SF01", mesh=120, rated_flow=30)
        self.assertEqual(sf.mesh, 120)

    def test_disc_filter(self):
        df = DiscFilter(name="DF01", disc_count=120)
        self.assertEqual(df.disc_count, 120)


class TestFertigation(unittest.TestCase):
    def test_tank(self):
        ft = FertilizerTank(volume=200, concentration=10)
        self.assertEqual(ft.volume, 200)

    def test_injector(self):
        inj = Injector(name="PZ-01", power=120)
        self.assertEqual(inj.power, 120)


class TestControl(unittest.TestCase):
    def test_valve_spec(self):
        vs = ValveSpec(diameter=50, price=200)
        self.assertEqual(vs.diameter, 50)

    def test_prv_spec(self):
        prv = PrvSpec(name="PRV01", default_setting=25)
        self.assertEqual(prv.default_setting, 25)


class TestSensor(unittest.TestCase):
    def test_pressure_gauge(self):
        pg = PressureGauge(range="0-60m")
        self.assertIn("60", pg.range)


class TestEquipmentSet(unittest.TestCase):
    def setUp(self):
        self.es = EquipmentSet()

    def test_empty_count(self):
        self.assertEqual(self.es.total_count, 0)

    def test_add_pump(self):
        ps = PumpSpec(rated_head=30)
        params = self.es.add_pump_spec("PU001", ps)
        self.assertIn("PU001", self.es.pump_specs)
        self.assertEqual(params["rated_head"], 30)

    def test_apply_to_pump_link(self):
        self.es.add_pump_spec("PU001", PumpSpec(rated_head=45, rated_flow=25))
        link = Pump("PU001", "J001", "J002")
        params = self.es.apply_to_link("PU001", link)
        self.assertEqual(params["rated_head"], 45)

    def test_apply_to_prv_link(self):
        self.es.prv_specs["V001"] = PrvSpec(default_setting=25)
        link = Valve("V001", "J001", "J002", valve_type=ValveType.PRV)
        params = self.es.apply_to_link("V001", link)
        self.assertEqual(params["setting"], 25)

    def test_integration_with_network(self):
        """设备系统与 DripNetwork 集成"""
        net = DripNetwork("test")
        net.equipment = self.es
        self.es.add_pump_spec("PU001", PumpSpec(rated_head=30))
        self.assertEqual(net.equipment.total_count, 1)


if __name__ == "__main__":
    unittest.main()
