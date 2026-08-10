"""滴灌管网节点模型"""

from abc import ABC
from dataclasses import dataclass
from typing import Optional


@dataclass
class DripNode(ABC):
    """管网节点基类
    
    Attributes:
        id: 节点唯一标识（如 "J001", "S001", "E001"）
        x: 地理坐标 X（投影坐标系，单位 m）
        y: 地理坐标 Y（投影坐标系，单位 m）
        elevation: 高程（单位 m），可从 DEM 自动提取
        description: 节点描述/备注
        tag: 节点标签（用于分组筛选）
    """
    id: str
    x: float
    y: float
    elevation: float = 0.0
    description: str = ""
    tag: str = ""


@dataclass
class SourceNode(DripNode):
    """水源节点 — 映射为 WNTR Reservoir
    
    Attributes:
        source_type: 水源类型（well=机井, reservoir=蓄水池, canal=河渠, outlet=出水口）
        available_flow: 可用流量（m³/s）
        head: 水头/扬程（m）
        water_quality: 初始水质（默认 0，用于水肥模拟）
    """
    source_type: str = "well"
    available_flow: float = 0.0
    head: float = 0.0
    water_quality: float = 0.0


@dataclass
class Junction(DripNode):
    """普通节点 — 映射为 WNTR Junction
    
    用于管道连接点、三通、弯头、支管连接点等。
    
    Attributes:
        demand: 需水量（m³/s），默认 0（非用水节点）
        demand_pattern: 需水量时变模式名称
    """
    demand: float = 0.0
    demand_pattern: Optional[str] = None


@dataclass
class EmitterNode(Junction):
    """滴头节点 — 映射为 WNTR Junction + emitter 属性
    
    沿毛管均匀分布，每个滴头位置一个 EmitterNode。
    在 WNTR 中表现为 Junction 节点附加发射器系数。
    
    Attributes:
        emitter_k: 滴头流量系数（L/h / m^x）
        emitter_x: 滴头流态指数
        emitter_spec: 关联的滴头规格型号（可选）
        lateral_id: 所属毛管 ID
        segment_index: 在毛管中的段序号（0-based）
    """
    emitter_k: float = 0.0
    emitter_x: float = 0.5
    emitter_spec: Optional['EmitterSpec'] = None
    lateral_id: Optional[str] = None
    segment_index: int = 0
