"""terrain — 地形适配模块

从 DEM 栅格提取节点高程，计算管段坡度，
分析压力分区，推荐 PRV 减压阀位置。
"""

from .adapter import TerrainAdapter, DemReader
from .slope import SlopeAnalyzer, PressureZoneAnalyzer, PrvRecommender

__all__ = [
    "TerrainAdapter",
    "DemReader",
    "SlopeAnalyzer",
    "PressureZoneAnalyzer",
    "PrvRecommender",
]
