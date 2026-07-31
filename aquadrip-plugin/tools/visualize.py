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

        layer = QgsVectorLayer(
            f"LineString?crs={crs_id}", "results_pipes", "memory")
        dp = layer.dataProvider()
        dp.addAttributes([
            QgsField("pipe_id", QVariant.String),
            QgsField("flow", QVariant.Double),
            QgsField("velocity", QVariant.Double),
        ])
        layer.updateFields()

        feats = []
        for lid, flow in link_flow.items():
            # 从 link ID 无法直接获取端点，需从 sync 的 DripNetwork
            # 但历史记录只有 node_coords，管道几何需从 aqd_pipes 复制
            # 这里先留空，由 _create_pipe_layer_from_qgis 补充几何
            pass

        # 管道几何从 aqd_pipes 图层复制（按 link_id 匹配）
        pipe_source = self._find_layer("aqd_pipes")
        if not pipe_source:
            return None

        link_geom_map = {}  # {link_id: geometry}
        for feat in pipe_source.getFeatures():
            # aqd_pipes 用 fid 标识（无 id 字段），sync 用 L{fid} 作为 link_id
            lid = f"L{feat.id()}"
            link_geom_map[lid] = feat.geometry()

        # planarize 产生的分段 ID（如 L1_p2）不在 aqd_pipes 中
        # 但它们的端点节点在 node_coords 中，可以重建几何
        for lid, flow in link_flow.items():
            geom = link_geom_map.get(lid)
            if geom and not geom.isEmpty():
                feat = QgsFeature(layer.fields())
                feat.setGeometry(geom)
            else:
                # 分段管道：找不到原始几何，从 from_node/to_node 重建
                # 但历史记录不存 from/to，跳过
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
            label = f"{lo:.2f} - {hi:.2f}"
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
