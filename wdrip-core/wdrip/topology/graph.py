"""拓扑图：TopologyNode / TopologyEdge / TopologyGraph

拓扑图是管网的"骨架"，只描述节点间的连接关系，
不包含任何几何坐标。这是整个系统的核心抽象。
"""

from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Set, Tuple


class TopologyLevel(IntEnum):
    """拓扑层级"""
    MAINLINE = 0   # 干管
    SUBMAIN = 1    # 支管
    LATERAL = 2    # 毛管
    OTHER = 9      # 其他（泵阀等）


@dataclass
class TopologyNode:
    """拓扑节点
    
    只包含连接关系，不包含坐标。
    
    Attributes:
        id: 节点 ID（与 DripNode.id 对应）
        level: 所在层级
        adjacent: 相邻节点 ID 列表
        parent: 父节点 ID（树状拓扑中，朝向水源的方向）
        children: 子节点 ID 列表
    """
    id: str
    level: TopologyLevel = TopologyLevel.OTHER
    adjacent: Set[str] = field(default_factory=set)
    parent: Optional[str] = None
    children: Set[str] = field(default_factory=set)

    def add_adjacent(self, node_id: str):
        self.adjacent.add(node_id)

    def remove_adjacent(self, node_id: str):
        self.adjacent.discard(node_id)

    @property
    def degree(self) -> int:
        """度数（连接的边数）"""
        return len(self.adjacent)

    @property
    def is_leaf(self) -> bool:
        """是否为叶子节点（度数为 1）"""
        return self.degree == 1

    @property
    def is_isolated(self) -> bool:
        """是否孤立（度数为 0）"""
        return self.degree == 0


@dataclass
class TopologyEdge:
    """拓扑边
    
    只描述连接关系，不包含管径/长度等工程参数。
    
    Attributes:
        id: 边 ID（与 DripLink.id 对应）
        from_node: 起点节点 ID
        to_node: 终点节点 ID
        edge_type: 边的实际类型（pipe/pump/valve）
        level: 所在层级
    """
    id: str
    from_node: str
    to_node: str
    edge_type: str = "pipe"   # pipe / pump / valve
    level: TopologyLevel = TopologyLevel.OTHER

    @property
    def nodes(self) -> Tuple[str, str]:
        """两端节点"""
        return (self.from_node, self.to_node)

    def other_end(self, node_id: str) -> Optional[str]:
        """获取边的另一端节点"""
        if node_id == self.from_node:
            return self.to_node
        if node_id == self.to_node:
            return self.from_node
        return None

    def contains_node(self, node_id: str) -> bool:
        """是否包含指定节点"""
        return node_id in (self.from_node, self.to_node)


