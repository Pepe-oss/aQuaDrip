"""topology — 拓扑引擎

核心原则：Geometry ≠ Topology。
拓扑图只描述"谁连接谁"，不包含任何几何坐标信息。
所有 Builder 输出 TopologyGraph，几何由独立层处理。
"""

from .graph import TopologyNode, TopologyEdge, TopologyGraph, TopologyLevel
from .hydraulic import HydraulicGraph

__all__ = [
    "TopologyNode",
    "TopologyEdge",
    "TopologyGraph",
    "TopologyLevel",
    "HydraulicGraph",
]
