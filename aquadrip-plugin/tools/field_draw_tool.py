"""FieldDrawTool — 在地图上绘制农田多边形"""

from qgis.gui import QgsMapTool, QgsMapMouseEvent, QgsRubberBand
from qgis.core import (
    QgsPointXY, QgsGeometry, QgsFeature,
    QgsProject, QgsWkbTypes,
)
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
        self.rubber.setStrokeColor(QColor(39, 174, 96))
        self.rubber.setWidth(2)

        self.points = []  # 已点击的点
        self.is_drawing = False
        self.temp_rubber = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.temp_rubber.setColor(QColor(39, 174, 96, 80))
        self.temp_rubber.setStrokeColor(QColor(39, 174, 96))
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
            point = event.snapPoint()
            self.points.append(point)
            self.is_drawing = True
            self._update_rubber()
        elif event.button() == Qt.RightButton:
            # 右键完成绘制
            if len(self.points) >= 3:
                self._finish_polygon()
            else:
                self._reset()

    def canvasMoveEvent(self, event: QgsMapMouseEvent):
        """鼠标移动事件（实时预览最后一段线或面）"""
        if self.is_drawing and len(self.points) > 0:
            point = event.snapPoint()
            n = len(self.points)
            if n < 3:
                # 点少于3个时，显示从最后点到鼠标的线段
                self.temp_rubber.reset(QgsWkbTypes.LineGeometry)
                self.temp_rubber.addPoint(self.points[-1])
                self.temp_rubber.addPoint(point)
            else:
                # 3个点以上，实时更新多边形预览
                self.temp_rubber.reset(QgsWkbTypes.PolygonGeometry)
                all_pts = self.points + [point]
                poly = QgsGeometry.fromPolygonXY([all_pts])
                self.temp_rubber.setToGeometry(poly)

    def canvasDoubleClickEvent(self, event):
        """双击完成绘制"""
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

    def _update_rubber(self):
        """更新多边形预览"""
        n = len(self.points)
        if n < 2:
            return
        if n == 2:
            # 2个点：显示线段
            self.rubber.reset(QgsWkbTypes.LineGeometry)
            self.rubber.addPoint(self.points[0])
            self.rubber.addPoint(self.points[1])
        else:
            # 3+个点：显示多边形
            self.rubber.reset(QgsWkbTypes.PolygonGeometry)
            polygon = QgsGeometry.fromPolygonXY([self.points])
            self.rubber.setToGeometry(polygon)

    def _finish_polygon(self):
        """完成多边形并写入图层"""
        if len(self.points) < 3:
            return

        polygon = QgsGeometry.fromPolygonXY([self.points])
        if not polygon.isGeosValid():
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "多边形无效，请重新绘制")
            return

        # 计算面积（考虑 CRS 和椭球）
        from qgis.core import QgsDistanceArea, QgsProject
        da = QgsDistanceArea()
        try:
            project = QgsProject.instance()
            da.setSourceCrs(project.crs(), project.transformContext())
            ellipsoid = project.ellipsoid()
            if ellipsoid and ellipsoid != "NONE":
                da.setEllipsoid(ellipsoid)
                area_sqm = da.measureArea(polygon)
            else:
                area_sqm = polygon.area()
        except:
            area_sqm = polygon.area()
        
        if area_sqm is None or area_sqm != area_sqm:
            area_sqm = polygon.area()
        
        area_hectare = area_sqm / 10000
        area_mu = area_sqm / 666.667

        # 写入图层
        if self.layer and self.layer.isValid():
            # 删除虚拟要素（如果有）
            ids_to_delete = []
            for feat in self.layer.getFeatures():
                ids_to_delete.append(feat.id())
            if ids_to_delete:
                self.layer.dataProvider().deleteFeatures(ids_to_delete)
            
            # 添加真实农田
            feat = QgsFeature(self.layer.fields())
            feat.setGeometry(polygon)
            self.layer.dataProvider().addFeatures([feat])
            self.layer.updateExtents()
            
            # 更新画布视图
            canvas = self.iface.mapCanvas()
            canvas.setExtent(self.layer.extent())
            canvas.refresh()
            
            self.iface.messageBar().pushMessage(
                "aQuaDrip",
                f"农田已绘制（{area_sqm:.0f} m² ≈ {area_mu:.1f} 亩）",
                level=0, duration=3)
        else:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "农田图层无效")

        self._reset()

    def _reset(self):
        """重置绘制状态"""
        self.points.clear()
        self.is_drawing = False
        self.rubber.reset(QgsWkbTypes.PolygonGeometry)
        self.temp_rubber.reset(QgsWkbTypes.LineGeometry)
