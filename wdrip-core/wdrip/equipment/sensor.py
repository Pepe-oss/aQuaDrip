"""传感器设备"""

from dataclasses import dataclass


@dataclass
class PressureGauge:
    """压力表"""
    name: str = ""
    range: str = "0-60m"
    accuracy: str = "0.5%"
    price: float = 0.0


@dataclass
class FlowMeter:
    """流量计"""
    name: str = ""
    range: str = ""
    accuracy: str = "1.0%"
    price: float = 0.0


@dataclass
class EcProbe:
    """EC 传感器"""
    name: str = ""
    range: str = "0-10 dS/m"
    accuracy: str = "0.1 dS/m"
    price: float = 0.0


@dataclass
class PhProbe:
    """pH 传感器"""
    name: str = ""
    range: str = "0-14 pH"
    accuracy: str = "0.1 pH"
    price: float = 0.0
