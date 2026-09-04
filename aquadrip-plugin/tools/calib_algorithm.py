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


def match_radius(x: float, y: float, geographic: bool = None) -> float:
    """观测点↔管网匹配半径上限(超出视为观测点放错位置,跳过)。

    投影坐标系 5m;经纬度坐标约 5e-5°(≈5m)。

    Args:
        geographic: 调用方已知的 CRS 类型(图层 crs().isGeographic())。
            None 时用启发式:|x|≤180 且 |y|≤90 视为经纬度——注意
            局部米制坐标系(小数值)会被误判,调用方应尽量传真值。
    """
    if geographic is None:
        geographic = abs(x) <= 180.0 and abs(y) <= 90.0
    return 5e-5 if geographic else 5.0


def nearest_sim_pressure(ox: float, oy: float,
                         node_pressure: dict, node_coords: dict,
                         geographic: bool = None
                         ) -> Tuple[Optional[float], float]:
    """观测点 → 最近节点的模拟压力(带匹配半径上限)。

    Returns:
        (压力或 None, 实际距离)——距离超过 match_radius 时返回 (None, dist)
    """
    r = match_radius(ox, oy, geographic)
    bd, bp = float("inf"), None
    for nid, p in node_pressure.items():
        c = node_coords.get(nid)
        if c is None or len(c) < 2:
            continue
        d = ((ox - c[0]) ** 2 + (oy - c[1]) ** 2) ** 0.5
        if d < bd:
            bd = d
            bp = float(p) if isinstance(p, (int, float)) else None
    if bd > r:
        return None, bd
    return bp, bd


def nearest_sim_flow(ox: float, oy: float, otype: str,
                     link_geometry: dict, link_flow: dict,
                     emitter_flow: dict, node_coords: dict,
                     geographic: bool = None
                     ) -> Tuple[Optional[float], float]:
    """观测点 → 类型感知的模拟流量(带匹配半径上限)。

    - emitter 型:匹配最近**滴头**的出流量(emitter_flow,E_* 节点)。
      观测实测流量是单滴头出流(L/h),与整管流量量级完全不同,
      按管段匹配会产生巨大的虚假相对误差、把 C 拉向错误方向。
    - 其他类型(junction/source):匹配最近管段流量(整管流量,
      与实测语义一致)。

    Returns:
        (流量 L/h 或 None, 实际距离)——超匹配半径返回 (None, dist)
    """
    r = match_radius(ox, oy, geographic)
    if otype == "emitter" and emitter_flow and node_coords:
        bd, bq = float("inf"), None
        for eid, q in emitter_flow.items():
            c = node_coords.get(eid)
            if c is None or len(c) < 2:
                continue
            d = ((ox - c[0]) ** 2 + (oy - c[1]) ** 2) ** 0.5
            if d < bd:
                bd = d
                bq = abs(float(q)) if isinstance(q, (int, float)) else None
        if bd > r:
            return None, bd
        return bq, bd

    bd, bq = float("inf"), None
    for lid, pts in link_geometry.items():
        if not pts or len(pts) < 2:
            continue
        for i in range(len(pts) - 1):
            ax, ay = pts[i][0], pts[i][1]
            bx, by = pts[i + 1][0], pts[i + 1][1]
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            t = max(0, min(1, ((ox - ax) * dx + (oy - ay) * dy) / l2)) \
                if l2 > 1e-20 else 0.5
            px, py = ax + t * dx, ay + t * dy
            d = ((ox - px) ** 2 + (oy - py) ** 2) ** 0.5
            if d < bd:
                bd = d
                f = link_flow.get(lid)
                bq = abs(float(f)) if isinstance(f, (int, float)) else None
    if bd > r:
        return None, bd
    return bq, bd


def _build_downstream_graph(net) -> Dict[str, List[Tuple]]:
    """构建有向下游图（仅 from→to 方向）。

    调用前需先 _fix_link_directions_in_memory 确保方向正确。
    """
    graph: Dict[str, List] = {nid: [] for nid in net.nodes}
    for lid, link in net.links.items():
        fn, tn = link.from_node, link.to_node
        graph.setdefault(fn, []).append((lid, link, tn))
    return graph


