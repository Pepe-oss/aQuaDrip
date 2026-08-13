# -*- coding: utf-8 -*-
"""校准算法接口 + Hazen-Williams 实现 + 拓扑顺序校准

算法通过 CalibrationAlgorithm 基类注册，calibration_dialog 自动发现。
"""

from abc import ABC, abstractmethod
from collections import deque
from typing import Dict, List, Optional, Set, Tuple, FrozenSet


class CalibrationAlgorithm(ABC):
    """校准算法基类

    子类必须实现:
      - name (str): 唯一标识
      - label (str): 中文显示名
      - description (str): 说明
      - calibrate(obs_data) -> dict
    """

    name: str = "base"
    label: str = "基础算法"
    description: str = ""

    def __init__(self, iface, params: dict = None):
        self.iface = iface
        self.params = params or {}
        self.net = None

    @abstractmethod
    def calibrate(self, obs_data: dict) -> dict:
        """执行一次校准

        Args:
            obs_data: {label: (x, y, P_sim, P_obs, Q_sim, Q_obs)}

        Returns:
            {"rmse": float, "details": [(lid, pipe_type, old_c, new_c, delta), ...]}
        """
        ...


# 注册表（calibration_dialog 读取）
ALGORITHMS: Dict[str, type] = {}


def register_algorithm(cls):
    """装饰器：注册校准算法"""
    ALGORITHMS[cls.name] = cls
    return cls


# ── 共享工具方法 ──

DEFAULT_C_LIMITS = {
    "mainline": (100, 150),
    "submain": (90, 140),
    "lateral": (80, 130),
}


def _build_downstream_graph(net) -> Dict[str, List[Tuple]]:
    """构建有向下游图（仅 from→to 方向）。

    DirectionFixer 已确保 from_node 朝向水源侧。
    """
    graph: Dict[str, List] = {nid: [] for nid in net.nodes}
    for lid, link in net.net_links() if hasattr(net, 'net_links') else net.links.items():
        fn, tn = link.from_node, link.to_node
        graph.setdefault(fn, []).append((lid, link, tn))
    return graph


def _bfs_upstream_pipes(graph, sources) -> Dict[str, Set[str]]:
    """BFS 从水源出发，记录每个节点的上游管道集合。

    Returns:
        {node_id: set_of_upstream_pipe_ids}
    """
    node_upstream: Dict[str, Set[str]] = {}
    for src in sources:
        queue = deque([(src, set())])
        visited = set()
        while queue:
            node, us = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            # 合并上游（一个节点可能从多条路径到达）
            if node in node_upstream:
                node_upstream[node] |= us
            else:
                node_upstream[node] = set(us)
            for lid, link, nx in graph.get(node, []):
                queue.append((nx, us | {lid}))
    return node_upstream


def _nearest_node(net, ox, oy) -> Optional[str]:
    """找距离 (ox, oy) 最近的节点"""
    bd, bn = float('inf'), None
    for nid, node in net.nodes.items():
        d = (node.x - ox) ** 2 + (node.y - oy) ** 2
        if d < bd:
            bd = d
            bn = nid
    return bn


def _estimate_source_head(net) -> float:
    """估算水源总水头（高程 + 水头），取最大值"""
    best = 30.0
    for nid, node in net.nodes.items():
        if hasattr(node, "source_type"):
            elev = getattr(node, "elevation", 0.0) or 0.0
            head = getattr(node, "head", 30.0) or 30.0
            best = max(best, elev + head)
    return best


