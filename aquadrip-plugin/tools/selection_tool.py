"""SelectionTool — 选择/查看管网元素"""

from qgis.core import QgsMapTool, QgsFeatureRequest, QgsGeometry
from qgis.gui import QgsMapTool, QgsMapMouseEvent, QgsRubberBand
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor


class SelectionTool(QgsMapTool):
    """选择工具 — 点击选择要素，查看属性"""

    def __init__(self, iface, layer_manager):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.layer_manager = layer_manager
        self.rb = QgsRubberBand(self.canvas)
        self.rb.setColor(QColor(231, 76, 60, 100))
        self.rb.setBorderColor(QColor(231, 76, 60))
        self.rb.setWidth(3)

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.PointingHandCursor)
        self.iface.messageBar().pushMessage(
            "aQuaDrip", "点击选择管网元素，右键清除选择", level=0, duration=3)

    def deactivate(self):
        self.rb.reset()
        super().deactivate()

    def canvasPressEvent(self, event: QgsMapMouseEvent):
        if event.button() == Qt.LeftButton:
            point = self.canvas.snapToCurrentLayer(event)
            self._select_at(point)
        elif event.button() == Qt.RightButton:
            self._clear_selection()

    def _select_at(self, point):
        """在点击位置查找并选择要素"""
        layers = self.layer_manager.get_all_layers() if self.layer_manager else {}
        
        best_feat = None
        best_dist = 20  # 像素容差
        
        for key, layer in layers.items():
            if not layer or not layer.isValid():
                continue
            # 转换到图层坐标
            for feat in layer.getFeatures():
                geom = feat.geometry()
                if geom is None:
                    continue
                dist = geom.distance(QgsGeometry.fromPointXY(point))
                if dist < best_dist:
                    best_dist = dist
                    best_feat = (layer, feat)
                    break  # 每层只取第一个
        
        if best_feat:
            layer, feat = best_feat
            layer.selectByIds([feat.id()])
            # 高亮
            self.rb.setToGeometry(feat.geometry())
            
            # 显示属性
            attrs = {field.name(): feat.attribute(field.name())
                     for field in layer.fields()}
            from qgis.PyQt.QtWidgets import QMessageBox
            info = "\n".join(f"{k}: {v}" for k, v in attrs.items() if v is not None)
            self.iface.messageBar().pushMessage(
                f"aQuaDrip - {layer.name()}",
                info[:200] if info else "(空)", level=0, duration=5)
        else:
            self._clear_selection()
            self.iface.messageBar().pushMessage(
                "aQuaDrip", "未选中任何要素", level=1, duration=2)

    def _clear_selection(self):
        """清除所有选择"""
        layers = self.layer_manager.get_all_layers() if self.layer_manager else {}
        for layer in layers.values():
            if layer and layer.isValid():
                layer.removeSelection()
        self.rb.reset()
