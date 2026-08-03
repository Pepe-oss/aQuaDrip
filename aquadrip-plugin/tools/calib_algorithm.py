"""校准算法接口 + Hazen-Williams 实现

算法通过 CalibrationAlgorithm 基类注册，calibration_dialog 自动发现。
"""

from abc import ABC, abstractmethod
from collections import deque
from typing import Dict, List, Optional, Set, Tuple


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
            if hasattr(link, "valve_type") or hasattr(link, "pump_type"):
                graph.setdefault(fn, []).append((lid, link, tn))
            else:
                graph.setdefault(fn, []).append((lid, link, tn))
                graph.setdefault(tn, []).append((lid, link, fn))

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
        self._obs_node_map: Dict[str, str] = {}  # obs_label -> nearest node id
        for obs_label, (ox, oy, ps, po, qs, qo) in obs_data.items():
            near_nid = self._nearest_node(ox, oy)
            if near_nid is None: continue
            self._obs_node_map[obs_label] = near_nid
            for lid in node_upstream.get(near_nid, set()):
                link = self.net.get_link(lid)
                if link is None or not hasattr(link, "pipe_type"): continue
                self._upstream_map.setdefault(lid, []).append(
                    (obs_label, (ps, po), (qs, qo)))

    def _nearest_node(self, ox, oy) -> Optional[str]:
        bd, bn = float('inf'), None
        for nid, node in self.net.nodes.items():
            d = (node.x-ox)**2 + (node.y-oy)**2
            if d < bd: bd = d; bn = nid
        return bn

    def _compute_adjustments(self):
        # 估算源节点总水头（高程 + 水源水头）
        src_head = self._estimate_source_head()

        self._new_roughness = {}
        for lid, entries in self._upstream_map.items():
            link = self.net.get_link(lid)
            if link is None: continue
            cc = getattr(link, "roughness", 130.0)

            td, tw = 0.0, 0.0
            for obs_label, (ps, po), (qs, qo) in entries:
                if ps is not None and po is not None and po > 0:
                    dp_abs = ps - po  # 绝对压力误差 (m)
                    # 估算沿程水头损失：源节点总水头 - 观测点压力
                    nid = self._obs_node_map.get(obs_label)
                    node_elev = 0.0
                    if nid:
                        node = self.net.nodes.get(nid)
                        if node:
                            node_elev = getattr(node, "elevation", 0.0) or 0.0
                    # 观测点处总水头 ≈ 节点高程 + 模拟压力
                    obs_total_head = node_elev + ps
                    est_hf = max(1.0, src_head - obs_total_head)
                    # Hazen-Williams 物理公式: dC = -C * dp / (1.852 * h_f)
                    dC_phys = -cc * dp_abs / (1.852 * est_hf)
                    td += self.learning_rate * dC_phys
                    tw += 1.0
                if qs is not None and qo is not None and qo > 0:
                    dq_rel = (qs - qo) / qo
                    td += self.learning_rate * dq_rel * 20.0 * (cc / 130.0)
                    tw += 1.0
            if tw == 0: continue
            delta = max(-25, min(25, td / tw))
            pt = getattr(link, "pipe_type", "mainline")
            cmin, cmax = self.c_limits.get(pt, (80, 150))
            nc = max(cmin, min(cmax, cc + delta))
            self._new_roughness[lid] = nc

    def _estimate_source_head(self) -> float:
        """估算水源节点的总水头（高程 + 水源水头），取最大值"""
        best = 30.0  # 默认 30m
        for nid, node in self.net.nodes.items():
            if hasattr(node, "source_type"):
                elev = getattr(node, "elevation", 0.0) or 0.0
                head = getattr(node, "source_head", 30.0) or 30.0
                best = max(best, elev + head)
        return best

    def _apply_roughness(self) -> Tuple[int, list]:
        old_vals = {}
        for lid in self._new_roughness:
            link = self.net.get_link(lid)
            if link: old_vals[lid] = getattr(link, "roughness", 130.0)

        # 同类型差异约束
        pipe_types: Dict[str, List[str]] = {}
        for lid in self._new_roughness:
            link = self.net.get_link(lid)
            if link is None: continue
            pt = getattr(link, "pipe_type", "mainline")
            pipe_types.setdefault(pt, []).append(lid)
        for pt, lids in pipe_types.items():
            if len(lids) < 2: continue
            cs = [self._new_roughness[l] for l in lids]
            avg = sum(cs)/len(cs)
            for lid in lids:
                c = self._new_roughness[lid]
                if abs(c-avg) > 20:
                    self._new_roughness[lid] = avg + (20 if c>avg else -20)

        pipe_layer = self._find_layer("aqd_pipes")
        if pipe_layer is None: return 0, []
        fid_map = {f.id(): f for f in pipe_layer.getFeatures()}

        details = []
        need_edit = not pipe_layer.isEditable()
        if need_edit: pipe_layer.startEditing()
        try:
            for lid, nc in self._new_roughness.items():
                if not lid.startswith("L"): continue
                try: fid = int(lid[1:])
                except ValueError: continue
                feat = fid_map.get(fid)
                if feat is None: continue
                oc = old_vals.get(lid, 130.0)
                feat.setAttribute("roughness", float(nc))
                pipe_layer.updateFeature(feat)
                pt = str(feat.attribute("pipe_type") or "mainline")
                details.append((lid, pt, oc, nc, nc-oc))
            if need_edit: pipe_layer.commitChanges()
        except Exception:
            if need_edit: pipe_layer.rollBack()
            raise
        pipe_layer.triggerRepaint()
        return len(details), details

    def _find_layer(self, key: str):
        from qgis.core import QgsProject, QgsVectorLayer
        for _lid, layer in QgsProject.instance().mapLayers().items():
            if not isinstance(layer, QgsVectorLayer): continue
            src = layer.source() if hasattr(layer, "source") else ""
            if key in src or layer.name() == key: return layer
        return None
