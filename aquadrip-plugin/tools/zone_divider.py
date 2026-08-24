"""ZoneDivider — 根据阀门自动划分管网分区（支持嵌套阀门层级）

算法:
  1. 从 SyncManager 构建 DripNetwork
  2. 构建有向邻接表（Pipe 双向，Valve/Pump 单向 from→to）
  3. 从水源节点 BFS，遇到 Valve 时递归划分子区
  4. 层级编号 "1", "1-1", "1-2", "2" ...
  5. 写回 aqd_pipes/aqd_pumps/aqd_valves.zone 字段
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

    def divide(self) -> dict:
        """主入口：矫正方向 → 划分分区 → 写回图层

        Returns:
            {"valves": int, "zones": int, "pipes": int}
        """
        # 0. 自动矫正阀门/水泵方向（确保 from_node 指向远离水源的一侧）
        from .direction_fixer import DirectionFixer
        DirectionFixer(self.iface).fix()

        # 1. 构建 DripNetwork（不展开毛管）
        from .sync_manager import SyncManager
        sync = SyncManager(self.iface)
        net = sync.sync_qgis_to_network(expand=False, split_vertices=False)

        if not net.links:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("ZoneDivider", "管网中没有管道"))
            return {"valves": 0, "zones": 0, "pipes": 0}

        # 2. 构建有向邻接表 + 收集阀门和水源
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

        if not sources:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("ZoneDivider", "管网中没有水源节点"))
            return {"valves": len(all_valves), "zones": 0, "pipes": 0}

        # 3. 层级 BFS 分区
        zone_map: Dict[str, str] = {}  # {link_id: zone_label}
        valve_counter: Dict[int, int] = {}  # {level: next_number}

        global_visited: Set[str] = set()
        for src in sources:
            self._traverse(src, graph, all_valves, zone_map,
                          valve_counter, "", global_visited)

        # 4. 写回图层
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

        # 5. 对 aqd_pipes 应用分类着色
        self._apply_zone_renderer()

        return {"valves": len(all_valves), "zones": zones, "pipes": written}

    # ── 层级 BFS ──

    def _traverse(self, start_node: str,
                  graph: Dict[str, List[Tuple[object, str]]],
                  all_valves: List[object],
                  zone_map: Dict[str, str],
                  valve_counter: Dict[int, int],
                  zone_prefix: str,
                  visited: Set[str]):
        """BFS 遍历管网，遇到阀门时递归进入子分区。

        Args:
            start_node: 起始节点 ID
            graph: 有向邻接表
            all_valves: 所有阀门对象列表（用于跳过标记）
            zone_map: {link_id: zone_label}
            valve_counter: {level: next_number} 每层分区的下一个编号
            zone_prefix: 当前分区前缀（""=水源上游，"1"=一级分区）
            visited: 全局已访问节点集
        """
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
                    # 确定阀门的「另一侧」节点（可能因反向遍历而不同）
                    other_side = link.from_node if node == link.to_node else link.to_node
                    # 递归处理阀门下游
                    self._traverse(other_side, graph, all_valves,
                                  zone_map, valve_counter, child_prefix, visited)
                elif is_valve:
                    # 阀门已处理过（从另一方向到达），跳过不重复标记
                    continue
                else:
                    # 普通管道或水泵：标记当前分区
                    zone_map[link.id] = zone_prefix or "0"
                    if next_node not in visited:
                        queue.append(next_node)

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

            sorted_zones = sorted(zones,
                key=lambda z: [int(x) for x in z.split("-")])

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