def _bfs_upstream_pipes(graph, sources) -> Dict[str, Set[str]]:
    """计算每个节点的上游管道集合（反向传播至不动点）。

    原 BFS 实现中,同一 BFS 内多条路径到达同一节点会被 visited
    拦截,节点处的 `|=` 合并是死代码——环状/汇流管网的上游集合
    不完整。改为沿 from→to 反向迭代传播,集合单调增长必然收敛。
    """
    reverse: Dict[str, List[Tuple[str, str]]] = {}
    for fn, edges in graph.items():
        for lid, _link, tn in edges:
            reverse.setdefault(tn, []).append((lid, fn))

    node_upstream: Dict[str, Set[str]] = {s: set() for s in sources}
    changed = True
    while changed:
        changed = False
        for tn, edges in reverse.items():
            acc = node_upstream.get(tn)
            if acc is None:
                acc = set()
            for lid, fn in edges:
                up_fn = node_upstream.get(fn)
                if up_fn is None:
                    continue  # fn 尚不可达任何水源
                merged = up_fn | {lid}
                if not merged <= acc:
                    acc = acc | merged
                    changed = True
            if acc:
                node_upstream[tn] = acc
    return node_upstream


def _nearest_node(net, ox, oy) -> Optional[str]:
    """找距离 (ox, oy) 最近的节点(带匹配半径上限,超出返回 None)"""
    bd, bn = float('inf'), None
    for nid, node in net.nodes.items():
        d = (node.x - ox) ** 2 + (node.y - oy) ** 2
        if d < bd:
            bd = d
            bn = nid
    if bn is not None and bd > match_radius(ox, oy):
        return None  # 观测点放错位置,不参与校准
    return bn


def _fix_link_directions_in_memory(net) -> int:
    """在内存 DripNetwork 上修正 link 方向（from_node 朝向水源侧）。

    TopologyBuilder 按几何顶点顺序（pts[0]→pts[-1]）确定方向，
    用户画反顶点序的管道在内存网络中 from→to 是逆向的。
    DirectionFixer 只改 GPKG 属性，不影响内存网络。

    用 BFS 距源跳数判断：from_node 跳数应 ≤ to_node 跳数。

    Returns:
        修正的 link 数量
    """
    # 构建无向邻接表
    adj: Dict[str, List[Tuple[str, str]]] = {}
    for lid, link in net.links.items():
        adj.setdefault(link.from_node, []).append((lid, link.to_node))
        adj.setdefault(link.to_node, []).append((lid, link.from_node))

    # BFS 从水源计算距源跳数
    sources = [nid for nid, n in net.nodes.items()
               if hasattr(n, "source_type")]
    dist: Dict[str, int] = {}
    queue = deque(sources)
    for src in sources:
        dist[src] = 0
    while queue:
        node = queue.popleft()
        for _lid, neighbor in adj.get(node, []):
            if neighbor not in dist:
                dist[neighbor] = dist[node] + 1
                queue.append(neighbor)

    # 修正方向：from_node 跳数 > to_node 跳数 → 交换
    fixed = 0
    for lid, link in net.links.items():
        df = dist.get(link.from_node)
        dt = dist.get(link.to_node)
        if df is not None and dt is not None and df > dt:
            link.from_node, link.to_node = link.to_node, link.from_node
            fixed += 1
    return fixed


def _estimate_source_head(net) -> float:
    """估算水源总水头（高程 + 水头），取最大值"""
    best = 30.0
    for nid, node in net.nodes.items():
        if hasattr(node, "source_type"):
            elev = getattr(node, "elevation", 0.0) or 0.0
            head = getattr(node, "head", 30.0) or 30.0
            best = max(best, elev + head)
    return best


def _hw_headloss(length_m: float, flow_lph: float, c: float,
                 diameter_mm: float) -> float:
    """Hazen-Williams 单管水头损失 (m)

    hf = 10.67 * L * Q^1.852 / (C^1.852 * D^4.87)
    Q 单位 m³/s，D 单位 m。

    Args:
        length_m: 管长 (m)
        flow_lph: 流量 (L/h)，0 时返回 0
        c: H-W 粗糙系数
        diameter_mm: 管径 (mm)
    """
    if length_m <= 0 or flow_lph <= 0 or diameter_mm <= 0 or c <= 0:
        return 0.0
    q_cms = flow_lph / 3.6e6  # L/h → m³/s
    d_m = diameter_mm / 1000.0  # mm → m
    return 10.67 * length_m * (q_cms ** 1.852) / \
        ((c ** 1.852) * (d_m ** 4.87))


