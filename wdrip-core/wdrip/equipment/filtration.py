"""过滤设备"""

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class FilterSpec:
    """过滤器基类参数"""
    name: str = ""
    mesh: int = 120              # 过滤精度（目数）
    rated_flow: float = 0.0      # 额定流量（m³/h）
    head_loss: float = 2.0       # 额定压损（m）
    price: float = 0.0


@dataclass
class SandFilter(FilterSpec):
    """砂石过滤器"""
    diameter: float = 0.0        # 罐体直径（mm）
    media_type: str = "quartz"   # 滤料类型


@dataclass
class ScreenFilter(FilterSpec):
    """筛网过滤器"""
    screen_area: float = 0.0     # 过滤面积（cm²）
    material: str = "stainless"  # 材质


@dataclass
class DiscFilter(FilterSpec):
    """叠片过滤器"""
    disc_count: int = 0          # 叠片数量
    disc_thickness: float = 0.0  # 叠片厚度（mm）
