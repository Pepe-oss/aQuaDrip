"""EquipmentSet — 设备容器

管理管网中所有设备的工程配置信息，
提供设备到 DripLink 参数的映射能力。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from .source import Well, Reservoir, Canal, Outlet
from .pumping import PumpSpec, VfdSpec
from .filtration import SandFilter, ScreenFilter, DiscFilter
from .fertigation import FertilizerTank, Injector
from .control import ValveSpec, PrvSpec, SolenoidSpec, FcvSpec, PsvSpec
from .sensor import PressureGauge, FlowMeter, EcProbe, PhProbe

if TYPE_CHECKING:
    from wdrip.network import DripLink, Pump as LinkPump, Valve as LinkValve


@dataclass
class EquipmentSet:
    """设备集合（DripNetwork 的 equipment 属性）
    
    按 6 大分类组织设备，每类设备关联到对应的管网元素 ID。
    """
    # 水源
    wells: Dict[str, Well] = field(default_factory=dict)         # {node_id: Well}
    reservoirs: Dict[str, Reservoir] = field(default_factory=dict)
    canals: Dict[str, Canal] = field(default_factory=dict)
    outlets: Dict[str, Outlet] = field(default_factory=dict)
    # 水泵
    pump_specs: Dict[str, PumpSpec] = field(default_factory=dict)  # {link_id: PumpSpec}
    vfds: Dict[str, VfdSpec] = field(default_factory=dict)
    # 过滤
    sand_filters: Dict[str, SandFilter] = field(default_factory=dict)
    screen_filters: Dict[str, ScreenFilter] = field(default_factory=dict)
    disc_filters: Dict[str, DiscFilter] = field(default_factory=dict)
    # 施肥
    fertilizer_tanks: Dict[str, FertilizerTank] = field(default_factory=dict)
    injectors: Dict[str, Injector] = field(default_factory=dict)
    # 控制
    valve_specs: Dict[str, ValveSpec] = field(default_factory=dict)
    prv_specs: Dict[str, PrvSpec] = field(default_factory=dict)
    solenoid_specs: Dict[str, SolenoidSpec] = field(default_factory=dict)
    fcv_specs: Dict[str, FcvSpec] = field(default_factory=dict)
    psv_specs: Dict[str, PsvSpec] = field(default_factory=dict)
    # 传感器
    pressure_gauges: Dict[str, PressureGauge] = field(default_factory=dict)
    flow_meters: Dict[str, FlowMeter] = field(default_factory=dict)
    ec_probes: Dict[str, EcProbe] = field(default_factory=dict)
    ph_probes: Dict[str, PhProbe] = field(default_factory=dict)

    @property
    def total_count(self) -> int:
        """设备总数"""
        return sum(len(d) for d in self.__dict__.values() if isinstance(d, dict))

    def add_pump_spec(self, link_id: str, spec: PumpSpec):
        """添加水泵规格并返回可用的参数字典"""
        self.pump_specs[link_id] = spec
        return spec.to_link_params()

    def apply_to_link(self, link_id: str, link: 'DripLink') -> dict:
        """将设备参数应用到 DripLink
        
        从 EquipmentSet 中查找对应设备配置，
        返回可设置到 DripLink 上的参数字典。
        无对应配置时返回空字典。
        """
        params = {}
        # 泵
        if link_id in self.pump_specs and hasattr(link, "pump_type"):
            params.update(self.pump_specs[link_id].to_link_params())
        # 阀
        if link_id in self.prv_specs and hasattr(link, "valve_type"):
            params["setting"] = self.prv_specs[link_id].default_setting
        if link_id in self.fcv_specs and hasattr(link, "valve_type"):
            params["setting"] = self.fcv_specs[link_id].flow_setting
        if link_id in self.psv_specs and hasattr(link, "valve_type"):
            params["setting"] = self.psv_specs[link_id].pressure_setting
        return params
