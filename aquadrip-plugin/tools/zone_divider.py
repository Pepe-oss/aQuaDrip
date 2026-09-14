"""ZoneDivider — 管网分区划分（支持嵌套层级 / 多阀合并 / 按流量编组）

算法:
  1. 从 SyncManager 构建 DripNetwork
  2. 构建有向邻接表（Pipe 双向，Valve/Pump 单向 from→to）
  3. 从水源节点 BFS，遇到 Valve 时递归划分子区
  4. 层级编号 "1", "1-1", "1-2", "2" ...
  5. 写回 aqd_pipes/aqd_pumps/aqd_valves.zone 字段

三种分区模式:
  divide()                 单阀细分——每个阀门一个分区（粒度最细的底图）
  merge_selected_valves()  手动合并——选中若干阀门并为同一分区
                           （现实中一个管理分区常由多个阀门同时控制）
  auto_group_by_flow()     按流量自动编组——沿干管顺序贪心装箱，
                           每组阀门需求流量之和 ≤ 目标组流量
                           （水源流量大于单阀区需求时，多阀同开凑满流量）

轮灌调度器按 zone 字符串分组同开：同标签的多阀即一个轮灌组，无需改动。
"""

from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtWidgets import QApplication


class ZoneDivider:
    """层级分区划分器"""

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()

    # ── 网络与图构建（三种模式共用） ──

    def _build_graph(self):
        """矫正方向 → 构建 DripNetwork + 邻接图

        Returns:
            (net, graph, all_valves, sources) 或 (None, None, [], [])
        """
        # 0. 自动矫正阀门/水泵方向（确保 from_node 指向远离水源的一侧）
        from .direction_fixer import DirectionFixer
        DirectionFixer(self.iface).fix()

        from .sync_manager import SyncManager
        sync = SyncManager(self.iface)
        net = sync.sync_qgis_to_network(expand=False, split_vertices=False)
        if not net.links:
            return None, None, [], []

        graph: Dict[str, List[Tuple[object, str]]] = {}
        all_valves = []
        sources = []

        for nid in net.nodes:
            graph[nid] = []

        for lid, link in net.links.items():
            fn, tn = link.from_node, link.to_node
            has_pump = hasattr(link, "pump_type")
            has_valve = hasattr(link, "valve_type")

            if has_valve:
                all_valves.append(link)
                # 阀门：BFS 双向可达（用户绘制方向可能与水流方向相反），
                # 但分区时仍以阀门为边界创建子分区
                graph.setdefault(fn, []).append((link, tn))
                graph.setdefault(tn, []).append((link, fn))
            elif has_pump:
                # 水泵：单向 from→to
                graph.setdefault(fn, []).append((link, tn))
            else:
                # 普通管道：双向
                graph.setdefault(fn, []).append((link, tn))
                graph.setdefault(tn, []).append((link, fn))

        for nid, node in net.nodes.items():
            if hasattr(node, "source_type"):
                sources.append(nid)

        return net, graph, all_valves, sources

    def divide(self) -> dict:
        """主入口（单阀细分）：矫正方向 → 划分分区 → 写回图层

        Returns:
            {"valves": int, "zones": int, "pipes": int}
        """
        # 1. 构建网络与图
        net, graph, all_valves, sources = self._build_graph()
        if net is None or not net.links:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("ZoneDivider", "管网中没有管道"))
            return {"valves": 0, "zones": 0, "pipes": 0}
        if not sources:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("ZoneDivider", "管网中没有水源节点"))
            return {"valves": len(all_valves), "zones": 0, "pipes": 0}

        # 2. 层级 BFS 分区
        zone_map: Dict[str, str] = {}  # {link_id: zone_label}
        valve_counter: Dict[int, int] = {}  # {level: next_number}

        global_visited: Set[str] = set()
        for src in sources:
            self._traverse(src, graph, all_valves, zone_map,
                           valve_counter, "", global_visited,
                           sources=set(sources))

        # 3. 写回图层
        if not zone_map:
            self.iface.messageBar().pushMessage(
                "aQuaDrip", QApplication.translate("ZoneDivider", "未检测到阀门，全部管道为公共区"), level=0, duration=4)
            return {"valves": len(all_valves), "zones": 0, "pipes": len(zone_map)}

        written = self._write_zones(zone_map)
        zones = len(set(v for v in zone_map.values() if v))

        self.iface.messageBar().pushMessage(
            "aQuaDrip",
            QApplication.translate("ZoneDivider", "分区完成: {0} 个阀门 → {1} 个分区, {2} 条管道已标记").format(len(all_valves), zones, written),
            level=0, duration=6)

        # 4. 对 aqd_pipes 应用分类着色
        self._apply_zone_renderer()

        return {"valves": len(all_valves), "zones": zones, "pipes": written}

    # ── 多阀合并（模式 A）──

    def merge_selected_valves(self) -> dict:
        """把地图上选中的多个阀门合并为同一分区

        现实中一个管理分区常由多个阀门同时控制（水源流量大于单阀区
        需求、或一个管理单元跨多条支管）。轮灌调度器按 zone 字符串
        分组同开——同标签即同组，本方法只需统一标签。

        Returns:
            {"valves": 合并阀门数, "zone": 新分区标签, "pipes": 重标管道数}
            失败时 valves=0
        """
        valve_layer = self._find_layer("aqd_valves")
        if valve_layer is None:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("ZoneDivider", "未找到 aqd_valves 图层"))
            return {"valves": 0, "zone": "", "pipes": 0}
        selected = list(valve_layer.selectedFeatures())
        if len(selected) < 2:
            self.iface.messageBar().pushWarning(
                "aQuaDrip",
                QApplication.translate("ZoneDivider",
                                       "请先在地图上选中至少 2 个阀门再合并（当前 {0} 个）").format(len(selected)))
            return {"valves": 0, "zone": "", "pipes": 0}

        net, graph, all_valves, sources = self._build_graph()
        if net is None or not sources:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("ZoneDivider", "管网构建失败或无水源"))
            return {"valves": 0, "zone": "", "pipes": 0}

        merged_ids = {f"V{f.id()}" for f in selected}
        # 各选中阀门下游子树（到未选中的阀门为止，保留其子分区）
        subtree = set()
        for vlid in merged_ids:
            link = net.links.get(vlid)
            if link is None:
                continue
            subtree |= self._valve_subtree(vlid, net, graph, set(sources))
        subtree_base = {self._base_id(lid) for lid in subtree}

        label = self._next_group_label()
        zone_map = {vlid: label for vlid in merged_ids}
        zone_map.update({lid: label for lid in subtree_base})

        written = self._write_zones(zone_map)
        self._apply_zone_renderer()
        self.iface.messageBar().pushMessage(
            "aQuaDrip",
            QApplication.translate("ZoneDivider",
                                   "已将 {0} 个阀门合并为分区 {1}（{2} 条管道重标记，轮灌时同开）").format(
                                       len(merged_ids), label, written),
            level=0, duration=6)
        return {"valves": len(merged_ids), "zone": label, "pipes": written}

    # ── 按流量自动编组（模式 B）──

    def auto_group_by_flow(self, target_flow_lph: float) -> dict:
        """沿干管顺序贪心装箱：每组阀门需求流量之和 ≤ 目标组流量

        需求流量估算优先用最新一次模拟的管段流量聚合（反映真实
        水力状态），无模拟历史时回退几何估算（毛管长度/滴头间距×
        滴头额定流量，按 10 m 工作压力计）。

        Args:
            target_flow_lph: 目标组流量（L/h），通常 = 水源可供流量

        Returns:
            {"groups": [{zone, valves, flow_lph}], "pipes": 重标管道数}
        """
        if target_flow_lph <= 0:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("ZoneDivider", "目标组流量必须大于 0"))
            return {"groups": [], "pipes": 0}

        net, graph, all_valves, sources = self._build_graph()
        if net is None or not sources or not all_valves:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("ZoneDivider", "管网构建失败、无水源或无阀门"))
            return {"groups": [], "pipes": 0}

        # 单阀细分底图 + 阀门发现顺序（BFS 序 = 沿干管的空间顺序）
        zone_map: Dict[str, str] = {}
        valve_counter: Dict[int, int] = {}
        valve_labels: Dict[str, str] = {}  # {valve_lid: 细分标签}（按发现顺序）
        visited: Set[str] = set()
        for src in sources:
            self._traverse(src, graph, all_valves, zone_map,
                           valve_counter, "", visited, valve_labels,
                           sources=set(sources))
        if not valve_labels:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("ZoneDivider", "未发现可编组的阀门"))
            return {"groups": [], "pipes": 0}

        # 每个阀门细分区的需求流量
        flows = self._estimate_valve_flows(zone_map, valve_labels, net)
        total = sum(flows.values())

        # 贪心装箱（发现顺序 = 空间相邻优先）
        bins: List[List[str]] = []
        cur, cur_q = [], 0.0
        for vlid in valve_labels:
            q = flows.get(vlid, 0.0)
            if cur and cur_q + q > target_flow_lph:
                bins.append(cur)
                cur, cur_q = [], 0.0
            cur.append(vlid)
            cur_q += q
        if cur:
            bins.append(cur)

        # 写组标签 G1..（含各阀门子树管道）
        zone_map_out: Dict[str, str] = {}
        groups = []
        for i, bin_ in enumerate(bins, start=1):
            label = f"G{i}"
            subtree = set()
            for vlid in bin_:
                subtree |= self._subtree_by_label(net, zone_map,
                                                  valve_labels[vlid])
                zone_map_out[vlid] = label
            for lid in subtree:
                zone_map_out[self._base_id(lid)] = label
            groups.append({
                "zone": label,
                "valves": bin_,
                "flow_lph": round(sum(flows.get(v, 0.0) for v in bin_), 1),
            })

        written = self._write_zones(zone_map_out)
        self._apply_zone_renderer()
        summary = "  ".join(
            f"{g['zone']}:{len(g['valves'])}阀/{g['flow_lph']:.0f}L/h"
            for g in groups)
        self.iface.messageBar().pushMessage(
            "aQuaDrip",
            QApplication.translate("ZoneDivider",
                                   "按流量编组完成: {0} 组（目标 {1:.0f} L/h, 总需求 {2:.0f} L/h） {3}").format(
                                       len(groups), target_flow_lph, total, summary),
            level=0, duration=8)
        return {"groups": groups, "pipes": written}

    # ── 层级 BFS ──

    def _traverse(self, start_node: str,
                  graph: Dict[str, List[Tuple[object, str]]],
                  all_valves: List[object],
                  zone_map: Dict[str, str],
                  valve_counter: Dict[int, int],
                  zone_prefix: str,
                  visited: Set[str],
                  valve_labels: Optional[Dict[str, str]] = None,
                  sources: Optional[Set[str]] = None):
        """BFS 遍历管网，遇到阀门时递归进入子分区。

        Args:
            start_node: 起始节点 ID
            graph: 有向邻接表
            all_valves: 所有阀门对象列表（用于跳过标记）
            zone_map: {link_id: zone_label}
            valve_counter: {level: next_number} 每层分区的下一个编号
            zone_prefix: 当前分区前缀（""=水源上游，"1"=一级分区）
            visited: 全局已访问节点集
            valve_labels: 可选输出 {valve_lid: 细分标签}（按发现顺序，
                供按流量编组使用——BFS 序即沿干管的空间顺序）
            sources: 水源节点集合（下游侧判定用，与存储方向无关）
        """
        sources_set = sources or set()
        queue = deque([start_node])

        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)

            for link, next_node in graph.get(node, []):
                is_valve = hasattr(link, "valve_type")

                if is_valve and link in all_valves and link.id not in zone_map:
                    # 计算子分区编号
                    level = (zone_prefix.count("-") + 1) if zone_prefix else 1
                    valve_counter[level] = valve_counter.get(level, 0) + 1
                    seq = valve_counter[level]
                    child_prefix = f"{zone_prefix}-{seq}" if zone_prefix else str(seq)
                    # 阀门标记为它控制的子分区（而非父分区），
                    # 这样轮灌调度可直接从阀门 zone 字段读取分区归属
                    zone_map[link.id] = child_prefix
                    if valve_labels is not None:
                        valve_labels[link.id] = child_prefix
                    # 下游侧判定与存储方向无关（sync 的拓扑回写会按
                    # 几何顶点序覆盖 DirectionFixer 的成果，不能信方向）
                    other_side = self._downstream_side(link, graph, sources_set)
                    # 递归处理阀门下游
                    self._traverse(other_side, graph, all_valves,
                                  zone_map, valve_counter, child_prefix, visited,
                                  valve_labels, sources_set)
                elif is_valve:
                    # 阀门已处理过（从另一方向到达），跳过不重复标记
                    continue
                else:
                    # 普通管道或水泵：标记当前分区
                    zone_map[link.id] = zone_prefix or "0"
                    if next_node not in visited:
                        queue.append(next_node)

    def _downstream_side(self, link, graph, sources_set: Set[str]) -> str:
        """阀门的下游侧节点（与存储 from/to 方向无关）

        不穿越任何阀门就能到达水源的一侧 = 上游侧，返回另一侧。
        判不了（两侧都不可达，如孤立段）时回退 to_node。
        """
        def _reaches_source(start: str) -> bool:
            seen = {link.from_node, link.to_node}
            q = deque([start])
            while q:
                n = q.popleft()
                if n in sources_set:
                    return True
                for nxt_link, nxt in graph.get(n, []):
                    if hasattr(nxt_link, "valve_type"):
                        continue
                    if nxt not in seen:
                        seen.add(nxt)
                        q.append(nxt)
            return False

        if _reaches_source(link.to_node):
            return link.from_node
        return link.to_node

    # ── 子树与标签辅助（合并/编组共用） ──

    def _valve_subtree(self, valve_lid: str, net, graph,
                       sources: Optional[Set[str]] = None) -> Set[str]:
        """阀门下游子树的 link id 集合（到其他阀门为止，不含阀门自身）

        下游侧判定与存储的 from/to 方向无关：不穿越任何阀门就能
        到达水源的一侧 = 上游侧（DirectionFixer 修好的方向会被
        SyncManager 的拓扑回写按几何顶点序覆盖，不能依赖）。
        从另一侧（下游）BFS 收集普通管道；遇任何阀门都不穿越
        （未选中的阀门保留其自己的子分区）。
        """
        link = net.links.get(valve_lid)
        if link is None:
            return set()
        sources_set = sources or set()

        def _reaches_source(start: str) -> bool:
            """从 start 出发不穿越阀门能否到达水源（= start 是上游侧）"""
            seen = {link.from_node, link.to_node}
            q = deque([start])
            while q:
                n = q.popleft()
                if n in sources_set:
                    return True
                for nxt_link, nxt in graph.get(n, []):
                    if hasattr(nxt_link, "valve_type"):
                        continue  # 不穿越阀门
                    if nxt not in seen:
                        seen.add(nxt)
                        q.append(nxt)
            return False

        if _reaches_source(link.to_node):
            start = link.from_node  # to 侧是上游 → 从 from 侧出发
        else:
            start = link.to_node

        subtree: Set[str] = set()
        visited_nodes = {link.from_node, link.to_node}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for nxt_link, next_node in graph.get(node, []):
                if hasattr(nxt_link, "valve_type"):
                    continue  # 不穿越任何阀门
                subtree.add(nxt_link.id)
                if next_node not in visited_nodes:
                    visited_nodes.add(next_node)
                    queue.append(next_node)
        return subtree

    def _subtree_by_label(self, net, zone_map: Dict[str, str],
                          label: str) -> Set[str]:
        """按细分标签取子树：标签等于 label 或为其后代（label-...）的 link"""
        prefix = label + "-"
        return {lid for lid, z in zone_map.items()
                if z == label or z.startswith(prefix)}

    @staticmethod
    def _base_id(lid: str) -> str:
        """拓扑切段 id → 原始要素 id（"L12_p3" → "L12"）"""
        return lid.split("_p")[0]

    def _next_group_label(self) -> str:
        """生成不与现有分区冲突的组标签 G{n}"""
        existing = set()
        for key in ("aqd_pipes", "aqd_valves"):
            layer = self._find_layer(key)
            if layer is None:
                continue
            for feat in layer.getFeatures():
                z = str(feat.attribute("zone") or "")
                if z.startswith("G"):
                    existing.add(z)
        n = 1
        while f"G{n}" in existing:
            n += 1
        return f"G{n}"

    def _estimate_valve_flows(self, zone_map: Dict[str, str],
                              valve_labels: Dict[str, str], net) -> Dict[str, float]:
        """估算每个阀门细分区的需求流量（L/h）

        优先用最新一次模拟的管段流量聚合（真实水力状态）；
        无模拟历史时按几何估算：毛管长/滴头间距 × 滴头出流
        （q = k·P^x，P 按 10 m 工作压力计）。
        """
        # 阀门 → 子树 link 集合
        subtree_map = {vlid: self._subtree_by_label(net, zone_map, label)
                       for vlid, label in valve_labels.items()}

        sim_flow = self._latest_link_flow()
        if sim_flow:
            flows = {}
            for vlid, links in subtree_map.items():
                q = 0.0
                for lid in links:
                    q += sim_flow.get(self._base_id(lid), 0.0)
                flows[vlid] = q
            return flows

        # 几何估算兜底
        pipe_layer = self._find_layer("aqd_pipes")
        if pipe_layer is None:
            return {vlid: 0.0 for vlid in valve_labels}
        from qgis.core import QgsDistanceArea
        da = None
        try:
            crs = pipe_layer.crs()
            if crs.isValid():
                da = QgsDistanceArea()
                da.setSourceCrs(crs, self.project.transformContext())
                da.setEllipsoid("WGS84")
        except Exception:
            da = None

        fid_flow = {}
        for feat in pipe_layer.getFeatures():
            if str(feat.attribute("pipe_type") or "") != "lateral":
                continue
            try:
                fid = feat.id()
            except Exception:
                continue
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            line = geom.asPolyline()
            if len(line) < 2:
                continue
            if da is not None:
                length_m = float(da.measureLine(line) or 0)
                if length_m <= 0:
                    length_m = geom.length() * 111320.0
            else:
                length_m = geom.length() * 111320.0
            spacing = float(feat.attribute("emitter_spacing") or 0.3)
            k = float(feat.attribute("emitter_k") or 0.506)
            x = float(feat.attribute("emitter_x") or 0.5)
            q_nominal = k * (10.0 ** x)  # 10 m 工作压力下的单滴头流量 L/h
            fid_flow[f"L{fid}"] = (length_m / spacing if spacing > 0 else 0) * q_nominal

        flows = {}
        for vlid, links in subtree_map.items():
            q = 0.0
            for lid in links:
                q += fid_flow.get(self._base_id(lid), 0.0)
            flows[vlid] = q
        return flows

    def _latest_link_flow(self) -> Optional[Dict[str, float]]:
        """最新模拟记录的管段流量（L/h），按原始要素聚合切段

        Returns:
            {"L12": 合计 L/h, ...} 或 None（无历史/读取失败）
        """
        try:
            from .layer_utils import find_gpkg_path
            from .sim_history import SimHistory
            gpkg = find_gpkg_path(self.project, "aqd_fields")
            if not gpkg:
                return None
            rec = SimHistory(gpkg).latest()
            if not rec:
                return None
            agg: Dict[str, float] = {}
            for lid, v in rec.get("link_flow", {}).items():
                base = self._base_id(lid)
                agg[base] = agg.get(base, 0.0) + float(v)
            return agg if agg else None
        except Exception:
            return None

    # ── 写回图层 ──

    def _write_zones(self, zone_map: Dict[str, str]) -> int:
        """将 zone 标签写回到图层

        zone_map 的 key 是 link.id，值为 "L{fid}" 前缀格式。
        需要映射回各图层：L*→aqd_pipes, PU*→aqd_pumps, V*→aqd_valves
        """
        layers = {
            "L": self._find_layer("aqd_pipes"),
            "PU": self._find_layer("aqd_pumps"),
            "V": self._find_layer("aqd_valves"),
        }
        # 构建 fid→feature 映射
        fid_map = {}  # {prefix: {fid: feature}}
        for prefix, layer in layers.items():
            if layer is None:
                continue
            fm = {}
            for feat in layer.getFeatures():
                fm[feat.id()] = feat
            fid_map[prefix] = fm

        written = 0
        for prefix, layer in layers.items():
            if layer is None:
                continue
            fm = fid_map.get(prefix, {})
            need_edit = not layer.isEditable()
            if need_edit:
                layer.startEditing()
            try:
                for lid, zone_label in zone_map.items():
                    if not lid.startswith(prefix):
                        continue
                    # 从 lid 提取 fid: "L3"→3
                    try:
                        fid = int(lid[len(prefix):])
                    except ValueError:
                        continue
                    feat = fm.get(fid)
                    if feat is None:
                        continue
                    feat.setAttribute("zone", zone_label)
                    layer.updateFeature(feat)
                    written += 1
                if need_edit:
                    layer.commitChanges()
            except Exception:
                if need_edit:
                    layer.rollBack()
                raise

        for layer in layers.values():
            if layer is not None:
                layer.triggerRepaint()
        return written

    # ── 分区着色 ──

    def _apply_zone_renderer(self):
        """对 aqd_pipes 图层按 zone 分类着色"""
        pipe_layer = self._find_layer("aqd_pipes")
        if pipe_layer is None:
            return
        try:
            from qgis.core import (
                QgsCategorizedSymbolRenderer, QgsRendererCategory,
                QgsSymbol,
            )
            from qgis.PyQt.QtGui import QColor

            # 收集所有 zone 值并排序
            zones = set()
            for feat in pipe_layer.getFeatures():
                z = str(feat.attribute("zone") or "")
                if z:
                    zones.add(z)
            if not zones:
                return

            # 数字层级标签按数值排序；G 组标签（多阀合并/编组产物）
            # 按名称排在层级标签之后
            def _zone_sort_key(z: str):
                try:
                    return [int(x) for x in z.split("-")]
                except ValueError:
                    return [10 ** 6, z]
            sorted_zones = sorted(zones, key=_zone_sort_key)

            colors = [
                QColor(179, 179, 179),    # "" 灰色
                QColor(66, 165, 245),     # "1" 蓝
                QColor(144, 202, 249),    # "1-1" 浅蓝
                QColor(129, 212, 250),    # "1-2" 更浅蓝
                QColor(102, 187, 106),    # "2" 绿
                QColor(165, 214, 167),    # "2-1" 浅绿
                QColor(255, 167, 38),     # "3" 橙
                QColor(255, 204, 128),    # "3-1" 浅橙
                QColor(239, 83, 80),      # "4" 红
                QColor(229, 115, 115),    # "4-1" 浅红
                QColor(171, 71, 188),     # "5" 紫
                QColor(206, 147, 216),    # "5-1" 浅紫
            ]

            categories = []
            # 先加空 zone
            symbol = QgsSymbol.defaultSymbol(pipe_layer.geometryType())
            symbol.setColor(QColor(220, 220, 220))
            symbol.setWidth(0.8)
            categories.append(QgsRendererCategory("", symbol, QApplication.translate("ZoneDivider", "公共区")))

            for i, z in enumerate(sorted_zones):
                symbol = QgsSymbol.defaultSymbol(pipe_layer.geometryType())
                symbol.setColor(colors[i % len(colors)])
                symbol.setWidth(1.2)
                label = QApplication.translate("ZoneDivider", "分区 {0}").format(z)
                categories.append(QgsRendererCategory(z, symbol, label))

            renderer = QgsCategorizedSymbolRenderer("zone", categories)
            pipe_layer.setRenderer(renderer)
            pipe_layer.triggerRepaint()
        except Exception as e:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("ZoneDivider", "分区着色失败: {0}").format(e))

    # ── 图层查找 ──

    def _find_layer(self, key: str) -> Optional[QgsVectorLayer]:
        from .layer_utils import find_layer
        return find_layer(self.project, key)
