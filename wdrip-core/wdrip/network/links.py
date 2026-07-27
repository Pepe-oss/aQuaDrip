"""滴灌管网管道/链路模型

重要：Pump（水泵）和 Valve（阀门）均为 Link 类型（继承自 DripLink），
不是 Node。在 WNTR/EPANET 中它们都是 Link（边），连接两个节点。
在 QGIS 中渲染为 LineString（线要素）。
"""

from abc import ABC
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, List, Tuple


class ValveType(Enum):
    """阀门类型"""
    GATE = "GATE"           # 手动闸阀
    PRV = "PRV"             # 减压阀（有方向：高压侧→低压侧）
    FCV = "FCV"             # 流量控制阀（有方向）
    PSV = "PSV"             # 持压阀（有方向）
    SOLENOID = "SOLENOID"   # 电磁阀（有方向）
    CHECK = "CHECK"         # 止回阀（有方向：from→to 为正向）
    GPV = "GPV"             # 通用阀（有方向）


class ValveStatus(Enum):
    """阀门状态"""
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class DripLink(ABC):
    """管网链路基类
    
    所有 Link 有明确的方向：from_node → to_node。
    Pipe 双向流通，方向仅用于定义拓扑。
    Pump 和 Valve 有方向约束。
    
    Attributes:
        id: 链路唯一标识（如 "P001", "L001", "PU001", "V001"）
        from_node: 起点节点 ID（定义正方向）
        to_node: 终点节点 ID
        description: 描述/备注
        tag: 标签
    """
    id: str
    from_node: str
    to_node: str
    description: str = ""
    tag: str = ""

    @property
    def direction(self) -> str:
        """正方向描述"""
        return f"{self.from_node} \u2192 {self.to_node}"

    def reverse(self):
        """反转方向：交换 from_node 和 to_node"""
        self.from_node, self.to_node = self.to_node, self.from_node


@dataclass
class Pipe(DripLink):
    """管道 — 映射为 WNTR Pipe，双向流通
    
    管道类型由 pipe_type 区分：
    - "mainline": 干管
    - "submain": 支管
    - "lateral": 毛管
    
    毛管（Lateral）特殊说明：
    - from_node：如果没有支管连接则为第一个 EmitterNode，
      有支管交叉连接时为交叉点生成的 Junction
    - to_node：最后一个 EmitterNode（末端）
    - 沿毛管均匀分布的是 EmitterNode（滴头节点）
    - 转换为 WNTR 时展开为多段 Pipe 连接相邻节点
    
    Attributes:
        pipe_type: 管道类型（mainline/submain/lateral）
        diameter: 管径（mm）
        length: 管长（m）
        roughness: 糙率系数（HW 公式默认 130，DW 公式为糙率高度 mm）
        material: 材质（PE/PVC/Steel 等）
        minor_loss: 局部水头损失系数
        status: 状态（OPEN/CLOSED，默认 OPEN）
    """
    pipe_type: str = "mainline"  # mainline / submain / lateral
    diameter: float = 0.0        # mm
    length: float = 0.0          # m
    roughness: float = 130.0     # HW C 值
    material: str = "PE"
    minor_loss: float = 0.0
    status: str = "OPEN"


@dataclass
class Pump(DripLink):
    """水泵 — 映射为 WNTR Pump（Link 类型）
    
    方向约束：
    - from_node = 进水侧（吸入端，suction side）
    - to_node = 出水侧（压出端，discharge side）
    - WNTR 中 Pump 不允许反向流动
    - 用户绘制时：先点击进水端 → 再点击出水端
    
    Attributes:
        pump_type: 水泵类型（centrifugal=离心泵, submersible=潜水泵）
        rated_head: 额定扬程（m）
        rated_flow: 额定流量（m³/h）
        rated_power: 额定功率（kW）
        efficiency: 效率（%，0-100）
        speed: 转速比（VFD 变频控制，默认 1.0）
        curve: Q-H 曲线点集 [(flow, head), ...]
        is_reversible: 是否可反转（默认 False）
    """
    pump_type: str = "centrifugal"
    rated_head: float = 0.0      # m
    rated_flow: float = 0.0      # m³/h
    rated_power: float = 0.0     # kW
    efficiency: float = 0.0      # %
    speed: float = 1.0
    curve: Optional[List[Tuple[float, float]]] = None
    is_reversible: bool = False


@dataclass
class Valve(DripLink):
    """阀门 — 映射为 WNTR Valve（Link 类型）
    
    方向约束：
    - PRV: from_node = 高压侧, to_node = 低压侧
    - FCV/PSV/GPV/SOLENOID/CHECK: 有方向性
    - GATE（手动闸阀）: 双向，无方向约束
    
    Attributes:
        valve_type: 阀门类型（ValveType 枚举）
        setting: 设定值（PRV=压力 m, FCV=流量, PSV=压力）
        status: 状态（OPEN/CLOSED）
        diameter: 口径（mm）
        has_direction: 是否有方向约束
        minor_loss: 局部水头损失系数
    """
    valve_type: ValveType = ValveType.GATE
    setting: float = 0.0
    status: ValveStatus = ValveStatus.OPEN
    diameter: float = 0.0        # mm
    minor_loss: float = 0.0

    @property
    def has_direction(self) -> bool:
        """是否有方向约束"""
        return self.valve_type in (
            ValveType.PRV, ValveType.FCV, ValveType.PSV,
            ValveType.SOLENOID, ValveType.CHECK, ValveType.GPV,
        )
