"""FieldDrawTool — 在地图上绘制农田多边形"""

from qgis.core import (
    QgsMapTool, QgsPointXY, QgsGeometry, QgsFeature,
    QgsProject, QgsRubberBand, QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsMapMouseEvent
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QPolygonF


class FieldDrawTool(QgsMapTool):
    """农田绘制工具 — 点击绘制多边形"""

    def __init__(self, iface, layer_manager):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.layer_manager = layer_manager
        self.layer = None  # 农田图层

        # 橡皮筋预览
        self.rubber = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self.rubber.setColor(QColor(39, 174, 96, 80))
        self.rubber.setBorderColor(QColor(39, 174, 96))
        self.rubber.setWidth(2)

        self.points = []  # 已点击的点
        self.is_drawing = False
        self.temp_rubber = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.temp_rubber.setColor(QColor(39, 174, 96))
        self.temp_rubber.setWidth(2)

    def activate(self):
        """激活工具"""
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        if self.layer_manager:
            self.layer = self.layer_manager.get_layer("field")
        else:
            self.layer = None
        self.iface.messageBar().pushMessage(
            "aQuaDrip", "点击地图绘制农田多边形，右键/回车完成", level=0, duration=5)

    def deactivate(self):
        """停用工具"""
        self._reset()
        super().deactivate()

    def canvasPressEvent(self, event: QgsMapMouseEvent):
        """鼠标点击事件"""
        if event.button() == Qt.LeftButton:
            point = self._to_map_coords(event)
            self.points.append(point)
            self.is_drawing = True
            self._update_rubber()
        elif event.button() == Qt.RightButton:
            if len(self.points) >= 3:
                self._finish_polygon()
            else:
                self._reset()

    def canvasMoveEvent(self, event: QgsMapMouseEvent):
        """鼠标移动事件（实时预览最后一段线）"""
        if self.is_drawing and len(self.points) > 0:
            point = self._to_map_coords(event)
            self.temp_rubber.reset(QgsWkbTypes.LineGeometry)
            # 画从最后一个点到鼠标位置的线
            last = self.points[-1]
            self.temp_rubber.addPoint(last)
            self.temp_rubber.addPoint(point)

    def canvasDoubleClickEvent(self, event):
        """双击完成绘制"""
        self.canvasMoveEvent(event)  # 先更新最后一点
        if len(self.points) >= 3:
            self._finish_polygon()

    def keyPressEvent(self, event):
        """回车完成，ESC 取消"""
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if len(self.points) >= 3:
                self._finish_polygon()
        elif event.key() == Qt.Key_Escape:
            self._reset()

    # ---- 内部方法 ----

    def _to_map_coords(self, event):
        """事件坐标转地图坐标"""
        return self.canvas.snapToCurrentLayer(event)

    def _update_rubber(self):
        """更新多边形预览"""
        self.rubber.reset(QgsWkbTypes.PolygonGeometry)
        if len(self.points) >= 3:
            polygon = QgsGeometry.fromPolygonXY([self.points])
            self.rubber.setToGeometry(polygon)
        else:
            self.rubber.reset(QgsWkbTypes.PolygonGeometry)

    def _finish_polygon(self):
        """完成多边形并写入图层"""
        if len(self.points) < 3:
            return

        polygon = QgsGeometry.fromPolygonXY([self.points])
        if not polygon.isGeosValid():
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "多边形无效，请重新绘制")
            return

        # 写入图层
        if self.layer and self.layer.isValid():
            if self.layer.featureCount() > 1:
                # 如果有虚拟要素，先清理
                self.layer_manager.clear_dummy_features()
                self.layer.startEditing()
                for feat in self.layer.getFeatures():
                    self.layer.deleteFeature(feat.id())
            
            feat = QgsFeature(self.layer.fields())
            feat.setGeometry(polygon)
            self.layer.dataProvider().addFeatures([feat])
            self.layer.updateExtents()
            self.iface.mapCanvas().zoomToFeatureExtent(self.layer)

        self.iface.messageBar().pushMessage(
            "aQuaDrip", f"农田已绘制（面积约 {polygon.area():.0f} m²）", level=0, duration=3)

        # 触发状态变迁（如果有事件总线）
        self._reset()

    def _reset(self):
        """重置绘制状态"""
        self.points.clear()
        self.is_drawing = False
        self.rubber.reset(QgsWkbTypes.PolygonGeometry)
        self.temp_rubber.reset(QgsWkbTypes.LineGeometry)