class TopologyGraph:
    """拓扑图 — 管网的连接骨架
    
    不包含任何几何坐标信息，是 Geometry 的上层抽象。
    """
    
    def __init__(self):
        self.nodes: Dict[str, TopologyNode] = {}
        self.edges: Dict[str, TopologyEdge] = {}

    # ---- 节点操作 ----

    def add_node(self, node_id: str, level: TopologyLevel = TopologyLevel.OTHER) -> TopologyNode:
        """添加节点"""
        if node_id not in self.nodes:
            self.nodes[node_id] = TopologyNode(id=node_id, level=level)
        return self.nodes[node_id]

    def remove_node(self, node_id: str):
        """删除节点及其关联的边"""
        if node_id not in self.nodes:
            return
        # 删除关联边
        to_remove = [eid for eid, e in self.edges.items()
                     if e.contains_node(node_id)]
        for eid in to_remove:
            self.remove_edge(eid)
        del self.nodes[node_id]

    def get_node(self, node_id: str) -> Optional[TopologyNode]:
        return self.nodes.get(node_id)

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    # ---- 边操作 ----

    def add_edge(self, edge_id: str, from_node: str, to_node: str,
                 edge_type: str = "pipe",
                 level: TopologyLevel = TopologyLevel.OTHER) -> TopologyEdge:
        """添加边，自动创建不存在的节点"""
        # 确保两端节点存在
        self.add_node(from_node, level)
        self.add_node(to_node, level)
        
        edge = TopologyEdge(
            id=edge_id,
            from_node=from_node,
            to_node=to_node,
            edge_type=edge_type,
            level=level,
        )
        self.edges[edge_id] = edge
        
        # 更新邻接关系
        self.nodes[from_node].add_adjacent(to_node)
        self.nodes[to_node].add_adjacent(from_node)
        
        return edge

    def remove_edge(self, edge_id: str):
        """删除边"""
        if edge_id not in self.edges:
            return
        edge = self.edges[edge_id]
        # 更新邻接关系
        if edge.from_node in self.nodes:
            self.nodes[edge.from_node].remove_adjacent(edge.to_node)
        if edge.to_node in self.nodes:
            self.nodes[edge.to_node].remove_adjacent(edge.from_node)
        del self.edges[edge_id]

    def get_edge(self, edge_id: str) -> Optional[TopologyEdge]:
        return self.edges.get(edge_id)

    # ---- 构建 ----

    def build_from_network(self, network) -> 'TopologyGraph':
        """从 DripNetwork 构建拓扑图"""
        for nid in network.nodes:
            self.add_node(nid)
        for lid, link in network.links.items():
            edge_type = "pipe"
            if hasattr(link, "pump_type"):
                edge_type = "pump"
            elif hasattr(link, "valve_type"):
                edge_type = "valve"
            
            # 确定层级
            level = TopologyLevel.OTHER
            if hasattr(link, "pipe_type"):
                if link.pipe_type == "mainline":
                    level = TopologyLevel.MAINLINE
                elif link.pipe_type == "submain":
                    level = TopologyLevel.SUBMAIN
                elif link.pipe_type == "lateral":
                    level = TopologyLevel.LATERAL
            
            self.add_edge(lid, link.from_node, link.to_node,
                         edge_type=edge_type, level=level)
        return self

    # ---- 拓扑验证 ----

    def validate(self) -> List[str]:
        """拓扑验证，返回错误列表"""
        errors = []
        errors.extend(self._check_isolated_nodes())
        errors.extend(self._check_connectivity())
        errors.extend(self._check_loops())
        errors.extend(self._check_dead_ends())
        return errors

    def _check_isolated_nodes(self) -> List[str]:
        """检查孤立节点"""
        errors = []
        for nid, node in self.nodes.items():
            if node.is_isolated:
                errors.append(f"节点 {nid} 孤立（不连接任何边）")
        return errors

    def _check_connectivity(self) -> List[str]:
        """检查连通性：是否所有节点都能从水源到达"""
        if not self.nodes:
            return []
        # 找到水源节点（level=OTHER 且度数>=1 的节点作为候选）
        # 实际水源由 DripNetwork 中的 SourceNode 标识
        # 这里只做基础检查
        start = next(iter(self.nodes))
        visited = self._bfs(start)
        unreachable = [nid for nid in self.nodes if nid not in visited]
        if unreachable:
            return [f"存在不连通的分量：{unreachable[:5]}...（共{len(unreachable)}个）"]
        return []

    def _check_loops(self) -> List[str]:
        """检测环路（滴灌管网通常为树状）

        按连通分量判断：若某分量内边数 >= 节点数则该分量含环。
        全局边数 >= 节点数只对单连通管网成立，多分量管网（如分区
        灌溉、环状干管）会被误报，因此必须分分量统计。
        """
        errors = []
        for comp_nodes in self._connected_components():
            # 统计属于该分量的边（两端节点都在分量内）
            comp_set = set(comp_nodes)
            edge_count = sum(
                1 for e in self.edges.values()
                if e.from_node in comp_set and e.to_node in comp_set
            )
            node_count = len(comp_nodes)
            if edge_count >= node_count:
                errors.append(
                    f"检测到环路：分量({comp_nodes[:3]}{'...' if len(comp_nodes) > 3 else ''})"
                    f" 边数({edge_count}) >= 节点数({node_count})")
        return errors

    def _check_dead_ends(self) -> List[str]:
        """检测死管（度数=1 的非末端节点）"""
        errors = []
        for nid, node in self.nodes.items():
            if node.degree == 1 and node.level == TopologyLevel.MAINLINE:
                errors.append(f"干管节点 {nid} 为死端（度数=1），请检查")
        return errors

    def _connected_components(self) -> List[List[str]]:
        """返回所有连通分量（节点 ID 列表的列表）"""
        visited: Set[str] = set()
        components: List[List[str]] = []
        for nid in self.nodes:
            if nid in visited:
                continue
            comp = self._bfs(nid)
            visited |= comp
            components.append(list(comp))
        return components

    def _bfs(self, start: str) -> Set[str]:
        """广度优先搜索"""
        visited = set()
        queue = deque([start])
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            node = self.nodes.get(nid)
            if node:
                for adj in node.adjacent:
                    if adj not in visited:
                        queue.append(adj)
        return visited

    # ---- 查询 ----

    def get_upstream_nodes(self, node_id: str) -> List[str]:
        """获取上游节点（BFS 朝向水源）"""
        # Simple BFS from node outward
        visited = set()
        queue = deque([node_id])
        result = []
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            result.append(nid)
            node = self.nodes.get(nid)
            if node:
                for adj in node.adjacent:
                    if adj not in visited:
                        queue.append(adj)
        return result

    def get_downstream_nodes(self, node_id: str) -> List[str]:
        """获取下游节点"""
        # 同 get_upstream_nodes，但按树状拓扑的 children 方向
        node = self.nodes.get(node_id)
        if not node:
            return []
        visited = set()
        queue = deque(node.children)
        result = []
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            result.append(nid)
            child_node = self.nodes.get(nid)
            if child_node:
                for c in child_node.children:
                    if c not in visited:
                        queue.append(c)
        return result

    def hierarchy(self) -> Dict[int, List[str]]:
        """按层级分组"""
        result = {level: [] for level in TopologyLevel}
        for eid, edge in self.edges.items():
            result[edge.level].append(eid)
        return result

    # ---- 统计 ----

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def is_tree(self) -> bool:
        """是否为树状结构（滴灌管网应为树状）"""
        return self.edge_count == self.node_count - 1

    # ---- 序列化 ----

    def to_dict(self) -> dict:
        """导出为字典（用于序列化）"""
        return {
            "nodes": {nid: {"level": node.level.value, "adjacent": list(node.adjacent)}
                      for nid, node in self.nodes.items()},
            "edges": {eid: {"from": edge.from_node, "to": edge.to_node,
                            "type": edge.edge_type, "level": edge.level.value}
                      for eid, edge in self.edges.items()},
        }
