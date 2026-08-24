"""EdgeSelectTool — 点击田块边确定滴灌带方向"""

import math
from qgis.gui import QgsMapTool, QgsMapMouseEvent, QgsRubberBand
from qgis.core import QgsWkbTypes, QgsGeometry, QgsPointXY, QgsProject
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QApplication


class EdgeSelectTool(QgsMapTool):
    """边选择工具 — 点击田块多边形的一条边，计算方向角度"""

    angle_selected = pyqtSignal(float)  # 选择完成后发射角度信号

    def __init__(self, iface):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.rb = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rb.setStrokeColor(QColor(231, 76, 60))
        self.rb.setWidth(3)

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        self.iface.messageBar().pushMessage(
            "aQuaDrip", QApplication.translate("EdgeSelectTool", "点击田块的一条边确定滴灌带方向"), level=0, duration=0)

    def deactivate(self):
        self.rb.reset()
        super().deactivate()

    def canvasPressEvent(self, event: QgsMapMouseEvent):
        if event.button() == Qt.LeftButton:
            point = event.snapPoint()
            angle = self._find_edge_angle(point)
            if angle is not None:
                self.rb.reset()
                self.angle_selected.emit(angle)
                self.iface.messageBar().pushMessage(
                    "aQuaDrip", QApplication.translate("EdgeSelectTool", "方向已选择: {0:.1f}°").format(angle), level=0, duration=3)
            else:
                self.iface.messageBar().pushWarning(
                    "aQuaDrip", QApplication.translate("EdgeSelectTool", "未选中有效边，请点击田块边界附近"))
        elif event.button() == Qt.RightButton:
            self._cancel()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._cancel()

    def _find_edge_angle(self, point: QgsPointXY, tolerance=20) -> float:
        """点击位置最近的田块边界线段的方位角"""
        field_layer = self._find_field_layer()
        if not field_layer:
            return None

        best_dist = tolerance
        best_angle = None

        for feat in field_layer.getFeatures():
            geom = feat.geometry()
            ring = None
            if geom and not geom.isEmpty() and geom.isMultipart():
                polygon = geom.asMultiPolygon()
                if polygon and polygon[0]:
                    ring = polygon[0][0]  # 外环
            elif geom and not geom.isEmpty():
                polygon = geom.asPolygon()
                if polygon:
                    ring = polygon[0]
            # 几何为空/无环时跳过该要素——否则 ring 未定义
            # 会 NameError（或沿用上一要素的边界）
            if not ring or len(ring) < 2:
                continue

            for i in range(len(ring) - 1):
                p1 = ring[i]
                p2 = ring[i + 1]
                seg = QgsGeometry.fromPolylineXY([p1, p2])
                dist = seg.distance(QgsGeometry.fromPointXY(point))
                if dist < best_dist:
                    best_dist = dist
                    # 计算线段方位角（度, 0=东, 逆时针）
                    dx = p2.x() - p1.x()
                    dy = p2.y() - p1.y()
                    angle = math.degrees(math.atan2(dy, dx))
                    # 归一化到 0~180°（滴灌带方向无正反）
                    angle = angle % 180
                    best_angle = angle

        return best_angle

    def _cancel(self):
        self.rb.reset()
        self.iface.messageBar().pushMessage(
            "aQuaDrip", QApplication.translate("EdgeSelectTool", "已取消边选择"), level=0, duration=2)
        self.canvas.unsetMapTool(self)

    def _find_field_layer(self):
        from .layer_utils import find_layer
        return find_layer(QgsProject.instance(), "aqd_fields")
