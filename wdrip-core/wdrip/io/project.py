"""ProjectFile — .aqd 工程文件读写"""

import json
import os
import zipfile
import tempfile
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from wdrip.network import DripNetwork

PROJECT_VERSION = "1.0"


@dataclass
class ProjectMetadata:
    """项目元数据"""
    name: str = "未命名项目"
    description: str = ""
    author: str = ""
    created_at: str = ""
    updated_at: str = ""
    version: str = PROJECT_VERSION
    crs: str = "EPSG:4326"
    units: str = "SI"


class ProjectFile:
    """.aqd 工程文件
    
    格式: ZIP 包，包含以下内容:
      VERSION          — 版本号
      metadata.json    — 项目元数据
      field.geojson    — 农田边界
      network.json     — 管网数据（节点+管道）
      equipment.json   — 设备配置
      simulation.json  — 模拟参数
      results/         — 结果缓存（可选）
    """
    
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self.metadata = ProjectMetadata()
        self.field_geojson: dict = {"type": "FeatureCollection", "features": []}
        self.network_data: dict = {"nodes": {}, "links": {}}
        self.equipment_data: dict = {}
        self.simulation_data: dict = {}
        self.results_data: dict = {}
    
    # ---- 保存 ----
    
    def save(self, path: Optional[str] = None) -> str:
        """保存到 .aqd 文件"""
        if path:
            self.path = path
        if not self.path:
            raise ValueError("未指定保存路径")
        
        self.metadata.updated_at = datetime.now().isoformat()
        if not self.metadata.created_at:
            self.metadata.created_at = self.metadata.updated_at
        
        with zipfile.ZipFile(self.path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 版本
            zf.writestr("VERSION", PROJECT_VERSION)
            # 元数据
            zf.writestr("metadata.json", json.dumps(asdict(self.metadata), indent=2, ensure_ascii=False))
            # 农田
            zf.writestr("field.geojson", json.dumps(self.field_geojson, indent=2, ensure_ascii=False))
            # 管网
            zf.writestr("network.json", json.dumps(self.network_data, indent=2, ensure_ascii=False))
            # 设备
            if self.equipment_data:
                zf.writestr("equipment.json", json.dumps(self.equipment_data, indent=2, ensure_ascii=False))
            # 模拟
            if self.simulation_data:
                zf.writestr("simulation.json", json.dumps(self.simulation_data, indent=2, ensure_ascii=False))
        
        return self.path
    
    # ---- 加载 ----
    
    def load(self, path: Optional[str] = None) -> 'ProjectFile':
        """从 .aqd 文件加载"""
        if path:
            self.path = path
        if not self.path or not os.path.exists(self.path):
            raise FileNotFoundError(f"文件不存在: {self.path}")
        
        with zipfile.ZipFile(self.path, "r") as zf:
            # 版本检查
            version = zf.read("VERSION").decode("utf-8").strip()
            if version != PROJECT_VERSION:
                raise ValueError(f"版本不匹配: 文件={version}, 期望={PROJECT_VERSION}")
            
            # 元数据
            if "metadata.json" in zf.namelist():
                data = json.loads(zf.read("metadata.json"))
                self.metadata = ProjectMetadata(**data)
            
            # 农田
            if "field.geojson" in zf.namelist():
                self.field_geojson = json.loads(zf.read("field.geojson"))
            
            # 管网
            if "network.json" in zf.namelist():
                self.network_data = json.loads(zf.read("network.json"))
            
            # 设备
            if "equipment.json" in zf.namelist():
                self.equipment_data = json.loads(zf.read("equipment.json"))
            
            # 模拟
            if "simulation.json" in zf.namelist():
                self.simulation_data = json.loads(zf.read("simulation.json"))
        
        return self
    
    # ---- DripNetwork 转换 ----
    
    def from_network(self, network: 'DripNetwork') -> 'ProjectFile':
        """从 DripNetwork 导出数据"""
        self.metadata.name = network.name
        self.metadata.units = network.units
        
        # 节点
        for nid, node in network.nodes.items():
            node_dict = {
                "type": type(node).__name__,
                "x": node.x,
                "y": node.y,
                "elevation": node.elevation,
            }
            # 类型特定属性
            if hasattr(node, "source_type"):
                node_dict["source_type"] = node.source_type
                node_dict["head"] = node.head
            if hasattr(node, "demand"):
                node_dict["demand"] = node.demand
            if hasattr(node, "emitter_k"):
                node_dict["emitter_k"] = node.emitter_k
                node_dict["emitter_x"] = node.emitter_x
            if hasattr(node, "lateral_id"):
                node_dict["lateral_id"] = node.lateral_id
            
            self.network_data["nodes"][nid] = node_dict
        
        # 链路
        for lid, link in network.links.items():
            link_dict = {
                "type": type(link).__name__,
                "from_node": link.from_node,
                "to_node": link.to_node,
            }
            if hasattr(link, "pipe_type"):
                link_dict["pipe_type"] = link.pipe_type
                link_dict["diameter"] = link.diameter
                link_dict["length"] = link.length
                link_dict["roughness"] = link.roughness
            if hasattr(link, "rated_head"):
                link_dict["rated_head"] = link.rated_head
                link_dict["rated_flow"] = link.rated_flow
            if hasattr(link, "valve_type"):
                link_dict["valve_type"] = str(link.valve_type.name)
                link_dict["setting"] = link.setting
            
            self.network_data["links"][lid] = link_dict
        
        # 农田
        if network.field_info:
            self.field_geojson = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {
                        "area": network.field_info.area,
                        "crop_type": network.field_info.crop_type,
                        "planting_pattern": network.field_info.planting_pattern,
                    },
                    "geometry": None,  # 由 QGIS 层填充
                }]
            }
        
        return self
    
    def to_network(self) -> dict:
        """转换为 DripNetwork 所需的参数字典
        
        返回: {"nodes": {...}, "links": {...}, ...}
        """
        return self.network_data
    
    def list_contents(self) -> List[str]:
        """列出文件内容"""
        if not self.path or not os.path.exists(self.path):
            return []
        with zipfile.ZipFile(self.path, "r") as zf:
            return zf.namelist()
