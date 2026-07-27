"""DeleteTool — 删除选中的要素"""

from qgis.gui import QgsMapTool, QgsMapMouseEvent
from qgis.core import QgsGeometry
from qgis.PyQt.QtCore import Qt


class DeleteTool(QgsMapTool):
    """删除工具 — 点击要素从图层中删除"""

    def __init__(self, iface, layer_manager):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.layer_manager = layer_manager

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.ForbiddenCursor)
        self.iface.messageBar().pushMessage(
            "aQuaDrip", "点击要删除的管网要素", level=0, duration=5)

    def canvasPressEvent(self, event: QgsMapMouseEvent):
        if event.button() == Qt.LeftButton:
            point = event.snapPoint()
            self._delete_at(point)
        elif event.button() == Qt.RightButton:
            self._clear_selection()

    def _delete_at(self, point, tolerance=15):
        """删除点击位置的要素"""
        layers = self.layer_manager.get_all_layers() if self.layer_manager else {}

        best = None
        best_dist = tolerance

        for key, layer in layers.items():
            if not layer or not layer.isValid():
                continue
            for feat in layer.getFeatures():
                geom = feat.geometry()
                if geom is None:
                    continue
                dist = geom.distance(QgsGeometry.fromPointXY(point))
                if dist < best_dist:
                    best_dist = dist
                    best = (layer, feat)

        if best:
            layer, feat = best
            layer.selectByIds([feat.id()])
            from qgis.PyQt.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self.iface.mainWindow(),
                "确认删除",
                f"删除 {layer.name()} 中的要素 {feat.attribute('id')}？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                layer.dataProvider().deleteFeatures([feat.id()])
                layer.updateExtents()
                self.iface.messageBar().pushMessage(
                    "aQuaDrip", f"已删除 {layer.name()} 要素", level=0, duration=3)
            layer.removeSelection()
        else:
            self.iface.messageBar().pushMessage(
                "aQuaDrip", "未选中任何要素", level=1, duration=2)

    def _clear_selection(self):
        layers = self.layer_manager.get_all_layers() if self.layer_manager else {}
        for layer in layers.values():
            if layer and layer.isValid():
                layer.removeSelection()
