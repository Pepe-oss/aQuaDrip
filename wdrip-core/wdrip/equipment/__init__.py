"""equipment — 设备系统（工程配置层）

6 大设备分类，每类包含选型参数、品牌型号等工程信息。
与 DripLink 的映射关系：
  - Equipment.Pump  → DripLink.Pump（水力参数）
  - Equipment.Valve → DripLink.Valve（阀设定值）
  - Filter          → Pipe + 局部水头损失
  - FertilizerTank  → Junction + 水质初始条件
  - Sensor          → 监测点（不参与水力计算）
"""

from .source import Well, Reservoir, Canal, Outlet
from .pumping import PumpSpec, VfdSpec
from .filtration import SandFilter, ScreenFilter, DiscFilter
from .fertigation import FertilizerTank, Injector
from .control import ValveSpec, PrvSpec, SolenoidSpec, FcvSpec, PsvSpec
from .sensor import PressureGauge, FlowMeter, EcProbe, PhProbe
from .container import EquipmentSet

__all__ = [
    "Well", "Reservoir", "Canal", "Outlet",
    "PumpSpec", "VfdSpec",
    "SandFilter", "ScreenFilter", "DiscFilter",
    "FertilizerTank", "Injector",
    "ValveSpec", "PrvSpec", "SolenoidSpec", "FcvSpec", "PsvSpec",
    "PressureGauge", "FlowMeter", "EcProbe", "PhProbe",
    "EquipmentSet",
]