def _aggregate_segment_flow(link_flow: Dict[str, float]) -> Dict[str, float]:
    """把切段流量聚合回基础管道 ID(纯函数,便于单测)。

    模拟历史来自展开/切断后的网络,link ID 形如 L4_seg003(毛管
    展开段)或 L3_p2(交叉切断段);校准内存网(expand=False)只有
    基础 ID L4/L3。串联切段流量沿程递减(中途出流),取各段最大值
    (=入口段流量)即该管道总流量。
    """
    agg: Dict[str, float] = {}
    for lid, v in link_flow.items():
        if not isinstance(v, (int, float)):
            continue
        base = lid.split("_p")[0].split("_seg")[0]
        q = abs(float(v))
        if q > agg.get(base, 0.0):
            agg[base] = q
    return agg


def _load_link_flow() -> Dict[str, float]:
    """从 sim_history 读取最新记录的 link_flow(L/h),聚合切段到基础 ID。

    注意单位:SimHistory.add 保存时已做 m³/s × 3.6e6 = L/h 换算,
    JSON 中即 L/h——此处不得再次换算(原先再乘 3.6e6 导致 hf 虚高
    ~10¹² 倍,hf² 加权的压力校准项实际失效)。
    """
    from .layer_utils import find_gpkg_path
    gpkg_path = find_gpkg_path(None, "aqd_fields")
    if not gpkg_path:
        return {}
    try:
        from .sim_history import SimHistory
        records = SimHistory(gpkg_path).load()
        if not records:
            return {}
        lf = records[0].get("link_flow", {})
        return _aggregate_segment_flow(lf)
    except Exception:
        return {}


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

    # 差异约束(avg±20)可能把值推出物理限值,按类型统一再 clamp 一次
    for lid in new_roughness:
        link = net.get_link(lid)
        pt = getattr(link, "pipe_type", "mainline") if link else "mainline"
        cmin, cmax = c_limits.get(pt, (80, 150))
        new_roughness[lid] = max(cmin, min(cmax, new_roughness[lid]))

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
        # 内存网中的切段 ID（L3_p2 交叉切断 / L4_seg003 毛管展开）属于
        # 同一条 GPKG 管道：映射回基础 fid 取平均后写回，
        # 而不是 int() 解析失败静默跳过（导致切段校正丢失）
        base_updates: Dict[int, List[float]] = {}
        for lid, nc in new_roughness.items():
            if not lid.startswith("L"):
                continue
            base = lid[1:].split("_p")[0].split("_seg")[0]
            try:
                fid = int(base)
            except ValueError:
                continue
            base_updates.setdefault(fid, []).append(float(nc))

        # old_vals 的键是内存网切段 ID(L25_p1/L4_seg003),同样按
        # 基础 fid 聚合取均值——否则查不到恒显示默认 130,掩盖
        # "上一轮写回已生效"的事实,误导收敛判读
        old_base: Dict[str, List[float]] = {}
        for lid, v in old_vals.items():
            if not lid.startswith("L"):
                continue
            b = lid[1:].split("_p")[0].split("_seg")[0]
            old_base.setdefault(b, []).append(float(v))

        for fid, cs in sorted(base_updates.items()):
            feat = fid_map.get(fid)
            if feat is None:
                continue
            lid = f"L{fid}"
            nc = sum(cs) / len(cs)
            ocs = old_base.get(str(fid), [130.0])
            oc = sum(ocs) / len(ocs)
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

        # 在内存网络上修正方向（TopologyBuilder 按几何顶点序定方向，
        # 顶点序画反的管道 from→to 是逆向的，GPKG 属性修正不影响它）
        _fix_link_directions_in_memory(self.net)

        # 1. 构建拓扑 + 上游追踪
        graph = _build_downstream_graph(self.net)
        sources = [nid for nid, n in self.net.nodes.items()
                   if hasattr(n, "source_type")]
        if not sources:
            return {"rmse": 0, "details": []}
        node_upstream = _bfs_upstream_pipes(graph, sources)

        # 2. 每个观测点 → 最近节点 → 上游管道集(超匹配半径则跳过)
        obs_upstream: Dict[str, Set[str]] = {}   # {obs_label: upstream_pipe_ids}
        obs_node: Dict[str, str] = {}             # {obs_label: nearest_node_id}
        skipped_obs: List[Tuple[str, float]] = []  # [(label, 距离)]
        for obs_label, (ox, oy, ps, po, qs, qo) in obs_data.items():
            nid = _nearest_node(self.net, ox, oy)
            if nid is None:
                dist = min(
                    (((node.x - ox) ** 2 + (node.y - oy) ** 2) ** 0.5)
                    for node in self.net.nodes.values()
                ) if self.net.nodes else float("inf")
                skipped_obs.append((obs_label, dist))
                continue
            obs_node[obs_label] = nid
            obs_upstream[obs_label] = node_upstream.get(nid, set()).copy()

        if not obs_upstream:
            return {"rmse": 0, "details": [], "skipped_obs": skipped_obs}

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

        # 4. 逐层校准（按管道自身水头损失加权）
        src_head = _estimate_source_head(self.net)
        link_flow_lph = _load_link_flow()  # {lid: 流量 L/h}
        new_roughness: Dict[str, float] = {}
        old_vals: Dict[str, float] = {}

        for obs_set, pipe_ids in layers:
            self._calibrate_layer(
                obs_set, pipe_ids, obs_data, obs_node,
                src_head, link_flow_lph, new_roughness, old_vals)
            # 序贯反馈:该层校准结果立即回写内存网,后续层的基线 C
            # 与 hf 灵敏度基于更新后的值——"拓扑顺序"名副其实
            for lid in pipe_ids:
                if lid in new_roughness:
                    link = self.net.get_link(lid)
                    if link is not None:
                        link.roughness = new_roughness[lid]

        # 5. 应用约束 + 写回 GPKG
        adjusted, details = _apply_roughness(
            self.iface, self.net, new_roughness, old_vals, self.c_limits)

        # 6. RMSE + 分类型统计（hf² 权重）
        errors = []
        for obs_label, (ox, oy, ps, po, qs, qo) in obs_data.items():
            if ps is not None and po is not None:
                errors.append(ps - po)
        rmse = (sum(e * e for e in errors) / max(len(errors), 1)) ** 0.5 \
            if errors else 0

        # 分类型统计：各类型管道的调整量和 hf² 权重
        type_stats: Dict[str, dict] = {}
        for lid, (l_type, old_c, new_c, delta) in [
            (d[0], (d[1], d[2], d[3], d[4])) for d in details
        ]:
            if l_type not in type_stats:
                type_stats[l_type] = {
                    "count": 0, "total_delta": 0.0,
                    "total_hf2": 0.0,
                }
            type_stats[l_type]["count"] += 1
            type_stats[l_type]["total_delta"] += delta
            hf_own = _hw_headloss(
                getattr(self.net.get_link(lid), "length", 0) or 0,
                link_flow_lph.get(lid, 0),
                old_c,
                getattr(self.net.get_link(lid), "diameter", 0) or 0)
            type_stats[l_type]["total_hf2"] += hf_own * hf_own

        total_hf2_all = sum(ts["total_hf2"] for ts in type_stats.values())
        for ts in type_stats.values():
            ts["hf2_weight"] = (ts["total_hf2"] / total_hf2_all
                                if total_hf2_all > 0 else 0.0)
            ts["avg_delta"] = (ts["total_delta"] / ts["count"]
                               if ts["count"] > 0 else 0.0)

        return {"rmse": rmse, "details": details, "adjusted": adjusted,
                "type_stats": type_stats, "skipped_obs": skipped_obs}

    def _calibrate_layer(self, obs_set: FrozenSet[str], pipe_ids: List[str],
                         obs_data: dict, obs_node: dict,
                         src_head: float, link_flow_lph: dict,
                         new_roughness: dict, old_vals: dict):
        """校准一层管道（共享同一组观测点的管道）

        按管道自身水头损失占比加权分配调整量：
        - 毛管（hf 大，敏感）→ 分到大部分修正量
        - 干管（hf 小，不敏感）→ 几乎不动
        避免干管 C 值被不必要地改动（其改变对压力几乎无影响）。
        """
        # 1. 计算层内每条管道的自身水头损失
        pipe_hf: Dict[str, float] = {}
        for lid in pipe_ids:
            link = self.net.get_link(lid)
            if link is None:
                continue
            cc = getattr(link, "roughness", 130.0)
            length = getattr(link, "length", 0.0) or 0.0
            diameter = getattr(link, "diameter", 0.0) or 0.0
            flow = link_flow_lph.get(lid, 0.0)
            pipe_hf[lid] = _hw_headloss(length, flow, cc, diameter)

        # hf² 加权：水头损失大的管道（毛管）分到更多调整量，
        # 水头损失小的管道（干管）几乎不动。总修正量精确等于目标。
        total_hf2 = sum(h * h for h in pipe_hf.values())

        # 2. 逐管道按 hf² 占比加权计算调整量
        for lid in pipe_ids:
            link = self.net.get_link(lid)
            if link is None:
                continue
            cc = getattr(link, "roughness", 130.0)
            old_vals[lid] = cc

            # 无流量数据时压力项退化为均匀 est_hf 反演(见下)
            hf_own = pipe_hf.get(lid, 0.0)
            if total_hf2 > 0:
                # dC ∝ hf_own：毛管（hf大）重点校准，干管（hf小）几乎不动
                hf_factor = hf_own / total_hf2
            else:
                hf_factor = 0.0

            td, tw = 0.0, 0.0
            for obs_label in obs_set:
                ox, oy, ps, po, qs, qo = obs_data.get(
                    obs_label, (None, None, None, None, None, None))

                # 压力误差 → C 值调整（hf² 加权）
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
                    if total_hf2 > 0:
                        # dC = -C * dp * hf_own / (1.852 * Σ hf²)
                        dC_phys = -cc * dp_abs * hf_factor / 1.852
                    else:
                        # 无流量数据:退化为按估算总水头均匀反演
                        dC_phys = -cc * dp_abs / (1.852 * est_hf)
                    td += self.learning_rate * dC_phys
                    tw += 1.0

                # 流量误差 → C 值调整（同样按 hf 占比加权）
                if qs is not None and qo is not None and qo > 0:
                    dq_rel = (qo - qs) / qo
                    # 用 hf 归一化权重（0~1）
                    w_norm = hf_own * hf_factor if total_hf2 > 0 else 1.0 / len(pipe_ids)
                    td += self.learning_rate * dq_rel * 20.0 * (cc / 130.0) * w_norm
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

        # 在内存网络上修正方向（同拓扑顺序校准）
        _fix_link_directions_in_memory(self.net)

        self._build_upstream_graph(obs_data)
        self._compute_adjustments()
        adjusted, details = self._apply_roughness()

        errors = []
        for entries in self._upstream_map.values():
            for _, (ps, po), (_, _) in entries:
                if ps is not None and po is not None:
                    errors.append(ps - po)
        rmse = (sum(e*e for e in errors)/max(len(errors),1)) ** 0.5 if errors else 0

        return {"rmse": rmse, "details": details, "adjusted": adjusted,
                "skipped_obs": getattr(self, "_skipped_obs", [])}

    # ── 上游图 + 调整 ──

    def _build_upstream_graph(self, obs_data: dict):
        graph = _build_downstream_graph(self.net)
        sources = [nid for nid, n in self.net.nodes.items() if hasattr(n, "source_type")]
        node_upstream = _bfs_upstream_pipes(graph, sources)

        self._upstream_map = {}
        self._obs_node_map: Dict[str, str] = {}
        self._skipped_obs: List[Tuple[str, float]] = []
        for obs_label, (ox, oy, ps, po, qs, qo) in obs_data.items():
            near_nid = _nearest_node(self.net, ox, oy)
            if near_nid is None:
                dist = min(
                    (((n.x - ox) ** 2 + (n.y - oy) ** 2) ** 0.5)
                    for n in self.net.nodes.values()
                ) if self.net.nodes else float("inf")
                self._skipped_obs.append((obs_label, dist))
                continue
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
