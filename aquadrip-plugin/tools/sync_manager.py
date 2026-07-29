"""SyncManager — QGIS 图层与 wdrip-core DripNetwork 双向同步

核心方法:
  sync_qgis_to_network()  — QGIS → DripNetwork
      读取农田/节点/管道 → 端点匹配节点（回写 from_node/to_node）
      → 毛管按 emitter_spacing 展开为 EmitterNode 滴头链
  sync_from_network()     — DripNetwork → QGIS（模拟结果回写）

单位约定（与 wdrip.network.links 一致）：
  - Pipe/Valve diameter: mm（WNTR 转换时在 core 内统一 /1000）
  - length: m（取几何长度）
  - 坐标/容差: 随图层 CRS（投影=米，经纬度=度，sync 时警告）
"""

import math
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsGeometry, QgsPointXY, QgsFeature,
)

if TYPE_CHECKING:
    from wdrip.network import DripNetwork
    from wdrip.simulation.result import SimulationResult


class SyncManager:
    """QGIS ↔ DripNetwork 同步管理器"""

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()

    # ── 字段安全读取 ──

    @staticmethod
    def _attr(feat: QgsFeature, name: str, default=None):
        """安全读取字段值（字段不存在或 NULL 时返回 default）

        不直接依赖 QgsFeature.attribute(name) 对缺失字段的行为——
        不同 QGIS 版本/构建下可能返回 None 或抛 KeyError('id')。
        """
        idx = feat.fields().lookupField(name)
        if idx < 0:
            return default
        val = feat.attribute(idx)
        return default if val is None else val

    # ── 从 QGIS 读取 → 构建 DripNetwork ──

    def sync_qgis_to_network(self) -> 'DripNetwork':
        """从 QGIS 图层读取数据，构建 DripNetwork（含毛管展开）"""
        from wdrip.network import (
            DripNetwork, FieldInfo,
            SourceNode, Junction,
            Pipe, Pump, Valve, ValveType,
            expand_lateral,
        )

        net = DripNetwork(name="aQuaDrip 项目")

        pipe_layer = self._get_layer("aqd_pipes")
        if self._is_geographic():
            self.log("⚠️ 图层为经纬度坐标，长度/面积按度计算，建议投影到米制坐标系")

        # 1. 读取农田
        field_layer = self._get_layer("aqd_fields")
        if field_layer and field_layer.featureCount() > 0:
            feat = next(field_layer.getFeatures())
            fgeom = feat.geometry()
            net.field_info = FieldInfo(
                area=fgeom.area() if fgeom and not fgeom.isEmpty() else 0.0,
                crop_type=str(self._attr(feat, "crop_type") or ""),
                planting_pattern=str(self._attr(feat, "planting_pattern") or "uniform"),
                row_spacings=[float(self._attr(feat, "row_spacing") or 0.5)],
                ridge_count=int(self._attr(feat, "ridge_count") or 0) or None,
                row_direction=float(self._attr(feat, "row_direction") or 0),
                emitter_spacing=float(self._attr(feat, "emitter_spacing") or 0.3),
                geometry=fgeom,
            )

        # 2. 读取节点
        node_layer = self._get_layer("aqd_nodes")
        node_positions = {}  # {coord_key: id} 用于管道端点匹配
        if node_layer:
            for feat in node_layer.getFeatures():
                geom = feat.geometry()
                if not geom or geom.isEmpty():
                    continue
                pt = geom.asPoint()
                nid = str(self._attr(feat, "id") or f"N{feat.id()}")
                node_type = str(self._attr(feat, "node_type") or "junction")
                elev = float(self._attr(feat, "elevation") or 0)

                if node_type == "source":
                    node = SourceNode(
                        nid, pt.x(), pt.y(), elevation=elev,
                        source_type=str(self._attr(feat, "source_type") or "well"),
                        head=float(self._attr(feat, "head") or 0),
                        available_flow=float(self._attr(feat, "available_flow") or 0))
                else:
                    node = Junction(nid, pt.x(), pt.y(), elevation=elev)

                net.add_node(node)
                node_positions[self._coord_key(pt.x(), pt.y())] = nid

        # 3. 读取管道 → T 型交叉分段 → 建 link（端点匹配 + 拓扑回写）
        laterals: List[Tuple[str, float]] = []  # [(link_id, emitter_spacing)]
        if pipe_layer:
            need_edit = not pipe_layer.isEditable()
            if need_edit:
                pipe_layer.startEditing()
            try:
                # 3.1 收集所有管道记录
                records = []
                for feat in pipe_layer.getFeatures():
                    geom = feat.geometry()
                    if not geom or geom.isEmpty():
                        continue
                    line = geom.asPolyline()
                    if len(line) < 2:
                        continue
                    records.append({
                        "feat": feat,
                        "lid": str(self._attr(feat, "id") or f"L{feat.id()}"),
                        "geom": geom,
                        "line": line,
                        "pipe_type": str(self._attr(feat, "pipe_type") or "mainline"),
                        "device": str(self._attr(feat, "device") or "none"),
                    })

                # 3.2 T 型交叉分段：节点/管端点落在管道中间时自动断开，
                #     使交叉点成为真正的拓扑连接（否则管网不连通，
                #     大量滴头无水源可达，流量为 0）
                segments = self._planarize(records, node_positions)

                # 3.3 逐段建 link
                for seg in segments:
                    rec = seg["record"]
                    pts = seg["pts"]
                    seg_length = QgsGeometry.fromPolylineXY(pts).length()
                    if seg_length <= 0:
                        continue  # 重合分割点产生的零长度段，跳过
                    lid = rec["lid"] if seg["part"] == 0 else \
                        f"{rec['lid']}_p{seg['part'] + 1}"

                    from_node = self._match_node(node_positions, pts[0])
                    to_node = self._match_node(node_positions, pts[-1])

                    # 端点无匹配节点时自动创建 Junction
                    if not from_node:
                        from_node = f"auto_N{len(net.nodes)}"
                        net.add_node(Junction(from_node, pts[0].x(), pts[0].y()))
                        node_positions[self._coord_key(pts[0].x(), pts[0].y())] = from_node
                    if not to_node:
                        to_node = f"auto_N{len(net.nodes)}"
                        net.add_node(Junction(to_node, pts[-1].x(), pts[-1].y()))
                        node_positions[self._coord_key(pts[-1].x(), pts[-1].y())] = to_node

                    # 记录首/末段端节点，用于拓扑回写
                    if seg["part"] == 0:
                        rec["_first_from"] = from_node
                    rec["_last_to"] = to_node

                    # 字段读取（diameter 保持 mm，core 内统一转换）
                    feat = rec["feat"]
                    diameter = float(self._attr(feat, "diameter") or 0)
                    length = seg_length
                    roughness = float(self._attr(feat, "roughness") or 130)
                    pipe_type = rec["pipe_type"]
                    device = rec["device"]

                    if device == "pump":
                        link = Pump(lid, from_node, to_node,
                                    rated_head=float(self._attr(feat, "pump_head") or 0),
                                    rated_flow=float(self._attr(feat, "pump_flow") or 0),
                                    rated_power=float(self._attr(feat, "pump_power") or 0))
                    elif device == "valve":
                        vtype_str = str(self._attr(feat, "valve_type") or "gate").upper()
                        vtype = getattr(ValveType, vtype_str, ValveType.GATE)
                        # TODO: aqd_pipes 暂无 valve_setting 字段，先用默认 10.0
                        link = Valve(lid, from_node, to_node,
                                     valve_type=vtype,
                                     setting=10.0,
                                     diameter=diameter)
                    else:
                        link = Pipe(lid, from_node, to_node,
                                    pipe_type=pipe_type,
                                    diameter=diameter, length=length,
                                    roughness=roughness)

                    net.add_link(link)

                    if pipe_type == "lateral" and device == "none":
                        es = float(self._attr(feat, "emitter_spacing") or 0)
                        if es <= 0 and net.field_info:
                            es = net.field_info.emitter_spacing
                        laterals.append((lid, es if es > 0 else 0.3))

                # 3.4 拓扑回写：QGIS 要素仍是整条管道，回写其首/末节点
                for rec in records:
                    feat = rec["feat"]
                    feat.setAttribute("from_node", rec.get("_first_from", ""))
                    feat.setAttribute("to_node", rec.get("_last_to", ""))
                    pipe_layer.updateFeature(feat)
            finally:
                if need_edit:
                    pipe_layer.commitChanges()

        # 4. 毛管展开为 EmitterNode 滴头链（模拟出水的前提）
        for lid, es in laterals:
            try:
                expand_lateral(net, lid, es)
            except Exception as e:
                self.log(f"⚠️ 毛管 {lid} 展开失败: {e}")

        return net

    # ── 将模拟结果写回 QGIS ──

    def sync_from_network(self, network: 'DripNetwork',
                          result: 'SimulationResult' = None):
        """将模拟结果写回 QGIS 图层（flow/velocity/pressure）"""
        pipe_layer = self._get_layer("aqd_pipes")
        node_layer = self._get_layer("aqd_nodes")
        if not result:
            return

        # 写入管道结果（流量、流速）
        if pipe_layer:
            need_edit = not pipe_layer.isEditable()
            if need_edit:
                pipe_layer.startEditing()
            try:
                for feat in pipe_layer.getFeatures():
                    lid = str(self._attr(feat, "id") or f"L{feat.id()}")
                    changed = False
                    if lid in result.link_flow:
                        arr = result.link_flow[lid]
                        if len(arr) > 0:
                            feat.setAttribute("flow", float(arr[-1]))
                            changed = True
                    if lid in result.link_velocity:
                        arr = result.link_velocity[lid]
                        if len(arr) > 0:
                            feat.setAttribute("velocity", float(arr[-1]))
                            changed = True
                    if changed:
                        pipe_layer.updateFeature(feat)
            finally:
                if need_edit:
                    pipe_layer.commitChanges()
            pipe_layer.triggerRepaint()

        # 写入节点结果（压力）
        if node_layer:
            # 迁移兜底：旧 GPKG 无 pressure 字段时自动补
            self._ensure_field(node_layer, "pressure")
            need_edit = not node_layer.isEditable()
            if need_edit:
                node_layer.startEditing()
            try:
                for feat in node_layer.getFeatures():
                    nid = str(self._attr(feat, "id") or f"N{feat.id()}")
                    if nid in result.node_pressure:
                        arr = result.node_pressure[nid]
                        if len(arr) > 0:
                            feat.setAttribute("pressure", float(arr[-1]))
                            node_layer.updateFeature(feat)
            finally:
                if need_edit:
                    node_layer.commitChanges()
            node_layer.triggerRepaint()

    # ── T 型交叉分段（planarize）──

    def _planarize(self, records: list, node_positions: dict) -> list:
        """T 型交叉分段

        兴趣点 = 所有已有节点 + 所有管道端点。对每条管道，找出落在其
        几何中间的兴趣点，按沿线位置排序后拆为多段。

        Returns:
            [{"record", "part", "pts"}]，part=0 为第一段（保留原 lid）
        """
        # 兴趣点：{coord_key: QgsPointXY}
        interest = {key: QgsPointXY(key[0], key[1]) for key in node_positions}
        for rec in records:
            for pt in (rec["line"][0], rec["line"][-1]):
                key = self._coord_key(pt.x(), pt.y())
                interest.setdefault(key, pt)

        # 在线判定容差（远小于节点匹配容差，否则会把相邻毛管的
        # 交叉节点误判到当前毛管上，产生重合分割点和零长度段）
        online_tol = self._online_tolerance()
        # 端点边距（分割点距端点的最小距离，用节点匹配容差）
        edge_margin = self._match_tolerance()
        all_segments = []
        for rec in records:
            line = rec["line"]
            end_keys = {
                self._coord_key(line[0].x(), line[0].y()),
                self._coord_key(line[-1].x(), line[-1].y()),
            }
            total_len = rec["geom"].length()
            if total_len <= 0:
                continue

            # 找中间穿越点（排除端点位置，端点由节点匹配处理）
            hits = []  # [(cum_len, key)]
            for key, pt in interest.items():
                if key in end_keys:
                    continue
                cum = self._project_cum_len(line, pt, online_tol)
                if cum is not None and edge_margin < cum < total_len - edge_margin:
                    hits.append((cum, key))
            hits.sort()
            # 分割点去重：多个兴趣点投影到同一/相近位置只保留一个，
            # 避免切出零长度段
            deduped = []
            for cum, key in hits:
                if deduped and abs(cum - deduped[-1][0]) < edge_margin:
                    continue
                deduped.append((cum, key))
            hits = deduped

            if not hits:
                all_segments.append({"record": rec, "part": 0, "pts": line})
                continue

            ratios = [cum / total_len for cum, _ in hits]
            parts = self._split_line(line, ratios)
            for i, pts in enumerate(parts):
                all_segments.append({"record": rec, "part": i, "pts": pts})
        return all_segments

    @staticmethod
    def _project_cum_len(line: list, pt: QgsPointXY,
                         tolerance: float) -> Optional[float]:
        """pt 投影到折线上的累积长度位置；距线超容差返回 None"""
        cum = 0.0
        pt_geom = QgsGeometry.fromPointXY(pt)
        for i in range(len(line) - 1):
            seg_len = line[i].distance(line[i + 1])
            if seg_len > 0:
                seg_geom = QgsGeometry.fromPolylineXY([line[i], line[i + 1]])
                if seg_geom.distance(pt_geom) <= tolerance:
                    r = line[i].distance(pt) / seg_len
                    r = max(0.0, min(1.0, r))
                    return cum + seg_len * r
            cum += seg_len
        return None

    @staticmethod
    def _split_line(line: list, ratios: list) -> list:
        """按沿线比例（0~1，已排序）把折线拆为多段"""
        seg_lens = [line[i].distance(line[i + 1])
                    for i in range(len(line) - 1)]
        total = sum(seg_lens)
        if total <= 0:
            return [line]

        # 各分割点坐标
        split_pts = []
        for ratio in ratios:
            target = total * ratio
            cum = 0.0
            pt = line[-1]
            for i, sl in enumerate(seg_lens):
                if sl > 0 and cum + sl >= target:
                    r = (target - cum) / sl
                    pt = QgsPointXY(
                        line[i].x() + (line[i + 1].x() - line[i].x()) * r,
                        line[i].y() + (line[i + 1].y() - line[i].y()) * r)
                    break
                cum += sl
            split_pts.append(pt)

        # 组装各段
        parts = []
        current = [line[0]]
        cum = 0.0
        si = 0
        targets = [total * r for r in ratios]
        for i, sl in enumerate(seg_lens):
            next_cum = cum + sl
            while si < len(split_pts) and cum < targets[si] <= next_cum:
                current.append(split_pts[si])
                parts.append(current)
                current = [split_pts[si]]
                si += 1
            current.append(line[i + 1])
            cum = next_cum
        parts.append(current)
        return [p for p in parts if len(p) >= 2]

    # ── 节点匹配（CRS 自适应容差）──

    def _match_node(self, node_positions: dict, pt: QgsPointXY) -> Optional[str]:
        """从节点位置字典中匹配最近的节点"""
        key = self._coord_key(pt.x(), pt.y())
        if key in node_positions:
            return node_positions[key]
        # 容差匹配（兜底）
        tolerance = self._match_tolerance()
        best = None
        best_dist = tolerance
        for (nx, ny), nid in node_positions.items():
            dist = math.sqrt((nx - pt.x())**2 + (ny - pt.y())**2)
            if dist < best_dist:
                best_dist = dist
                best = nid
        return best

    def _coord_key(self, x: float, y: float) -> Tuple[float, float]:
        """坐标 key 精度：投影坐标 1mm，经纬度约 1cm"""
        digits = 7 if self._is_geographic() else 3
        return (round(x, digits), round(y, digits))

    def _match_tolerance(self) -> float:
        """匹配容差：投影坐标 1m，经纬度约 1m"""
        return 1e-5 if self._is_geographic() else 1.0

    def _online_tolerance(self) -> float:
        """点"在线上"的判定容差（远小于节点匹配容差）

        交叉节点/管端点由 snapping 或投影生成、精确在线上，此容差只需
        覆盖浮点误差。若误用节点匹配容差（1m），会把相邻毛管（间距
        0.3m）的交叉节点误判到当前毛管上，产生大量重合分割点。
        """
        return 1e-8 if self._is_geographic() else 1e-3

    def _is_geographic(self) -> bool:
        layer = self._get_layer("aqd_nodes") or self._get_layer("aqd_pipes")
        return bool(layer and layer.crs().isGeographic())

    # ── 图层查找（从项目中找，与其他工具一致）──

    @staticmethod
    def _ensure_field(layer: QgsVectorLayer, field_name: str):
        """确保图层存在指定字段（用于旧 GPKG 的字段迁移）"""
        from qgis.core import QgsField
        from qgis.PyQt.QtCore import QVariant
        if layer.fields().lookupField(field_name) < 0:
            layer.dataProvider().addAttributes(
                [QgsField(field_name, QVariant.Double)])
            layer.updateFields()

    def _get_layer(self, key: str) -> Optional[QgsVectorLayer]:
        """从项目已加载图层中查找（按名称或 source 匹配）

        注意：必须用项目中的图层实例，写回结果才能实时刷新；
        用 gpkg 路径重开的图层对象修改后项目视图不会更新。
        """
        for layer in self.project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if layer.name() == key or key in (layer.source() or ""):
                return layer
        return None

    def log(self, msg: str):
        """输出日志"""
        self.iface.messageBar().pushMessage("aQuaDrip", msg, level=0, duration=3)
