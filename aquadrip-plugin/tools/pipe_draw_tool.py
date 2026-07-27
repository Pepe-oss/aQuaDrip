"""PipeDrawTool — 在地图上绘制管道（干管/支管/毛管）"""

from qgis.gui import QgsMapTool, QgsMapMouseEvent, QgsMapCanvasSnappingUtils, QgsRubberBand
from qgis.core import (
    QgsPointXY, QgsGeometry, QgsFeature,
    QgsProject, QgsWkbTypes, QgsSnappingConfig,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor


class PipeDrawTool(QgsMapTool):
    """管道绘制工具 — 点击起点→点击终点（自动连接最近的节点）"""

    def __init__(self, iface, layer_manager, pipe_type="mainline"):
        """
        Args:
            pipe_type: mainline / submain / lateral
        """
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.layer_manager = layer_manager
        self.pipe_type = pipe_type
        self.layer = None
        self.junction_layer = None

        # 颜色
        colors = {
            "mainline": ("#1a5276", "#1a5276"),
            "submain": ("#2e86c1", "#2e86c1"),
            "lateral": ("#85c1e9", "#85c1e9"),
        }
        fill, border = colors.get(pipe_type, ("#666", "#666"))

        self.rubber = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rubber.setColor(QColor(border))
        self.rubber.setWidth({
            "mainline": 3, "submain": 2, "lateral": 1
        }.get(pipe_type, 2))

        self.start_point = None
        self.start_node = None

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        if self.layer_manager:
            self.layer = self.layer_manager.get_layer(self.pipe_type)
            self.junction_layer = self.layer_manager.get_layer("junction")
        msg = {
            "mainline": "点击起点→点击终点绘制干管",
            "submain": "点击起点→点击终点绘制支管",
            "lateral": "点击起点→点击终点绘制毛管",
        }.get(self.pipe_type, "绘制管道")
        self.iface.messageBar().pushMessage("aQuaDrip", msg, level=0, duration=5)

    def deactivate(self):
        self._reset()
        super().deactivate()

    def canvasPressEvent(self, event: QgsMapMouseEvent):
        if event.button() == Qt.LeftButton:
            point = self.canvas.snapToCurrentLayer(event)
            
            if self.start_point is None:
                # 第一个点：尝试捕捉已有节点
                self.start_point = point
                self.start_node = self._snap_to_nearest_junction(point)
                self.rubber.addPoint(point)
            else:
                # 第二个点：完成管道
                end_point = point
                end_node = self._snap_to_nearest_junction(end_point)
                self._finish_pipe(self.start_point, end_point, self.start_node, end_node)
                self._reset()
        elif event.button() == Qt.RightButton:
            self._reset()

    def canvasMoveEvent(self, event: QgsMapMouseEvent):
        if self.start_point is not None:
            point = self.canvas.snapToCurrentLayer(event)
            self.rubber.reset(QgsWkbTypes.LineGeometry)
            self.rubber.addPoint(self.start_point)
            self.rubber.addPoint(point)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._reset()

    # ---- 内部 ----

    def _snap_to_nearest_junction(self, point, tolerance=10):
        """捕捉最近的节点"""
        if not self.junction_layer or not self.junction_layer.isValid():
            return None
        
        nearest = None
        min_dist = tolerance
        
        for feat in self.junction_layer.getFeatures():
            geom = feat.geometry()
            dist = geom.distance(QgsGeometry.fromPointXY(point))
            if dist < min_dist:
                min_dist = dist
                nearest = feat
        
        return nearest

    def _finish_pipe(self, start_pt, end_pt, start_node=None, end_node=None):
        """完成管道并写入图层"""
        if not self.layer or not self.layer.isValid():
            return
        
        # 确定起止节点ID
        from_id = start_node["id"] if start_node else self._create_junction(start_pt)
        to_id = end_node["id"] if end_node else self._create_junction(end_pt)
        
        if from_id == to_id:
            self.iface.messageBar().pushWarning("aQuaDrip", "起点和终点相同")
            return
        
        # 写入管道
        line = QgsGeometry.fromPolylineXY([start_pt, end_pt])
        feat = QgsFeature(self.layer.fields())
        feat.setGeometry(line)
        
        import random
        feat.setAttribute("id", f"{self.pipe_type[0].upper()}{random.randint(100,999)}")
        feat.setAttribute("diameter", {
            "mainline": 63, "submain": 40, "lateral": 16
        }.get(self.pipe_type, 20))
        feat.setAttribute("length", line.length())
        
        self.layer.dataProvider().addFeatures([feat])
        self.layer.updateExtents()

    def _create_junction(self, point):
        """在指定位置创建节点"""
        if not self.junction_layer:
            return None
        
        import random
        nid = f"N{random.randint(1000,9999)}"
        
        feat = QgsFeature(self.junction_layer.fields())
        feat.setGeometry(QgsGeometry.fromPointXY(point))
        feat.setAttribute("id", nid)
        self.junction_layer.dataProvider().addFeatures([feat])
        self.junction_layer.updateExtents()
        return nid

    def _reset(self):
        self.start_point = None
        self.start_node = None
        self.rubber.reset(QgsWkbTypes.LineGeometry)
