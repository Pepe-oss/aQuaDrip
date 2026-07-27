"""HydraulicGraph — 水力计算图

在 TopologyGraph 的基础上附加工程参数，形成可直接转换为 WNTR 的水力模型。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from .graph import TopologyGraph, TopologyLevel

if TYPE_CHECKING:
    from wdrip.network import DripNetwork, EmitterNode, Pipe, Pump, Valve


@dataclass
class HydraulicNode:
    """水力计算节点
    
    Attributes:
        id: 节点 ID
        elevation: 高程（m）
        demand: 需水量（m³/s）
        demand_pattern: 需水量模式名
        emitter_k: 发射器 K 值（滴头用）
        emitter_x: 发射器 x 值（滴头用）
        node_type: 节点类型（junction/reservoir/tank/emitter）
        head: 水头（水源用）
    """
    id: str
    elevation: float = 0.0
    demand: float = 0.0
    demand_pattern: Optional[str] = None
    emitter_k: float = 0.0
    emitter_x: float = 0.5
    node_type: str = "junction"  # junction / reservoir / tank / emitter


@dataclass
class HydraulicLink:
    """水力计算链路
    
    Attributes:
        id: 链路 ID
        from_node: 起点节点
        to_node: 终点节点
        diameter: 管径（mm）
        length: 管长（m）
        roughness: 糙率
        minor_loss: 局部水头损失
        link_type: 类型（pipe/pump/valve）
        status: 状态（OPEN/CLOSED）
        # 泵参数
        pump_head: float
        pump_flow: float
        pump_curve: list
        # 阀参数
        valve_type: str
        valve_setting: float
    """
    id: str
    from_node: str
    to_node: str
    diameter: float = 0.0
    length: float = 0.0
    roughness: float = 130.0
    minor_loss: float = 0.0
    link_type: str = "pipe"
    status: str = "OPEN"
    # Pump
    pump_head: float = 0.0
    pump_flow: float = 0.0
    pump_curve: Optional[List[Tuple[float, float]]] = None
    # Valve
    valve_type: str = ""
    valve_setting: float = 0.0


class HydraulicGraph:
    """水力计算图
    
    在 TopologyGraph 的拓扑结构上附加工程参数，
    是 DripNetwork → WNTR 的中间层。
    """
    
    def __init__(self):
        self.nodes: Dict[str, HydraulicNode] = {}
        self.links: Dict[str, HydraulicLink] = {}
        self.topology: Optional[TopologyGraph] = None

    def build_from_network(self, network: 'DripNetwork') -> 'HydraulicGraph':
        """从 DripNetwork 构建水力计算图"""
        self.topology = TopologyGraph().build_from_network(network)
        
        # 转换节点
        for nid, node in network.nodes.items():
            hn = HydraulicNode(id=nid, elevation=node.elevation)
            
            if hasattr(node, "head") and node.head > 0:
                hn.node_type = "reservoir"
                hn.head = node.head
            if hasattr(node, "demand"):
                hn.demand = node.demand
                hn.demand_pattern = node.demand_pattern
            if hasattr(node, "emitter_k"):
                hn.node_type = "emitter"
                hn.emitter_k = node.emitter_k
                hn.emitter_x = node.emitter_x
            
            self.nodes[nid] = hn
        
        # 转换链路
        for lid, link in network.links.items():
            hl = HydraulicLink(
                id=lid,
                from_node=link.from_node,
                to_node=link.to_node,
            )
            
            if hasattr(link, "diameter"):
                hl.diameter = link.diameter
            if hasattr(link, "length"):
                hl.length = link.length
            if hasattr(link, "roughness"):
                hl.roughness = link.roughness
            if hasattr(link, "minor_loss"):
                hl.minor_loss = link.minor_loss
            if hasattr(link, "status"):
                hl.status = link.status
            
            if hasattr(link, "pump_type"):
                hl.link_type = "pump"
                hl.pump_head = link.rated_head
                hl.pump_flow = link.rated_flow
                hl.pump_curve = link.curve
            elif hasattr(link, "valve_type"):
                hl.link_type = "valve"
                hl.valve_type = link.valve_type.name if hasattr(link.valve_type, "name") else str(link.valve_type)
                hl.valve_setting = link.setting
            
            self.links[lid] = hl
        
        return self

    def to_wntr(self):
        """转换为 WNTR WaterNetworkModel
        
        暂未实现，Sprint 1.6 完成。
        """
        raise NotImplementedError("to_wntr() 将在 Sprint 1.6 实现")
