"""DripNetwork — 滴灌管网唯一数据源"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from .nodes import DripNode, SourceNode, Junction, EmitterNode
from .links import DripLink, Pipe, Pump, Valve, ValveType, ValveStatus
from .emitter import EmitterSpec
from .field import FieldInfo
from .schedule import IrrigationSchedule, IrrigationCycle, ShiftGroup


@dataclass
class DripNetwork:
    """滴灌管网 — 唯一数据源（One Source of Truth）
    
    所有管网信息集中存储于此，不分散在多个对象中。
    转换为 WNTR 模型必须通过此对象。
    
    Attributes:
        name: 管网名称
        field_info: 农田信息
        nodes: 节点字典 {node_id: DripNode}
        links: 链路字典 {link_id: DripLink}
        schedule: 灌溉制度
        units: 单位制（"SI" 或 "US"）
    """
    name: str = ""
    field_info: Optional[FieldInfo] = None
    nodes: Dict[str, DripNode] = field(default_factory=dict)
    links: Dict[str, DripLink] = field(default_factory=dict)
    schedule: Optional[IrrigationSchedule] = None
    units: str = "SI"

    # ---- 节点操作方法 ----

    def add_node(self, node: DripNode):
        """添加节点"""
        if node.id in self.nodes:
            raise KeyError(f"节点 {node.id} 已存在")
        self.nodes[node.id] = node

    def get_node(self, node_id: str) -> Optional[DripNode]:
        """获取节点"""
        return self.nodes.get(node_id)

    def remove_node(self, node_id: str):
        """删除节点及其关联的链路"""
        if node_id not in self.nodes:
            raise KeyError(f"节点 {node_id} 不存在")
        # 删除关联链路
        to_remove = [
            lid for lid, link in self.links.items()
            if link.from_node == node_id or link.to_node == node_id
        ]
        for lid in to_remove:
            del self.links[lid]
        del self.nodes[node_id]

    def get_nodes_by_type(self, node_type: type) -> List[DripNode]:
        """按类型获取节点"""
        return [n for n in self.nodes.values() if isinstance(n, node_type)]

    # ---- 链路操作方法 ----

    def add_link(self, link: DripLink):
        """添加链路"""
        if link.id in self.links:
            raise KeyError(f"链路 {link.id} 已存在")
        # 验证起止节点存在
        if link.from_node not in self.nodes:
            raise KeyError(f"起点节点 {link.from_node} 不存在")
        if link.to_node not in self.nodes:
            raise KeyError(f"终点节点 {link.to_node} 不存在")
        self.links[link.id] = link

    def get_link(self, link_id: str) -> Optional[DripLink]:
        """获取链路"""
        return self.links.get(link_id)

    def remove_link(self, link_id: str):
        """删除链路"""
        if link_id not in self.links:
            raise KeyError(f"链路 {link_id} 不存在")
        del self.links[link_id]

    def get_links_by_type(self, link_type: type) -> List[DripLink]:
        """按类型获取链路"""
        return [l for l in self.links.values() if isinstance(l, link_type)]

    def get_links_by_pipe_type(self, pipe_type: str) -> List[Pipe]:
        """按管道类型获取（mainline/submain/lateral）"""
        return [
            l for l in self.links.values()
            if isinstance(l, Pipe) and l.pipe_type == pipe_type
        ]

    def get_adjacent_links(self, node_id: str) -> List[DripLink]:
        """获取与指定节点相邻的所有链路"""
        return [
            l for l in self.links.values()
            if l.from_node == node_id or l.to_node == node_id
        ]

    # ---- 统计属性 ----

    @property
    def emitter_count(self) -> int:
        """滴头数量"""
        return len(self.get_nodes_by_type(EmitterNode))

    @property
    def pipe_length_by_type(self) -> Dict[str, float]:
        """按类型统计管道总长（m）"""
        result = {"mainline": 0.0, "submain": 0.0, "lateral": 0.0}
        for link in self.links.values():
            if isinstance(link, Pipe) and link.pipe_type in result:
                result[link.pipe_type] += link.length
        return result

    @property
    def total_pipe_length(self) -> float:
        """管道总长（m）"""
        return sum(l.length for l in self.links.values() if isinstance(l, Pipe))

    # ---- 验证 ----

    def validate(self) -> List[str]:
        """模型验证，返回错误列表
        
        检查项：
        1. 所有链路的起止节点是否存在
        2. 是否有孤立节点（不连接任何链路）
        3. Pump 方向验证（进水/出水侧检查）
        4. PRV 方向验证（高压/低压侧检查）
        5. 所有 EmitterNode 是否属于某条毛管
        6. 农田参数合法性
        """
        errors = []

        # 1. 链路起止节点完整性
        for lid, link in self.links.items():
            if link.from_node not in self.nodes:
                errors.append(f"链路 {lid} 的起点节点 {link.from_node} 不存在")
            if link.to_node not in self.nodes:
                errors.append(f"链路 {lid} 的终点节点 {link.to_node} 不存在")

        # 2. 孤立节点
        connected_nodes = set()
        for link in self.links.values():
            connected_nodes.add(link.from_node)
            connected_nodes.add(link.to_node)
        for nid in self.nodes:
            if nid not in connected_nodes:
                errors.append(f"节点 {nid} 是孤立节点（不连接任何管道）")

        # 3. Pump 方向验证
        for lid, link in self.links.items():
            if isinstance(link, Pump):
                from_node = self.nodes.get(link.from_node)
                to_node = self.nodes.get(link.to_node)
                # 简单检查：进水侧不应是 EmitterNode
                if isinstance(from_node, EmitterNode):
                    errors.append(
                        f"水泵 {lid} 的进水侧（from_node={link.from_node}）"
                        f"是 EmitterNode，水泵应从水源/干管侧取水"
                    )

        # 4. PRV 方向验证
        for lid, link in self.links.items():
            if isinstance(link, Valve) and link.valve_type == ValveType.PRV:
                # PRV 的 from_node 应为高压侧
                if link.has_direction and link.setting <= 0:
                    errors.append(
                        f"PRV {lid} 设定值无效（{link.setting}），应大于 0"
                    )

        # 5. EmitterNode 检查
        for nid, node in self.nodes.items():
            if isinstance(node, EmitterNode):
                if not node.lateral_id:
                    errors.append(f"滴头 {nid} 未关联到任何毛管")
                elif node.lateral_id not in self.links:
                    errors.append(
                        f"滴头 {nid} 关联的毛管 {node.lateral_id} 不存在"
                    )

        # 6. 农田参数检查
        if self.field_info:
            errors.extend(self.field_info.validate())

        return errors

    # ---- 转换为 WNTR（占位，Phase 1.6 实现） ----

    def to_wntr(self):
        """转换为 WNTR WaterNetworkModel
        
        暂未实现，Phase 1.6（模拟封装）时完成。
        """
        raise NotImplementedError("to_wntr() 将在 Sprint 1.6 实现")

    def to_hydraulic_graph(self):
        """生成水力计算图
        
        暂未实现，Phase 1.2（拓扑引擎）时完成。
        """
        raise NotImplementedError("to_hydraulic_graph() 将在 Sprint 1.2 实现")
