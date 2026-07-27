"""滴头规格参数"""

from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class EmitterSpec:
    """滴头规格型号
    
    定义滴头的水力特性参数，用于 EmitterNode 的自动配置。
    内置参数库可从 emitter_db 模块加载。
    
    Attributes:
        name: 型号名称（如 "DripperNet 16mm 1.6L/h"）
        manufacturer: 品牌/制造商（如 "Netafim"）
        k: 流量系数（L/h / m^x）
        x: 流态指数
            0.5 = 全紊流（Non-PC 滴头）
            0.0 ≈ 0 = 压力补偿式（PC 滴头）
        working_pressure_min: 最小工作压力（m）
        working_pressure_max: 最大工作压力（m）
        nominal_flow: 额定流量（L/h），在额定压力下测得
        recommended_pressure: 推荐工作压力（m），默认 10m
        is_pressure_compensating: 是否压力补偿式
        category: 使用类别（如 "drip_line", "button", "online"）
        notes: 备注
    """
    name: str
    manufacturer: str = ""
    k: float = 0.0
    x: float = 0.5
    working_pressure_min: float = 5.0
    working_pressure_max: float = 40.0
    nominal_flow: float = 1.6
    recommended_pressure: float = 10.0
    is_pressure_compensating: bool = False
    category: str = "drip_line"
    notes: str = ""

    def flow_at_pressure(self, pressure: float) -> float:
        """计算在给定压力下的滴头流量（L/h）
        
        Args:
            pressure: 工作压力（m）
            
        Returns:
            滴头流量（L/h）
        """
        if self.is_pressure_compensating:
            return self.nominal_flow
        if pressure <= 0:
            return 0.0
        return self.k * (pressure ** self.x)

    def validate(self) -> list:
        """检查参数合法性，返回错误列表"""
        errors = []
        if self.k <= 0 and not self.is_pressure_compensating:
            errors.append("非 PC 滴头必须指定 K 值（>0）")
        if not (0 <= self.x <= 1):
            errors.append("流态指数 x 应在 0~1 之间")
        if self.working_pressure_max <= self.working_pressure_min:
            errors.append("最大工作压力应大于最小工作压力")
        if self.nominal_flow <= 0:
            errors.append("额定流量必须大于 0")
        return errors


# 内置滴头参数库（部分常见型号）
BUILTIN_EMITTERS: Dict[str, EmitterSpec] = {
    "Netafim_DripperNet_16mm_1.6": EmitterSpec(
        name="DripperNet 16mm 1.6L/h",
        manufacturer="Netafim",
        k=0.506,
        x=0.5,
        working_pressure_min=5,
        working_pressure_max=40,
        nominal_flow=1.6,
        recommended_pressure=10,
        is_pressure_compensating=False,
        category="drip_line",
    ),
    "Netafim_DripperNet_16mm_2.0": EmitterSpec(
        name="DripperNet 16mm 2.0L/h",
        manufacturer="Netafim",
        k=0.632,
        x=0.5,
        working_pressure_min=5,
        working_pressure_max=40,
        nominal_flow=2.0,
        recommended_pressure=10,
        is_pressure_compensating=False,
        category="drip_line",
    ),
    "Netafim_PC_16mm_1.6": EmitterSpec(
        name="PC 16mm 1.6L/h",
        manufacturer="Netafim",
        k=1.6,  # PC 滴头 K 值约等于额定流量
        x=0.05,
        working_pressure_min=5,
        working_pressure_max=40,
        nominal_flow=1.6,
        recommended_pressure=10,
        is_pressure_compensating=True,
        category="drip_line",
    ),
    "Netafim_PC_16mm_2.0": EmitterSpec(
        name="PC 16mm 2.0L/h",
        manufacturer="Netafim",
        k=2.0,
        x=0.05,
        working_pressure_min=5,
        working_pressure_max=40,
        nominal_flow=2.0,
        recommended_pressure=10,
        is_pressure_compensating=True,
        category="drip_line",
    ),
    "RainBird_XFD_17mm_1.0": EmitterSpec(
        name="XFD 17mm 1.0L/h",
        manufacturer="RainBird",
        k=0.316,
        x=0.5,
        working_pressure_min=3,
        working_pressure_max=35,
        nominal_flow=1.0,
        recommended_pressure=10,
        is_pressure_compensating=False,
        category="drip_line",
    ),
    "RainBird_XFD_17mm_1.9": EmitterSpec(
        name="XFD 17mm 1.9L/h",
        manufacturer="RainBird",
        k=0.601,
        x=0.5,
        working_pressure_min=3,
        working_pressure_max=35,
        nominal_flow=1.9,
        recommended_pressure=10,
        is_pressure_compensating=False,
        category="drip_line",
    ),
    "Jain_JB_16mm_2.0": EmitterSpec(
        name="JB 16mm 2.0L/h",
        manufacturer="Jain Irrigation",
        k=0.632,
        x=0.5,
        working_pressure_min=4,
        working_pressure_max=35,
        nominal_flow=2.0,
        recommended_pressure=10,
        is_pressure_compensating=False,
        category="drip_line",
    ),
    "Jain_PC_16mm_2.0": EmitterSpec(
        name="PC 16mm 2.0L/h",
        manufacturer="Jain Irrigation",
        k=2.0,
        x=0.05,
        working_pressure_min=5,
        working_pressure_max=40,
        nominal_flow=2.0,
        recommended_pressure=10,
        is_pressure_compensating=True,
        category="drip_line",
    ),
    "Toro_DN_16mm_1.0": EmitterSpec(
        name="DN 16mm 1.0L/h",
        manufacturer="Toro",
        k=0.316,
        x=0.5,
        working_pressure_min=4,
        working_pressure_max=35,
        nominal_flow=1.0,
        recommended_pressure=10,
        is_pressure_compensating=False,
        category="drip_line",
    ),
    "Toro_PC_16mm_1.6": EmitterSpec(
        name="PC 16mm 1.6L/h",
        manufacturer="Toro",
        k=1.6,
        x=0.05,
        working_pressure_min=5,
        working_pressure_max=40,
        nominal_flow=1.6,
        recommended_pressure=10,
        is_pressure_compensating=True,
        category="drip_line",
    ),
}


def get_emitter_specs_by_manufacturer(manufacturer: str) -> Dict[str, EmitterSpec]:
    """按品牌筛选滴头参数"""
    return {k: v for k, v in BUILTIN_EMITTERS.items()
            if v.manufacturer == manufacturer}


def list_manufacturers() -> List[str]:
    """列出所有可用品牌"""
    return sorted(set(e.manufacturer for e in BUILTIN_EMITTERS.values()))
