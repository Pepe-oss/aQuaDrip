"""控制设备（阀门）"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ValveSpec:
    """通用阀门规格"""
    name: str = ""
    diameter: float = 0.0
    pressure_rating: float = 0.0   # 公称压力（MPa）
    material: str = "brass"
    price: float = 0.0


@dataclass
class PrvSpec:
    """减压阀"""
    name: str = ""
    diameter: float = 0.0
    adjustable_range: str = ""   # 调节范围（如 "5-40m"）
    default_setting: float = 20.0
    price: float = 0.0


@dataclass
class SolenoidSpec:
    """电磁阀"""
    name: str = ""
    diameter: float = 0.0
    voltage: str = "24VAC"
    normally_open: bool = False
    price: float = 0.0


@dataclass
class FcvSpec:
    """流量控制阀"""
    name: str = ""
    diameter: float = 0.0
    flow_setting: float = 0.0  # 设定流量（m³/h）
    price: float = 0.0


@dataclass
class PsvSpec:
    """持压阀"""
    name: str = ""
    diameter: float = 0.0
    pressure_setting: float = 0.0
    price: float = 0.0
