"""TerrainAdapter — DEM 读取与高程提取"""

import os
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from wdrip.network import DripNetwork


@dataclass
class DemInfo:
    """DEM 栅格信息"""
    path: str                    # 文件路径
    crs: Optional[str] = None    # 坐标系
    resolution: float = 0.0      # 分辨率 (m)
    min_elevation: float = 0.0   # 最低高程
    max_elevation: float = 0.0   # 最高高程
    band_count: int = 1          # 波段数


class DemReader:
    """DEM 栅格读取器
    
    使用 rasterio 读取 GeoTIFF 格式的 DEM 数据。
    如果 rasterio 不可用，回退到简单的 CSV 格式。
    """
    
    def __init__(self, path: str):
        self.path = path
        self._rasterio = None
        self._dataset = None
        self._info: Optional[DemInfo] = None
    
    def open(self) -> bool:
        """打开 DEM 文件，返回是否成功"""
        # 尝试用 rasterio 打开
        try:
            import rasterio
            self._rasterio = rasterio
            self._dataset = rasterio.open(self.path)
            self._info = DemInfo(
                path=self.path,
                crs=str(self._dataset.crs) if self._dataset.crs else None,
                resolution=abs(self._dataset.res[0]),
                min_elevation=0.0,
                max_elevation=0.0,
                band_count=self._dataset.count,
            )
            # 用掩膜 nodata 后的波段统计真实高程范围。
            # 注意 bounds.top/bottom 是地理外包框的北/南边界坐标，
            # 不是高程值，不能用作 min/max elevation
            try:
                import numpy as np
                band = self._dataset.read(1, masked=True)
                valid = band.compressed()
                if valid.size > 0:
                    self._info.min_elevation = float(np.min(valid))
                    self._info.max_elevation = float(np.max(valid))
            except Exception:
                pass  # 统计失败不阻断打开（read_elevation 仍可用）
            return True
        except ImportError:
            warnings.warn("rasterio 未安装，尝试 CSV 回退模式")
            return self._open_csv()
        except Exception as e:
            warnings.warn(f"无法打开 DEM 文件 {self.path}: {e}")
            return False
    
    def _open_csv(self) -> bool:
        """以 CSV 格式回退打开（x,y,elevation）"""
        try:
            with open(self.path, "r") as f:
                header = f.readline().strip().lower()
                if "elevation" not in header and "z" not in header:
                    # 可能不是 CSV DEM
                    return False
                # 仅验证文件可读，数据按需读取
                return True
        except IOError:
            return False
    
    def read_elevation(self, x: float, y: float) -> Optional[float]:
        """读取指定坐标的高程值

        Args:
            x: 投影坐标 X (m)
            y: 投影坐标 Y (m)

        Returns:
            高程值 (m)，失败或命中 nodata 像素（如 -9999）返回 None
        """
        if self._rasterio and self._dataset:
            try:
                # 坐标转行列
                row, col = self._dataset.index(x, y)
                # 读取单个像素值（masked=True 让 nodata 像素可识别，
                # 否则 -9999 之类哨兵值会直接写进节点高程）
                value = self._dataset.read(1, window=(
                    (row, row + 1), (col, col + 1)
                ), masked=True)
                v = value[0][0]
                import numpy as np
                if np.ma.is_masked(v):
                    return None
                fv = float(v)
                nodata = self._dataset.nodata
                if nodata is not None and fv == float(nodata):
                    return None
                return fv
            except Exception:
                return None
        return None
    
    def read_elevations_batch(self, coords: List[Tuple[float, float]]) -> Dict[Tuple[float, float], Optional[float]]:
        """批量读取高程值"""
        result = {}
        for x, y in coords:
            result[(x, y)] = self.read_elevation(x, y)
        return result
    
    def close(self):
        """关闭 DEM 文件"""
        if self._dataset:
            self._dataset.close()
    
    @property
    def info(self) -> Optional[DemInfo]:
        return self._info


class TerrainAdapter:
    """地形适配器
    
    从 DEM 提取节点高程，更新 DripNetwork 中的节点。
    """
    
    def __init__(self, dem_path: Optional[str] = None):
        self.dem_path = dem_path
        self.reader: Optional[DemReader] = None
        self.elevation_stats: Dict[str, float] = {}
    
    def load_dem(self, path: str) -> bool:
        """加载 DEM 文件"""
        self.dem_path = path
        self.reader = DemReader(path)
        success = self.reader.open()
        if success and self.reader.info:
            self.elevation_stats = {
                "min": self.reader.info.min_elevation,
                "max": self.reader.info.max_elevation,
                "range": self.reader.info.max_elevation - self.reader.info.min_elevation,
            }
        return success
    
    def extract_elevations(self, network: 'DripNetwork') -> Dict[str, float]:
        """为管网中所有节点提取高程
        
        Args:
            network: 滴灌管网
            
        Returns:
            节点ID到高程的映射 {node_id: elevation}
        """
        result = {}
        if not self.reader:
            return result
        
        for nid, node in network.nodes.items():
            elev = self.reader.read_elevation(node.x, node.y)
            if elev is not None:
                node.elevation = elev
                result[nid] = elev
        
        return result
    
    def apply_to_network(self, network: 'DripNetwork') -> int:
        """提取高程并更新到网络，返回成功更新的节点数"""
        updated = self.extract_elevations(network)
        return len(updated)
