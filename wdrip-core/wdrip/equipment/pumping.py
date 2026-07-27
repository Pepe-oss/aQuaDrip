"""水泵与变频设备"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class PumpSpec:
    """水泵规格（工程选型参数）
    
    与 DripLink.Pump 的区别：
    - PumpSpec：选型信息（品牌、型号、价格、曲线等）
    - DripLink.Pump：WNTR 水力参数（用于模拟）
    
    Attributes:
        name: 型号名称
        manufacturer: 品牌
        pump_type: 类型（centrifugal=离心泵, submersible=潜水泵）
        rated_head: 额定扬程（m）
        rated_flow: 额定流量（m³/h）
        rated_power: 额定功率（kW）
        efficiency: 效率（%）
        speed: 额定转速（rpm）
        curve: Q-H 曲线 [(flow, head), ...]
        price: 参考价格（元）
    """
    name: str = ""
    manufacturer: str = ""
    pump_type: str = "centrifugal"
    rated_head: float = 0.0
    rated_flow: float = 0.0
    rated_power: float = 0.0
    efficiency: float = 0.0
    speed: float = 0.0
    curve: Optional[List[Tuple[float, float]]] = None
    price: float = 0.0

    def to_link_params(self) -> dict:
        """转换为 DripLink.Pump 的参数"""
        return {
            "rated_head": self.rated_head,
            "rated_flow": self.rated_flow,
            "rated_power": self.rated_power,
            "efficiency": self.efficiency,
            "curve": self.curve,
        }


@dataclass
class VfdSpec:
    """变频器规格"""
    name: str = ""
    power: float = 0.0          # 适配功率（kW）
    min_speed: float = 0.3      # 最低转速比
    max_speed: float = 1.0      # 最高转速比
    price: float = 0.0
