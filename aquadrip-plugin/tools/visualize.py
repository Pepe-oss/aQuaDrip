"""Visualizer — 模拟结果可视化

从历史记录生成临时可视化图层：
- results_nodes（点）：节点压力 + 滴头流量，按压力渐变着色
- results_pipes（线）：管道流量 + 流速，按流量渐变着色
"""

from typing import Optional

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature,
    QgsGeometry, QgsPointXY,
    QgsGraduatedSymbolRenderer, QgsGradientColorRamp,
    QgsGradientStop, QgsSymbol, QgsRendererRange,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor


class Visualizer:
    """从历史记录生成可视化临时图层"""

    def __init__(self, iface):
        self.iface = iface

    def show_results(self, record: dict, mode: str = "pressure"):
        """生成 results_pipes + results_nodes 临时图层并渲染

        Args:
            record: 历史记录字典（来自 SimHistory.get）
            mode: 节点着色模式 "pressure"（压力）或 "emitter"（滴头流量）
        """
        project = QgsProject.instance()
        crs = project.crs()
        crs_id = crs.authid() if crs.isValid() else "EPSG:4326"

        # 删除旧 results 图层
        self._remove_old_layers(project)

        # 生成节点图层
        node_layer = self._create_node_layer(record, crs_id, mode)
        if node_layer:
            project.addMapLayer(node_layer)

        # 生成管道图层
        pipe_layer = self._create_pipe_layer(record, crs_id)
        if pipe_layer:
            project.addMapLayer(pipe_layer)

        ts = record.get("timestamp", "?")
        cu = record.get("cu", 0)
        du = record.get("du", 0)
        self.iface.messageBar().pushMessage(
            "aQuaDrip",
            f"可视化: {ts}  CU={cu:.1f}%  DU={du:.1f}%",
            level=0, duration=5)

    def _create_node_layer(self, record: dict, crs_id: str,
                            mode: str) -> Optional[QgsVectorLayer]:
        """节点图层：压力/滴头流量着色"""
        node_pressure = record.get("node_pressure", {})
        emitter_flow = record.get("emitter_flow", {})
        node_coords = record.get("node_coords", {})

        layer = QgsVectorLayer(
            f"Point?crs={crs_id}", "results_nodes", "memory")
        dp = layer.dataProvider()
        dp.addAttributes([
            QgsField("node_id", QVariant.String),
            QgsField("pressure", QVariant.Double),
            QgsField("emitter_flow", QVariant.Double),
        ])
        layer.updateFields()

        feats = []
        # 普通节点（有压力）
        for nid, pressure in node_pressure.items():
            coords = node_coords.get(nid)
            if not coords or len(coords) < 2:
                continue
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(
                QgsPointXY(float(coords[0]), float(coords[1]))))
            feat.setAttribute("node_id", nid)
            feat.setAttribute("pressure", float(pressure))
            # 如果该节点也是滴头，取滴头流量
            if nid in emitter_flow:
                feat.setAttribute("emitter_flow", float(emitter_flow[nid]))
            feats.append(feat)

        # 滴头节点（只有 emitter_flow，坐标在 node_coords）
        for eid, flow in emitter_flow.items():
            if eid in node_pressure:
                continue  # 已在上面处理
            coords = node_coords.get(eid)
            if not coords or len(coords) < 2:
                continue
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(
                QgsPointXY(float(coords[0]), float(coords[1]))))
            feat.setAttribute("node_id", eid)
            feat.setAttribute("emitter_flow", float(flow))
            feats.append(feat)

        if not feats:
            return None
        dp.addFeatures(feats)
        layer.updateExtents()

        # 着色
        field_name = "emitter_flow" if mode == "emitter" else "pressure"
        self._apply_graduated_renderer(layer, field_name, "blue_red")

        return layer

    def _create_pipe_layer(self, record: dict,
                            crs_id: str) -> Optional[QgsVectorLayer]:
        """管道图层：流量/流速着色"""
        link_flow = record.get("link_flow", {})
        link_velocity = record.get("link_velocity", {})
        node_coords = record.get("node_coords", {})
        link_endpoints = record.get("link_endpoints", {})
        link_geometry = record.get("link_geometry", {})

        layer = QgsVectorLayer(
            f"LineString?crs={crs_id}", "results_pipes", "memory")
        dp = layer.dataProvider()
        dp.addAttributes([
            QgsField("pipe_id", QVariant.String),
            QgsField("flow", QVariant.Double),
            QgsField("velocity", QVariant.Double),
        ])
        layer.updateFields()

        # 几何来源优先级（保留管道真实形状，含转弯折线）：
        #   1. link_geometry：sync 时记录的折线顶点（最完整，含转弯）
        #   2. 原始 link 图层（aqd_pipes/aqd_pumps/aqd_valves）：按 L{fid} 匹配
        #   3. link_endpoints + node_coords：仅两端点直线（兜底）
        link_geom_map = {}  # {link_id: geometry}
        for key in ("aqd_pipes", "aqd_pumps", "aqd_valves"):
            ly = self._find_layer(key)
            if ly:
                for feat in ly.getFeatures():
                    lid = f"L{feat.id()}"
                    link_geom_map[lid] = feat.geometry()

        feats = []
        for lid, flow in link_flow.items():
            feat = QgsFeature(layer.fields())
            geom_built = False
            # 1. 优先用折线顶点（含转弯），覆盖被切断的分段
            pts = link_geometry.get(lid)
            if pts and len(pts) >= 2:
                feat.setGeometry(QgsGeometry.fromPolylineXY([
                    QgsPointXY(float(p[0]), float(p[1])) for p in pts]))
                geom_built = True
            # 2. 原始图层几何（未切断的 L{fid}）
            if not geom_built:
                geom = link_geom_map.get(lid)
                if geom and not geom.isEmpty():
                    feat.setGeometry(geom)
                    geom_built = True
            # 3. 兜底：从端点节点画直线
            if not geom_built:
                endpoints = link_endpoints.get(lid)
                if not endpoints or len(endpoints) < 2:
                    continue
                from_c = node_coords.get(endpoints[0])
                to_c = node_coords.get(endpoints[1])
                if not from_c or not to_c or len(from_c) < 2 or len(to_c) < 2:
                    continue
                feat.setGeometry(QgsGeometry.fromPolylineXY([
                    QgsPointXY(float(from_c[0]), float(from_c[1])),
                    QgsPointXY(float(to_c[0]), float(to_c[1])),
                ]))
                geom_built = True
            if not geom_built:
                continue
            feat.setAttribute("pipe_id", lid)
            feat.setAttribute("flow", abs(float(flow)))
            if lid in link_velocity:
                feat.setAttribute("velocity", float(link_velocity[lid]))
            feats.append(feat)

        if not feats:
            return None
        dp.addFeatures(feats)
        layer.updateExtents()

        # 着色：流量渐变
        self._apply_graduated_renderer(layer, "flow", "green_red")

        return layer

    def _apply_graduated_renderer(self, layer: QgsVectorLayer,
                                   field_name: str, scheme: str):
        """应用渐变渲染器

        Args:
            layer: 目标图层
            field_name: 分类字段
            scheme: "blue_red" 或 "green_red"
        """
        # 计算分类
        values = []
        for feat in layer.getFeatures():
            val = feat.attribute(field_name)
            if val is not None:
                try:
                    values.append(float(val))
                except (TypeError, ValueError):
                    pass

        if not values:
            return

        min_val = min(values)
        max_val = max(values)
        if max_val - min_val < 1e-10:
            max_val = min_val + 1  # 避免除零

        # 色带
        if scheme == "blue_red":
            # 蓝（低）→ 黄 → 红（高）
            colors = [
                QColor(44, 123, 182),    # 蓝
                QColor(171, 217, 233),   # 浅蓝
                QColor(255, 255, 191),   # 黄
                QColor(253, 174, 97),    # 橙
                QColor(215, 25, 28),     # 红
            ]
        else:
            # 绿（低）→ 黄 → 红（高）
            colors = [
                QColor(26, 150, 65),     # 绿
                QColor(166, 217, 106),   # 浅绿
                QColor(255, 255, 191),   # 黄
                QColor(253, 174, 97),    # 橙
                QColor(215, 25, 28),     # 红
            ]

        intv = (max_val - min_val) / len(colors)
        # 自适应标签精度：范围窄时显示更多小数
        span = max_val - min_val
        if span < 0.01:
            digits = 4
        elif span < 1:
            digits = 3
        else:
            digits = 2
        range_list = []
        for i, color in enumerate(colors):
            lo = min_val + intv * i
            hi = max_val if i == len(colors) - 1 else min_val + intv * (i + 1)
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            symbol.setColor(color)
            if layer.geometryType() == 0:  # 点
                symbol.setSize(3)
            else:  # 线
                symbol.setWidth(1.5)
            label = f"{lo:.{digits}f} - {hi:.{digits}f}"
            range_list.append(QgsRendererRange(lo, hi, symbol, label))

        renderer = QgsGraduatedSymbolRenderer(field_name, range_list)
        layer.setRenderer(renderer)

    def _remove_old_layers(self, project: QgsProject):
        """删除旧的 results 图层"""
        to_remove = []
        for lid, layer in project.mapLayers().items():
            name = layer.name() if hasattr(layer, "name") else ""
            if name in ("results_nodes", "results_pipes"):
                to_remove.append(lid)
        for lid in to_remove:
            project.removeMapLayer(lid)

    def _find_layer(self, keyword: str) -> Optional[QgsVectorLayer]:
        """查找项目中的矢量图层（按 name 或 source）"""
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            s = layer.source() if hasattr(layer, "source") else ""
            if keyword in s or layer.name() == keyword:
                return layer
        return None