def _apply_roughness(iface, net, new_roughness, old_vals, c_limits) -> Tuple[int, list]:
    """应用粗糙度到 GPKG + 同类型差异约束。

    Returns:
        (adjusted_count, details)
    """
    # 同类型差异约束
    pipe_types: Dict[str, List[str]] = {}
    for lid in new_roughness:
        link = net.get_link(lid)
        if link is None:
            continue
        pt = getattr(link, "pipe_type", "mainline")
        pipe_types.setdefault(pt, []).append(lid)
    for pt, lids in pipe_types.items():
        if len(lids) < 2:
            continue
        cs = [new_roughness[l] for l in lids]
        avg = sum(cs) / len(cs)
        for lid in lids:
            c = new_roughness[lid]
            if abs(c - avg) > 20:
                new_roughness[lid] = avg + (20 if c > avg else -20)

    from qgis.core import QgsProject
    from .layer_utils import find_layer
    pipe_layer = find_layer(QgsProject.instance(), "aqd_pipes")
    if pipe_layer is None:
        return 0, []

    fid_map = {f.id(): f for f in pipe_layer.getFeatures()}
    details = []
    need_edit = not pipe_layer.isEditable()
    if need_edit:
        pipe_layer.startEditing()
    try:
        for lid, nc in new_roughness.items():
            if not lid.startswith("L"):
                continue
            try:
                fid = int(lid[1:])
            except ValueError:
                continue
            feat = fid_map.get(fid)
            if feat is None:
                continue
            oc = old_vals.get(lid, 130.0)
            feat.setAttribute("roughness", float(nc))
            pipe_layer.updateFeature(feat)
            pt = str(feat.attribute("pipe_type") or "mainline")
            details.append((lid, pt, oc, nc, nc - oc))
    except Exception:
        if need_edit:
            pipe_layer.rollBack()
        raise
    else:
        if need_edit and not pipe_layer.commitChanges():
            pipe_layer.rollBack()
    pipe_layer.triggerRepaint()
    return len(details), details


