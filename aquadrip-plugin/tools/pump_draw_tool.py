"""PumpDrawTool — 在地图上绘制水泵（作为 Link）"""

from qgis.gui import QgsMapTool, QgsMapMouseEvent, QgsRubberBand
from qgis.core import QgsPointXY, QgsGeometry, QgsFeature, QgsWkbTypes
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor


class PumpDrawTool(QgsMapTool):
    """水泵绘制工具 — 点击进水端→点击出水端"""

    def __init__(self, iface, layer_manager):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.layer_manager = layer_manager
        self.layer = None
        self.junction_layer = None
        self.start_point = None
        self.start_node_id = None

        self.rubber = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rubber.setStrokeColor(QColor(231, 76, 60))
        self.rubber.setWidth(3)

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        if self.layer_manager:
            self.layer = self.layer_manager.get_layer("pump")
            self.junction_layer = self.layer_manager.get_layer("junction")
        self.iface.messageBar().pushMessage(
            "aQuaDrip", "点击进水端节点 → 点击出水端节点绘制水泵", level=0, duration=5)

    def deactivate(self):
        self._reset()
        super().deactivate()

    def canvasPressEvent(self, event: QgsMapMouseEvent):
        if event.button() == Qt.LeftButton:
            point = event.snapPoint()
            if self.start_point is None:
                self.start_point = point
                self.start_node_id = self._find_or_create_node(point)
                self.rubber.addPoint(point)
            else:
                end_node_id = self._find_or_create_node(point)
                self._finish_pump(point, end_node_id)
                self._reset()
        elif event.button() == Qt.RightButton:
            self._reset()

    def canvasMoveEvent(self, event: QgsMapMouseEvent):
        if self.start_point is not None:
            point = event.snapPoint()
            self.rubber.reset(QgsWkbTypes.LineGeometry)
            self.rubber.addPoint(self.start_point)
            self.rubber.addPoint(point)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._reset()

    def _find_or_create_node(self, point, tolerance=15):
        """查找附近节点，未找到则创建"""
        if self.junction_layer and self.junction_layer.isValid():
            for feat in self.junction_layer.getFeatures():
                dist = feat.geometry().distance(QgsGeometry.fromPointXY(point))
                if dist < tolerance:
                    return feat.attribute("id")
        # 创建新节点（即使 junction_layer 无效也生成 ID）
        import random, time
        nid = f"N{random.randint(1000, 9999)}{int(time.time())%100}"
        if self.junction_layer and self.junction_layer.isValid():
            feat = QgsFeature(self.junction_layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(point))
            feat.setAttribute("id", nid)
            self.junction_layer.dataProvider().addFeatures([feat])
            self.junction_layer.updateExtents()
        return nid

    def _finish_pump(self, end_point, end_node_id):
        if not self.layer or not self.layer.isValid():
            self.iface.messageBar().pushWarning("aQuaDrip", "水泵图层无效")
            return
        import random
        try:
            feat = QgsFeature(self.layer.fields())
            line = QgsGeometry.fromPolylineXY([self.start_point, end_point])
            if line.isNull():
                self.iface.messageBar().pushWarning("aQuaDrip", "几何无效")
                return
            feat.setGeometry(line)
            pid = f"PU{random.randint(100, 999)}"
            feat.setAttribute("id", pid)
            feat.setAttribute("head", 30)
            feat.setAttribute("flow", 15)
            feat.setAttribute("power", 5.5)
            
            added = self.layer.dataProvider().addFeatures([feat])
            if not added:
                self.iface.messageBar().pushWarning("aQuaDrip", "添加要素失败")
                return
            
            self.layer.updateExtents()
            self.layer.triggerRepaint()
            self.canvas.setExtent(self.layer.extent())
            self.canvas.refresh()
            self.iface.messageBar().pushMessage(
                "aQuaDrip", f"水泵 {pid} 已绘制 (图层要素数: {self.layer.featureCount()})", level=0, duration=3)
        except Exception as e:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", f"绘制失败: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    def _reset(self):
        self.start_point = None
        self.start_node_id = None
        self.rubber.reset(QgsWkbTypes.LineGeometry)
