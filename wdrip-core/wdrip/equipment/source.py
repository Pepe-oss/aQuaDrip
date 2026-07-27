"""水源设备"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Well:
    """机井
    
    Attributes:
        name: 机井名称/编号
        depth: 井深（m）
        static_level: 静水位（m，地面以下）
        dynamic_level: 动水位（m，抽水时）
        yield_rate: 出水量（m³/h）
        head: 扬程（m）
    """
    name: str = ""
    depth: float = 0.0
    static_level: float = 0.0
    dynamic_level: float = 0.0
    yield_rate: float = 0.0
    head: float = 0.0


@dataclass
class Reservoir:
    """蓄水池
    
    Attributes:
        name: 名称
        capacity: 库容（m³）
        water_level: 当前水位（m）
        bottom_level: 池底高程（m）
        diameter: 直径（m，圆形池用）
    """
    name: str = ""
    capacity: float = 0.0
    water_level: float = 0.0
    bottom_level: float = 0.0
    diameter: float = 0.0


@dataclass
class Canal:
    """河渠取水点"""
    name: str = ""
    flow_rate: float = 0.0
    head: float = 0.0


@dataclass
class Outlet:
    """出水口（从地下管道引到地面的出水点）
    
    Attributes:
        name: 名称
        diameter: 口径（mm）
        pressure: 出水口压力（m）
        is_control: 是否有阀门控制
    """
    name: str = ""
    diameter: float = 0.0
    pressure: float = 0.0
    is_control: bool = False