@register_algorithm
class TopologyOrderedCalibrator(CalibrationAlgorithm):
    """拓扑顺序校准

    将观测点的上游管道按"影响范围"分层：
      Layer 0: 影响所有观测点的管道（共同上游，如干管）
      Layer 1..k: 影响部分观测点的管道（分支共享）
      Layer k+1..: 只影响单一观测点的管道（各分支独有）

    共同管道用所有相关观测点的误差联合校准；
    独有管道仅用该观测点的误差校准。
    避免上下游误差互相干扰。
    """

    name = "topology_ordered"
    label = "拓扑顺序校准"
    description = "按拓扑层级分层校准：先共同上游，再逐层独立"

    def __init__(self, iface, params: dict = None):
        super().__init__(iface, params)
        self.learning_rate = params.get("learning_rate", 0.30) if params else 0.30
        self.c_limits = params.get("c_limits", DEFAULT_C_LIMITS) if params else dict(DEFAULT_C_LIMITS)

    def calibrate(self, obs_data: dict) -> dict:
        from .sync_manager import SyncManager
        sync = SyncManager(self.iface)
        self.net = sync.sync_qgis_to_network(expand=False, split_vertices=False)
        if not self.net.links:
            return {"rmse": 0, "details": []}

        # 1. 构建拓扑 + 上游追踪
        graph = _build_downstream_graph(self.net)
        sources = [nid for nid, n in self.net.nodes.items()
                   if hasattr(n, "source_type")]
        if not sources:
            return {"rmse": 0, "details": []}
        node_upstream = _bfs_upstream_pipes(graph, sources)

        # 2. 每个观测点 → 最近节点 → 上游管道集
        obs_upstream: Dict[str, Set[str]] = {}   # {obs_label: upstream_pipe_ids}
        obs_node: Dict[str, str] = {}             # {obs_label: nearest_node_id}
        for obs_label, (ox, oy, ps, po, qs, qo) in obs_data.items():
            nid = _nearest_node(self.net, ox, oy)
            if nid is None:
                continue
            obs_node[obs_label] = nid
            obs_upstream[obs_label] = node_upstream.get(nid, set()).copy()

        if not obs_upstream:
            return {"rmse": 0, "details": []}

        # 3. 分层：按"影响的观测点集合"分组管道
        pipe_obs: Dict[str, Set[str]] = {}  # {pipe_id: {obs_labels}}
        for obs_label, pipes in obs_upstream.items():
            for lid in pipes:
                pipe_obs.setdefault(lid, set()).add(obs_label)

        # 按 obs 集合大小降序排列（共同管道在前）
        layers: List[Tuple[FrozenSet[str], List[str]]] = []
        group: Dict[FrozenSet[str], List[str]] = {}
        for lid, obs_set in pipe_obs.items():
            key = frozenset(obs_set)
            group.setdefault(key, []).append(lid)
        layers = sorted(group.items(), key=lambda x: -len(x[0]))

        # 4. 逐层校准
        src_head = _estimate_source_head(self.net)
        new_roughness: Dict[str, float] = {}
        old_vals: Dict[str, float] = {}

        for obs_set, pipe_ids in layers:
            self._calibrate_layer(
                obs_set, pipe_ids, obs_data, obs_node,
                src_head, new_roughness, old_vals)

        # 5. 应用约束 + 写回 GPKG
        adjusted, details = _apply_roughness(
            self.iface, self.net, new_roughness, old_vals, self.c_limits)

        # 6. RMSE
        errors = []
        for obs_label, (ox, oy, ps, po, qs, qo) in obs_data.items():
            if ps is not None and po is not None:
                errors.append(ps - po)
        rmse = (sum(e * e for e in errors) / max(len(errors), 1)) ** 0.5 \
            if errors else 0

        return {"rmse": rmse, "details": details, "adjusted": adjusted}

    def _calibrate_layer(self, obs_set: FrozenSet[str], pipe_ids: List[str],
                         obs_data: dict, obs_node: dict,
                         src_head: float,
                         new_roughness: dict, old_vals: dict):
        """校准一层管道（共享同一组观测点的管道）"""
        for lid in pipe_ids:
            link = self.net.get_link(lid)
            if link is None:
                continue
            cc = getattr(link, "roughness", 130.0)
            old_vals[lid] = cc

            td, tw = 0.0, 0.0
            for obs_label in obs_set:
                ox, oy, ps, po, qs, qo = obs_data.get(
                    obs_label, (None, None, None, None, None, None))

                # 压力误差 → C 值调整
                if ps is not None and po is not None and po > 0:
                    dp_abs = ps - po
                    nid = obs_node.get(obs_label)
                    node_elev = 0.0
                    if nid:
                        node = self.net.nodes.get(nid)
                        if node:
                            node_elev = getattr(node, "elevation", 0.0) or 0.0
                    obs_total_head = node_elev + po
                    est_hf = max(1.0, src_head - obs_total_head)
                    dC_phys = -cc * dp_abs / (1.852 * est_hf)
                    td += self.learning_rate * dC_phys
                    tw += 1.0

                # 流量误差 → C 值调整
                if qs is not None and qo is not None and qo > 0:
                    dq_rel = (qo - qs) / qo
                    td += self.learning_rate * dq_rel * 20.0 * (cc / 130.0)
                    tw += 1.0

            if tw == 0:
                continue
            delta = max(-25, min(25, td / tw))
            pt = getattr(link, "pipe_type", "mainline")
            cmin, cmax = self.c_limits.get(pt, (80, 150))
            nc = max(cmin, min(cmax, cc + delta))
            new_roughness[lid] = nc

    def _find_layer(self, key: str):
        from qgis.core import QgsProject
        from .layer_utils import find_layer
        return find_layer(QgsProject.instance(), key)


