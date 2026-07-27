"""Builder 基类和参数"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List

from wdrip.topology import TopologyGraph
from wdrip.network import FieldInfo


@dataclass
class LayoutParams:
    """布局参数
    
    Attributes:
        planting_pattern: 耕作模式（覆盖 FieldInfo 中的值）
        row_spacings: 行距序列（m）
        ridge_count: 垄数
        plant_spacing: 株距（m）
        lateral_spacing: 毛管间距（m）
        emitter_spacing: 滴头间距（m）
        row_direction: 种植方向（度）
        mainline_strategy: 干管策略（along_long/short/center/boundary/manual）
        submain_strategy: 支管策略（equal/mst/skeleton/shortest_path）
        submain_spacing: 支管间距（m，等距模式用）
    """
    planting_pattern: str = "uniform"
    row_spacings: List[float] = field(default_factory=lambda: [0.5])
    ridge_count: Optional[int] = None
    plant_spacing: float = 0.3
    lateral_spacing: Optional[float] = None
    emitter_spacing: float = 0.3
    row_direction: float = 0.0
    mainline_strategy: str = "along_long"
    submain_strategy: str = "equal"
    submain_spacing: float = 50.0


class LayoutBuilder(ABC):
    """布局构建器基类
    
    所有 Builder 必须实现 build_topology() 方法，
    输出 TopologyGraph（不包含几何坐标）。
    """
    
    def __init__(self):
        self.graph = TopologyGraph()
    
    @abstractmethod
    def build_topology(self, field: FieldInfo, params: LayoutParams) -> TopologyGraph:
        """构建管网拓扑
        
        Args:
            field: 农田信息（含边界几何）
            params: 布局参数
            
        Returns:
            不含几何坐标的 TopologyGraph
        """
        pass
    
    def _generate_lateral_id(self, index: int) -> str:
        """生成毛管 ID"""
        return f"L{index:04d}"
    
    def _generate_emitter_id(self, lateral_id: str, index: int) -> str:
        """生成滴头 ID"""
        return f"E_{lateral_id}_{index:04d}"
    
    def _generate_junction_id(self, lateral_id: str) -> str:
        """生成连接节点 ID"""
        return f"J_{lateral_id}_start"
