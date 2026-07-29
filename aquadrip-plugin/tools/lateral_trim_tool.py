"""LateralTrimTool — 点击毛管任意位置将其分割为两段"""

from qgis.gui import QgsMapTool, QgsMapMouseEvent, QgsRubberBand
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsGeometry, QgsPointXY,
    QgsFeature, QgsWkbTypes, QgsFeatureRequest,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor


class LateralTrimTool(QgsMapTool):
    """毛管切割工具 — 点击毛管在点击处分割为两段"""

    def __init__(self, iface):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.rb = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rb.setStrokeColor(QColor(231, 76, 60))
        self.rb.setWidth(2)

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        self.iface.messageBar().pushMessage(
            "aQuaDrip", "点击毛管上的任意位置将其分割为两段", level=0, duration=5)

    def deactivate(self):
        self.rb.reset()
        super().deactivate()

    def canvasPressEvent(self, event: QgsMapMouseEvent):
        if event.button() == Qt.LeftButton:
            point = event.snapPoint()
            self._trim_lateral(point)
        elif event.button() == Qt.RightButton:
            self.deactivate()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.deactivate()

    def _find_lateral_layer(self):
        """查找 aqd_pipes 图层"""
        for layer in QgsProject.instance().mapLayers().values():
            s = layer.source() if hasattr(layer, 'source') else ""
            if "aqd_pipes" in s:
                return layer
        return None

    def _trim_lateral(self, point: QgsPointXY, tolerance=15):
        """在点击位置分割毛管"""
        layer = self._find_lateral_layer()
        if not layer:
            self.iface.messageBar().pushWarning("aQuaDrip", "aqd_pipes 图层未找到")
            return

        # 找到最近的 lateral 管道
        best_feat = None
        best_dist = tolerance
        best_pos = None  # 分割位置（在线的比例 0~1）

        for feat in layer.getFeatures():
            # 只处理毛管
            if str(feat.attribute("pipe_type") or "") != "lateral":
                continue
            geom = feat.geometry()
            if not geom:
                continue
            line = geom.asPolyline()
            if len(line) < 2:
                continue

            # 找到线上离点击点最近的线段
            for i in range(len(line) - 1):
                p1, p2 = line[i], line[i+1]
                seg = QgsGeometry.fromPolylineXY([p1, p2])
                dist = seg.distance(QgsGeometry.fromPointXY(point))
                if dist < best_dist:
                    best_dist = dist
                    best_feat = feat
                    # 计算分割点在毛管上的比例
                    total_len = geom.length()
                    if total_len > 0:
                        # 计算到该段起点的累积距离
                        cum_dist = 0
                        for j in range(i):
                            cum_dist += line[j].distance(line[j+1])
                        # 加上这段内点击位置的比例
                        seg_len = p1.distance(p2)
                        if seg_len > 0:
                            # 点击点到 p1 的距离
                            click_dist = p1.distance(point)
                            ratio = min(max(click_dist / seg_len, 0.01), 0.99)
                            cum_dist += seg_len * ratio
                            best_pos = cum_dist / total_len

        if not best_feat or best_pos is None:
            self.iface.messageBar().pushWarning("aQuaDrip", "未选中有效的毛管")
            return

        # 分割毛管
        geom = best_feat.geometry()
        full_line = geom.asPolyline()

        # 找到分割点位置
        split_idx = -1
        cum_len = 0
        total_len = geom.length()
        target_len = total_len * best_pos

        for i in range(len(full_line) - 1):
            seg_len = full_line[i].distance(full_line[i+1])
            if cum_len + seg_len >= target_len:
                split_idx = i
                break
            cum_len += seg_len

        if split_idx < 0:
            return

        # 计算分割点在最后一段上的确切位置
        p1, p2 = full_line[split_idx], full_line[split_idx + 1]
        seg_len = p1.distance(p2)
        remaining = target_len - cum_len
        ratio = max(0.01, min(0.99, remaining / seg_len)) if seg_len > 0 else 0.5
        split_pt = QgsPointXY(
            p1.x() + (p2.x() - p1.x()) * ratio,
            p1.y() + (p2.y() - p1.y()) * ratio,
        )

        # 创建两条新毛管
        line1_pts = full_line[:split_idx + 1] + [split_pt]
        line2_pts = [split_pt] + full_line[split_idx + 1:]

        if len(line1_pts) < 2 or len(line2_pts) < 2:
            self.iface.messageBar().pushWarning("aQuaDrip", "分割后线段太短")
            return

        # 写入图层
        layer.startEditing()
        old_id = best_feat.attribute("id") or ""
        old_attrs = {f.name(): best_feat.attribute(f.name()) for f in layer.fields()}

        for pts, suffix in [(line1_pts, "a"), (line2_pts, "b")]:
            new_feat = QgsFeature(layer.fields())
            new_feat.setGeometry(QgsGeometry.fromPolylineXY(pts))
            for k, v in old_attrs.items():
                new_feat.setAttribute(k, v)
            new_feat.setAttribute("id", f"{old_id}_{suffix}" if old_id else "")
            layer.addFeature(new_feat)

        # 删除旧毛管
        layer.deleteFeature(best_feat.id())
        layer.commitChanges()
        layer.triggerRepaint()

        self.iface.messageBar().pushMessage(
            "aQuaDrip", f"毛管已分割为两段", level=0, duration=3)