@register_algorithm
class HazenWilliamsCalibrator(CalibrationAlgorithm):
    """Hazen-Williams 粗糙系数校准

    基于压力和流量误差，按上游管道拓扑权重调整 C 值。
    约束：C ∈ [type_min, type_max]，同类型管道间差异 ≤ 20。
    """

    name = "hazen_williams"
    label = "Hazen-Williams 粗糙系数调整"
    description = "基于压力/流量误差，按上游管道拓扑权重调整 C 值"

    DEFAULT_C_LIMITS = {
        "mainline": (100, 150),
        "submain": (90, 140),
        "lateral": (80, 130),
    }

    def __init__(self, iface, params: dict = None):
        super().__init__(iface, params)
        self.learning_rate = params.get("learning_rate", 0.30) if params else 0.30
        self.c_limits = params.get("c_limits", self.DEFAULT_C_LIMITS) if params else self.DEFAULT_C_LIMITS
        self._upstream_map: Dict[str, List] = {}
        self._new_roughness: Dict[str, float] = {}

    def calibrate(self, obs_data: dict) -> dict:
        from .sync_manager import SyncManager
        sync = SyncManager(self.iface)
        self.net = sync.sync_qgis_to_network(expand=False, split_vertices=False)
        if not self.net.links:
            return {"rmse": 0, "details": []}

        self._build_upstream_graph(obs_data)
        self._compute_adjustments()
        adjusted, details = self._apply_roughness()

        errors = []
        for entries in self._upstream_map.values():
            for _, (ps, po), (_, _) in entries:
                if ps is not None and po is not None:
                    errors.append(ps - po)
        rmse = (sum(e*e for e in errors)/max(len(errors),1)) ** 0.5 if errors else 0

        return {"rmse": rmse, "details": details, "adjusted": adjusted}

    # ── 上游图 + 调整 ──

    def _build_upstream_graph(self, obs_data: dict):
        graph: Dict[str, List] = {nid: [] for nid in self.net.nodes}
        for lid, link in self.net.links.items():
            fn, tn = link.from_node, link.to_node
            graph.setdefault(fn, []).append((lid, link, tn))

        sources = [nid for nid, n in self.net.nodes.items() if hasattr(n, "source_type")]
        node_upstream: Dict[str, Set[str]] = {}
        for src in sources:
            queue = deque([(src, set())])
            visited = set()
            while queue:
                node, us = queue.popleft()
                if node in visited: continue
                visited.add(node)
                node_upstream[node] = us
                for lid, link, nx in graph.get(node, []):
                    queue.append((nx, us | {lid}))

        self._upstream_map = {}
        self._obs_node_map: Dict[str, str] = {}
        for obs_label, (ox, oy, ps, po, qs, qo) in obs_data.items():
            near_nid = _nearest_node(self.net, ox, oy)
            if near_nid is None: continue
            self._obs_node_map[obs_label] = near_nid
            for lid in node_upstream.get(near_nid, set()):
                link = self.net.get_link(lid)
                if link is None or not hasattr(link, "pipe_type"): continue
                self._upstream_map.setdefault(lid, []).append(
                    (obs_label, (ps, po), (qs, qo)))

    def _compute_adjustments(self):
        src_head = _estimate_source_head(self.net)

        self._new_roughness = {}
        for lid, entries in self._upstream_map.items():
            link = self.net.get_link(lid)
            if link is None: continue
            cc = getattr(link, "roughness", 130.0)

            td, tw = 0.0, 0.0
            for obs_label, (ps, po), (qs, qo) in entries:
                if ps is not None and po is not None and po > 0:
                    dp_abs = ps - po
                    nid = self._obs_node_map.get(obs_label)
                    node_elev = 0.0
                    if nid:
                        node = self.net.nodes.get(nid)
                        if node:
                            node_elev = getattr(node, "elevation", 0.0) or 0.0
                    obs_total_head = node_elev + po
                    est_hf = max(1.0, src_head - obs_total_head)
                    dC_phys = -cc * dp_abs / (1.852 * est_hf)
                    td += self.learning_rate * dC_phys
                    tw += 1.0
                if qs is not None and qo is not None and qo > 0:
                    dq_rel = (qo - qs) / qo
                    td += self.learning_rate * dq_rel * 20.0 * (cc / 130.0)
                    tw += 1.0
            if tw == 0: continue
            delta = max(-25, min(25, td / tw))
            pt = getattr(link, "pipe_type", "mainline")
            cmin, cmax = self.c_limits.get(pt, (80, 150))
            nc = max(cmin, min(cmax, cc + delta))
            self._new_roughness[lid] = nc

    def _apply_roughness(self) -> Tuple[int, list]:
        old_vals = {lid: getattr(self.net.get_link(lid), "roughness", 130.0)
                    for lid in self._new_roughness if self.net.get_link(lid)}
        return _apply_roughness(
            self.iface, self.net, self._new_roughness, old_vals, self.c_limits)
