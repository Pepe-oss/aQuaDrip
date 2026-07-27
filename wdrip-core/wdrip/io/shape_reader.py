"""ShapeReader — Shapefile 导入"""

import os
import warnings
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from wdrip.network import DripNetwork


class ShapeReader:
    """Shapefile 导入器
    
    读取 ESRI Shapefile 格式的地理数据，
    支持导入农田地块、现有点/线管网。
    需要 geopandas 和 shapely。
    """
    
    def __init__(self):
        self._geopandas = None
    
    def _check_geopandas(self):
        """检查 geopandas 是否可用"""
        if self._geopandas is None:
            try:
                import geopandas as gpd
                self._geopandas = gpd
            except ImportError:
                raise ImportError("需要 geopandas: pip install geopandas")
    
    def read_field(self, shp_path: str) -> Optional[dict]:
        """从 Shapefile 读取农田地块
        
        Args:
            shp_path: .shp 文件路径
            
        Returns:
            GeoJSON Feature dict，失败返回 None
        """
        if not os.path.exists(shp_path):
            raise FileNotFoundError(f"文件不存在: {shp_path}")
        
        self._check_geopandas()
        gdf = self._geopandas.read_file(shp_path)
        
        if len(gdf) == 0:
            return None
        
        # 取第一个多边形
        first = gdf.iloc[0]
        geometry = first.geometry
        
        if geometry.geom_type not in ("Polygon", "MultiPolygon"):
            warnings.warn(f"几何类型 {geometry.geom_type} 不是多边形")
            return None
        
        # 计算面积
        area = geometry.area
        
        feature = {
            "type": "Feature",
            "properties": {
                "area": area,
                **{k: str(v) for k, v in first.items() if k != "geometry"},
            },
            "geometry": geometry.__geo_interface__,
        }
        return feature
    
    def read_nodes(self, shp_path: str) -> List[dict]:
        """从点 Shapefile 读取节点
        
        Returns:
            [{id, x, y, elevation}, ...]
        """
        if not os.path.exists(shp_path):
            raise FileNotFoundError(f"文件不存在: {shp_path}")
        
        self._check_geopandas()
        gdf = self._geopandas.read_file(shp_path)
        
        nodes = []
        for idx, row in gdf.iterrows():
            geom = row.geometry
            if geom.geom_type != "Point":
                continue
            
            nid = str(row.get("id", row.get("ID", f"N{idx:04d}")))
            nodes.append({
                "id": nid,
                "x": geom.x,
                "y": geom.y,
                "elevation": float(row.get("elevation", row.get("ELEVATION", 0))),
                "demand": float(row.get("demand", row.get("DEMAND", 0))),
            })
        
        return nodes
    
    def read_pipes(self, shp_path: str) -> List[dict]:
        """从线 Shapefile 读取管道
        
        Returns:
            [{id, from_node, to_node, diameter, length, ...}, ...]
        """
        if not os.path.exists(shp_path):
            raise FileNotFoundError(f"文件不存在: {shp_path}")
        
        self._check_geopandas()
        gdf = self._geopandas.read_file(shp_path)
        
        pipes = []
        for idx, row in gdf.iterrows():
            geom = row.geometry
            if geom.geom_type != "LineString":
                continue
            
            coords = list(geom.coords)
            if len(coords) < 2:
                continue
            
            pid = str(row.get("id", row.get("ID", f"L{idx:04d}")))
            pipes.append({
                "id": pid,
                "from_node": str(row.get("node1", row.get("NODE1", ""))),
                "to_node": str(row.get("node2", row.get("NODE2", ""))),
                "diameter": float(row.get("diameter", row.get("DIAMETER", 0))),
                "length": float(row.get("length", row.get("LENGTH", geom.length))),
                "roughness": float(row.get("roughness", row.get("ROUGHNESS", 130))),
                "pipe_type": str(row.get("type", row.get("TYPE", "mainline"))),
                "coords": list(coords),
            })
        
        return pipes
    
    def detect_nodes_from_pipes(self, pipes: List[dict]) -> List[dict]:
        """从管道端点自动推断节点位置"""
        node_coords = {}
        for pipe in pipes:
            coords = pipe.get("coords", [])
            if len(coords) >= 2:
                # 起点
                start_key = f"{coords[0][0]:.3f}_{coords[0][1]:.3f}"
                if start_key not in node_coords:
                    node_coords[start_key] = coords[0]
                # 终点
                end_key = f"{coords[-1][0]:.3f}_{coords[-1][1]:.3f}"
                if end_key not in node_coords:
                    node_coords[end_key] = coords[-1]
        
        nodes = []
        for i, (key, (x, y)) in enumerate(node_coords.items()):
            nodes.append({
                "id": f"N{i:04d}",
                "x": x,
                "y": y,
                "elevation": 0,
                "demand": 0,
            })
        
        return nodes
