"""Sprint 1.8 — 项目文件测试"""

import os, sys, json, tempfile, zipfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wdrip.io import ProjectFile, ProjectMetadata, InpWriter
from wdrip.network import (
    DripNetwork, SourceNode, Junction, EmitterNode,
    Pipe, Pump, Valve, ValveType, FieldInfo, BUILTIN_EMITTERS,
)


class TestProjectFile(unittest.TestCase):
    """1.8.1 .aqd 工程文件"""
    
    def setUp(self):
        self.net = DripNetwork("test_proj", field_info=FieldInfo(area=10000))
        self.net.add_node(SourceNode("S1", 0, 0, head=30))
        self.net.add_node(Junction("J1", 10, 10, elevation=5))
        self.net.add_node(EmitterNode("E1", 20, 10, emitter_k=0.506, lateral_id="L1"))
        self.net.add_link(Pipe("P1", "S1", "J1", pipe_type="mainline", diameter=0.05, length=100))

    def test_save_and_load(self):
        with tempfile.NamedTemporaryFile(suffix=".aqd", delete=False) as f:
            tmp_path = f.name
        
        try:
            # 保存
            proj = ProjectFile()
            proj.from_network(self.net)
            proj.save(tmp_path)
            
            self.assertTrue(os.path.exists(tmp_path))
            
            # 加载
            loaded = ProjectFile(tmp_path).load()
            self.assertEqual(loaded.metadata.name, "test_proj")
            self.assertIn("S1", loaded.network_data["nodes"])
            self.assertIn("P1", loaded.network_data["links"])
        finally:
            os.unlink(tmp_path)
    
    def test_contents(self):
        with tempfile.NamedTemporaryFile(suffix=".aqd", delete=False) as f:
            tmp_path = f.name
        
        try:
            proj = ProjectFile()
            proj.from_network(self.net)
            proj.save(tmp_path)
            
            contents = proj.list_contents()
            self.assertIn("VERSION", contents)
            self.assertIn("metadata.json", contents)
            self.assertIn("network.json", contents)
        finally:
            os.unlink(tmp_path)
    
    def test_metadata_defaults(self):
        meta = ProjectMetadata()
        self.assertEqual(meta.version, "1.0")
        self.assertEqual(meta.units, "SI")


class TestInpWriter(unittest.TestCase):
    """1.8.2 INP 导出"""
    
    def setUp(self):
        self.net = DripNetwork("test_inp")
        self.net.add_node(SourceNode("R1", 0, 0, source_type="well", head=25))
        self.net.add_node(Junction("J1", 10, 0, elevation=2, demand=0))
        self.net.add_node(EmitterNode("E1", 20, 0, elevation=5,
                                       emitter_k=0.5164, emitter_x=0.5))
        self.net.add_link(Pipe("P1", "R1", "J1", pipe_type="mainline",
                                diameter=0.05, length=100, roughness=130))
        self.net.add_link(Pipe("P2", "J1", "E1", pipe_type="lateral",
                                diameter=0.016, length=100, roughness=130))
    
    def test_to_string(self):
        inp = InpWriter(self.net).to_string()
        self.assertIn("[TITLE]", inp)
        self.assertIn("[JUNCTIONS]", inp)
        self.assertIn("[RESERVOIRS]", inp)
        self.assertIn("[PIPES]", inp)
        self.assertIn("[EMITTERS]", inp)
        self.assertIn("[COORDINATES]", inp)
        self.assertIn("[OPTIONS]", inp)
        self.assertIn("[END]", inp)
    
    def test_contains_nodes(self):
        inp = InpWriter(self.net).to_string()
        self.assertIn("R1", inp)
        self.assertIn("J1", inp)
        self.assertIn("E1", inp)
    
    def test_contains_pipes(self):
        inp = InpWriter(self.net).to_string()
        self.assertIn("P1", inp)
        self.assertIn("P2", inp)
    
    def test_write_file(self):
        with tempfile.NamedTemporaryFile(suffix=".inp", delete=False) as f:
            tmp_path = f.name
        try:
            InpWriter(self.net).write(tmp_path)
            with open(tmp_path) as f:
                content = f.read()
            self.assertIn("[TITLE]", content)
        finally:
            os.unlink(tmp_path)


class TestInpWriterAdvanced(unittest.TestCase):
    """INP 导出进阶测试（含泵和阀）"""
    
    def test_pump_and_valve(self):
        net = DripNetwork("advanced")
        net.add_node(SourceNode("R1", 0, 0, head=30))
        net.add_node(Junction("J1", 10, 0))
        net.add_node(Junction("J2", 20, 0))
        net.add_node(EmitterNode("E1", 30, 0, emitter_k=0.5, lateral_id="L1"))
        net.add_link(Pipe("P1", "R1", "J1", pipe_type="mainline", diameter=0.05, length=50))
        net.add_link(Pump("PU1", "J1", "J2", rated_head=20, rated_flow=10))
        net.add_link(Valve("V1", "J2", "E1", valve_type=ValveType.PRV, setting=15))
        net.add_link(Pipe("L1", "E1", "E1", pipe_type="lateral", diameter=0.016, length=10))
        
        inp = InpWriter(net).to_string()
        self.assertIn("[PUMPS]", inp)
        self.assertIn("[VALVES]", inp)
        self.assertIn("PU1", inp)
        self.assertIn("V1", inp)


if __name__ == "__main__":
    unittest.main()
