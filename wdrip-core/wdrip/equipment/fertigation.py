"""施肥设备"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class FertilizerTank:
    """施肥罐
    
    Attributes:
        name: 名称
        volume: 容积（L）
        concentration: 母液浓度（%）
        injection_rate: 注入速率（L/h）
        working_pressure: 工作压力（m）
    """
    name: str = ""
    volume: float = 200.0
    concentration: float = 10.0
    injection_rate: float = 0.0
    working_pressure: float = 10.0


@dataclass
class Injector:
    """注肥泵
    
    Attributes:
        name: 型号
        flow_range: 流量范围（L/h）
        pressure_range: 压力范围（m）
        power: 功率（W）
    """
    name: str = ""
    flow_range: str = ""
    pressure_range: str = ""
    power: float = 0.0
