"""network — 滴灌管网数据模型

核心数据类：
- DripNode (基类): SourceNode / Junction / EmitterNode
- DripLink (基类): Pipe / Pump / Valve
- DripNetwork: 唯一数据源，包含节点、链路、农田信息、灌溉制度
- EmitterSpec: 滴头规格 + 内置参数库
- FieldInfo: 农田信息（支持 4 种耕作模式）
- IrrigationSchedule: 灌溉制度与轮灌分组
"""

from .nodes import DripNode, SourceNode, Junction, EmitterNode
from .links import DripLink, Pipe, Pump, Valve, ValveType, ValveStatus
from .emitter import (
    EmitterSpec,
    BUILTIN_EMITTERS,
    get_emitter_specs_by_manufacturer,
    list_manufacturers,
)
from .field import FieldInfo
from .schedule import IrrigationSchedule, IrrigationCycle, ShiftGroup
from .network import DripNetwork

__all__ = [
    # 节点
    "DripNode",
    "SourceNode",
    "Junction",
    "EmitterNode",
    # 链路
    "DripLink",
    "Pipe",
    "Pump",
    "Valve",
    "ValveType",
    "ValveStatus",
    # 滴头
    "EmitterSpec",
    "BUILTIN_EMITTERS",
    "get_emitter_specs_by_manufacturer",
    "list_manufacturers",
    # 农田
    "FieldInfo",
    # 灌溉
    "IrrigationSchedule",
    "IrrigationCycle",
    "ShiftGroup",
    # 管网
    "DripNetwork",
]
