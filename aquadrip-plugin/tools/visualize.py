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
from qgis.PyQt.QtWidgets import QApplication

# 压力单位转换：WNTR 输出 mH₂O → 显示用 MPa
M_H2O_TO_MPa = 0.00980665


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
            QApplication.translate("Visualize", "可视化: {0}  CU={1:.1f}%  DU={2:.1f}%").format(ts, cu, du),
            level=0, duration=5)

    def _create_node_layer(self, record: dict, crs_id: str,
                            mode: str) -> Optional[QgsVectorLayer]:
        """节点图层：压力 (MPa) / 滴头流量 (L/h) 着色"""
        node_pressure = record.get("node_pressure", {})
        emitter_flow = record.get("emitter_flow", {})
        node_coords = record.get("node_coords", {})

        layer = QgsVectorLayer(
            f"Point?crs={crs_id}", "results_nodes", "memory")
        dp = layer.dataProvider()
        dp.addAttributes([
            QgsField("node_id", QVariant.String),
            QgsField("pressure_mpa", QVariant.Double),
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
            feat.setAttribute("pressure_mpa", float(pressure) * M_H2O_TO_MPa)
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
        field_name = "emitter_flow" if mode == "emitter" else "pressure_mpa"
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
        for key, prefix in [("aqd_pipes", "L"), ("aqd_pumps", "PU"), ("aqd_valves", "V")]:
            ly = self._find_layer(key)
            if ly:
                for feat in ly.getFeatures():
                    lid = f"{prefix}{feat.id()}"
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
        """应用渐变渲染器（分位数分级，避免极端值导致颜色分布不均）

        Args:
            layer: 目标图层
            field_name: 分类字段
            scheme: "blue_red" 或 "green_red"
        """
        import math as _math

        # 收集所有值
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

        # 色带（7 级）
        if scheme == "blue_red":
            colors = [
                QColor(44, 123, 182),    # 蓝
                QColor(131, 190, 219),
                QColor(200, 225, 237),
                QColor(255, 255, 191),   # 黄
                QColor(254, 200, 123),
                QColor(252, 141, 58),
                QColor(215, 25, 28),     # 红
            ]
        else:
            colors = [
                QColor(26, 150, 65),     # 绿
                QColor(128, 191, 73),
                QColor(204, 227, 121),
                QColor(255, 255, 191),   # 黄
                QColor(254, 196, 79),
                QColor(252, 141, 58),
                QColor(215, 25, 28),     # 红
            ]

        # 分位数断点：排序后等分
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        k = len(colors)
        breaks = []
        for i in range(1, k):
            idx = int(n * i / k)
            if idx >= n:
                idx = n - 1
            breaks.append(sorted_vals[idx])
        # 确保断点单调递增（去重）
        unique_breaks = []
        prev = float('-inf')
        for b in breaks:
            if b > prev + 1e-12:
                unique_breaks.append(b)
                prev = b

        if not unique_breaks:
            return

        # 自适应标签精度
        span = max(values) - min(values)
        if span < 0.01:
            digits = 4
        elif span < 1:
            digits = 3
        elif span < 100:
            digits = 2
        else:
            digits = 1

        range_list = []
        lo = float('-inf')
        for i, hi in enumerate(unique_breaks):
            color = colors[i % len(colors)]
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            symbol.setColor(color)
            if layer.geometryType() == 0:
                symbol.setSize(3)
            else:
                symbol.setWidth(1.5)
            label = f"{lo:.{digits}f} - {hi:.{digits}f}" if lo != float('-inf') else f"< {hi:.{digits}f}"
            range_list.append(QgsRendererRange(lo, hi, symbol, label))
            lo = hi

        # 最后一档：> 最后一个断点
        color = colors[-1]
        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        symbol.setColor(color)
        if layer.geometryType() == 0:
            symbol.setSize(3)
        else:
            symbol.setWidth(1.5)
        label = f"> {unique_breaks[-1]:.{digits}f}"
        range_list.append(QgsRendererRange(unique_breaks[-1], float('inf'), symbol, label))

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
        from .layer_utils import find_layer
        return find_layer(QgsProject.instance(), keyword)
