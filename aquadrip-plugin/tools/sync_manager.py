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

    def sync_qgis_to_network(self, expand: bool = True,
                             split_vertices: bool = False) -> 'DripNetwork':
        """从 QGIS 图层读取数据，构建 DripNetwork

        Args:
            expand: 是否展开毛管为滴头链（模拟用）。
                INP 导出时应为 False 以保留原始管网结构。
            split_vertices: 是否在每个折线顶点处分割管道（INP 导出用）。
                EPANET 只支持两点直线，QGIS 折线的每个顶点都需要 junction。
        """
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

        # 2. 读取节点和管道要素
        node_layer = self._get_layer("aqd_nodes")
        node_features = list(node_layer.getFeatures()) if node_layer else []

        pipe_features = []
        if pipe_layer:
            pipe_features = list(pipe_layer.getFeatures())

        # 3. 统一拓扑构建（几何相交驱动，不经坐标匹配）
        from .topology_builder import TopologyBuilder

        if split_vertices:
            # INP 导出：折线每个顶点都需 junction
            pipe_fields = pipe_layer.fields() if pipe_layer else None
            recs = []
            for feat in pipe_features:
                geom = feat.geometry()
                if not geom or geom.isEmpty(): continue
                line = geom.asPolyline()
                if len(line) < 2: continue
                recs.append({
                    "line": line,
                    "lid": str(self._attr(feat, "id") or f"L{feat.id()}"),
                    "geom": geom,
                    "feat": feat,
                })
            vertex_segs = self._split_at_vertices(recs)
            # 转为 TopologyBuilder 需要的格式
            # 关键：fake_feat 必须继承原 feat 的 fields/attributes/fid，
            # 否则 TopologyBuilder 读 diameter/roughness/device 等字段
            # 会得到 None→0，导出的 INP 管径/糙率全为默认值
            builder_features = []
            for seg in vertex_segs:
                src_feat = seg["record"].get("feat")
                if src_feat is not None and pipe_fields is not None:
                    fake_feat = QgsFeature(pipe_fields)
                    fake_feat.setAttributes(src_feat.attributes())
                    fake_feat.setId(src_feat.id())
                else:
                    fake_feat = QgsFeature()
                fake_feat.setGeometry(QgsGeometry.fromPolylineXY(seg["pts"]))
                builder_features.append(fake_feat)
            builder = TopologyBuilder(net, self._is_geographic())
            segments = builder.build(node_features, builder_features)
        else:
            builder = TopologyBuilder(net, self._is_geographic())
            segments = builder.build(node_features, pipe_features)

        # 诊断
        lat_count = len([s for s in segments if s["pipe_type"] == "lateral"])
        self.log(f"拓扑构建: {len(segments)} 段（毛管 {lat_count}）"
                 f" 节点 {len(net.nodes)}")

        # 4. 从 segments 建 link + 收集毛管
        laterals: List[dict] = []  # [{lid, spacing, k, x}]
        # link 几何（含转弯折线顶点）：可视化时按 lid 取折线，
        # 否则被交叉切断的分段(L{fid}_p{n})只能从端点画直线，丢失转弯形状。
        # 运行时挂到 net 上（不污染核心 Pipe 模型），由 _save_sim_history 持久化。
        link_geometry: Dict[str, list] = {}
        if pipe_layer:
            need_edit = not pipe_layer.isEditable()
            if need_edit:
                pipe_layer.startEditing()
            try:
                fid_to_segs = {}  # {fid: [segments]}
                for seg in segments:
                    fid_to_segs.setdefault(seg["fid"], []).append(seg)

                for seg in segments:
                    pts = seg["pts"]
                    seg_length = QgsGeometry.fromPolylineXY(pts).length()
                    if seg_length <= 0:
                        continue
                    rec_fid = seg["fid"]
                    lid = seg["lid"] if seg["part"] == 0 else \
                        f"{seg['lid']}_p{seg['part'] + 1}"
                    from_node = seg["from_node"]
                    to_node = seg["to_node"]
                    if not from_node or not to_node:
                        continue

                    # 记录该分段的折线顶点（含转弯），供可视化重建几何
                    link_geometry[lid] = [
                        (float(p.x()), float(p.y())) for p in pts
                    ]

                    feat = seg["feat"]
                    diameter = float(self._attr(feat, "diameter") or 0)
                    roughness = float(self._attr(feat, "roughness") or 130)
                    pipe_type = seg["pipe_type"]
                    device = seg["device"]

                    if device == "pump":
                        link = Pump(lid, from_node, to_node,
                                    rated_head=float(self._attr(feat, "pump_head") or 0),
                                    rated_flow=float(self._attr(feat, "pump_flow") or 0),
                                    rated_power=float(self._attr(feat, "pump_power") or 0))
                    elif device == "valve":
                        vtype_str = str(self._attr(feat, "valve_type") or "gate").upper()
                        vtype = getattr(ValveType, vtype_str, ValveType.GATE)
                        link = Valve(lid, from_node, to_node,
                                     valve_type=vtype,
                                     setting=10.0,
                                     diameter=diameter)
                    else:
                        link = Pipe(lid, from_node, to_node,
                                    pipe_type=pipe_type,
                                    diameter=diameter, length=seg_length,
                                    roughness=roughness)

                    net.add_link(link)

                    if pipe_type == "lateral" and device == "none":
                        es = float(self._attr(feat, "emitter_spacing") or 0)
                        if es <= 0 and net.field_info:
                            es = net.field_info.emitter_spacing
                        ek = self._attr(feat, "emitter_k") or None
                        ex = self._attr(feat, "emitter_x") or None
                        laterals.append({
                            "lid": lid,
                            "spacing": es if es > 0 else 0.3,
                            "k": float(ek) if ek is not None else None,
                            "x": float(ex) if ex is not None else None,
                        })

                # 拓扑回写
                for fid, segs in fid_to_segs.items():
                    if not segs:
                        continue
                    feat = segs[0]["feat"]
                    feat.setAttribute("from_node", segs[0]["from_node"] or "")
                    feat.setAttribute("to_node", segs[-1]["to_node"] or "")
                    pipe_layer.updateFeature(feat)
            finally:
                if need_edit:
                    pipe_layer.commitChanges()

        # 4. 毛管展开为 EmitterNode 滴头链（模拟出水的前提）
        #    INP 导出时跳过展开，保留原始管网结构
        if expand:
            for lat in laterals:
                try:
                    expand_lateral(net, lat["lid"], lat["spacing"],
                                   emitter_k=lat.get("k"),
                                   emitter_x=lat.get("x"))
                except Exception as e:
                    self.log(f"⚠️ 毛管 {lat['lid']} 展开失败: {e}")

        # expand 后补充缺失 link 的几何（毛管展开新增的滴头间短段是直线，
        # 用 from/to 节点坐标补全即可），保证每个 link 都有可视化几何
        for lid, link in net.links.items():
            if lid in link_geometry:
                continue
            a = net.get_node(link.from_node)
            b = net.get_node(link.to_node)
            if a is not None and b is not None:
                link_geometry[lid] = [(a.x, a.y), (b.x, b.y)]

        # 运行时挂到 net（不污染核心 Pipe 模型）
        net.link_geometry = link_geometry

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

    # ── 顶点切段（INP 导出用）──

    def _split_at_vertices(self, records: list) -> list:
        """INP 导出用：把每条管道在每个折线顶点处拆分为多段

        EPANET 只支持两点直线，QGIS 折线的每个顶点都需要一个 junction。
        每条折线 (v0,v1,...,vn) 拆为 n 段：(v0,v1), (v1,v2), ..., (v_{n-1},vn)。

        Returns:
            [{"record", "part", "pts"}]，part=0 为第一段（保留原 lid）
        """
        all_segments = []
        for rec in records:
            line = rec["line"]
            if len(line) < 2:
                continue
            for i in range(len(line) - 1):
                pts = [line[i], line[i + 1]]
                # 跳过零长度段
                if line[i].distance(line[i + 1]) < 1e-10:
                    continue
                all_segments.append({
                    "record": rec,
                    "part": i,
                    "pts": pts,
                })
        return all_segments

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
