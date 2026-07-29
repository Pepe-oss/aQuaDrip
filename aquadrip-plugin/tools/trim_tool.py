"""TrimTool — 管道切割工具（支持毛管/支管/干管 + 切割长度）"""

from qgis.gui import QgsMapTool, QgsMapMouseEvent, QgsRubberBand
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsGeometry, QgsPointXY,
    QgsFeature, QgsWkbTypes, QgsFeatureRequest,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

import math


class TrimTool(QgsMapTool):
    """管道切割工具"""

    def __init__(self, iface, pipe_types=None, cut_length=0):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.pipe_types = pipe_types or ["lateral"]
        self.cut_length = cut_length
        self.rb = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rb.setStrokeColor(QColor(231, 76, 60))
        self.rb.setWidth(2)

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        type_names = {
            "mainline": "干管", "submain": "支管", "lateral": "毛管"
        }
        types_str = "/".join(type_names.get(t, t) for t in self.pipe_types)
        msg = f"点击{types_str}进行切割"
        if self.cut_length > 0:
            msg += f"（切除{self.cut_length:.2f}m）"
        self.iface.messageBar().pushMessage("aQuaDrip", msg, level=0, duration=5)

    def deactivate(self):
        self.rb.reset()
        super().deactivate()

    def canvasPressEvent(self, event: QgsMapMouseEvent):
        if event.button() == Qt.LeftButton:
            point = event.snapPoint()
            self._trim_pipe(point)
        elif event.button() == Qt.RightButton:
            self.deactivate()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.deactivate()

    def _find_pipe_layer(self):
        for layer in QgsProject.instance().mapLayers().values():
            s = layer.source() if hasattr(layer, 'source') else ""
            if "aqd_pipes" in s:
                return layer
        return None

    def _trim_pipe(self, point: QgsPointXY, tolerance=15):
        layer = self._find_pipe_layer()
        if not layer:
            self.iface.messageBar().pushWarning("aQuaDrip", "aqd_pipes 未找到")
            return

        # 1. 查找最近的管道
        best_feat = None
        best_dist = tolerance
        best_pos = 0.0  # 点击位置在管线上的比例(0~1)

        for feat in layer.getFeatures():
            ptype = str(feat.attribute("pipe_type") or "")
            if ptype not in self.pipe_types:
                continue
            geom = feat.geometry()
            if not geom:
                continue
            line = geom.asPolyline()
            if len(line) < 2:
                continue
            for i in range(len(line) - 1):
                seg = QgsGeometry.fromPolylineXY([line[i], line[i+1]])
                dist = seg.distance(QgsGeometry.fromPointXY(point))
                if dist < best_dist:
                    best_dist = dist
                    best_feat = feat
                    total_len = geom.length()
                    if total_len > 0:
                        cum = 0
                        for j in range(i):
                            cum += line[j].distance(line[j+1])
                        seg_len = line[i].distance(line[i+1])
                        if seg_len > 0:
                            ratio = min(max(line[i].distance(point) / seg_len, 0.01), 0.99)
                            cum += seg_len * ratio
                            best_pos = cum / total_len

        if not best_feat:
            self.iface.messageBar().pushWarning("aQuaDrip", "未选中有效管道")
            return

        # 2. 切割管道
        geom = best_feat.geometry()
        line = geom.asPolyline()
        total_len = geom.length()

        def split_at_ratio(ratio):
            """在指定比例处分割，返回分割点坐标"""
            target = total_len * ratio
            cum = 0
            for i in range(len(line) - 1):
                sl = line[i].distance(line[i+1])
                if cum + sl >= target:
                    remain = target - cum
                    r2 = remain / sl if sl > 0 else 0.5
                    r2 = max(0.01, min(0.99, r2))
                    x = line[i].x() + (line[i+1].x() - line[i].x()) * r2
                    y = line[i].y() + (line[i+1].y() - line[i].y()) * r2
                    return i, QgsPointXY(x, y)
                cum += sl
            return len(line) - 2, QgsPointXY(line[-1].x(), line[-1].y())

        if self.cut_length <= 0:
            # 模式1：仅分割（在点击位置断开）
            idx, split_pt = split_at_ratio(best_pos)
            line1 = line[:idx + 1] + [split_pt]
            line2 = [split_pt] + line[idx + 1:]
            segments = [line1, line2] if len(line1) >= 2 and len(line2) >= 2 else []
        else:
            # 模式2：切除一段
            half = self.cut_length / 2
            cut_start_ratio = max(0, best_pos * total_len - half) / total_len
            cut_end_ratio = min(total_len, best_pos * total_len + half) / total_len
            idx1, pt1 = split_at_ratio(cut_start_ratio)
            idx2, pt2 = split_at_ratio(cut_end_ratio)
            # 前半段：起点 → pt1
            seg1 = line[:idx1 + 1] + [pt1]
            # 后半段：pt2 → 终点
            seg2 = [pt2] + line[idx2 + 1:]
            segments = []
            if len(seg1) >= 2:
                segments.append(seg1)
            if len(seg2) >= 2:
                segments.append(seg2)

        if not segments:
            self.iface.messageBar().pushWarning("aQuaDrip", "分割后线段太短")
            return

        # 3. 写入
        layer.startEditing()
        for pts in segments:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPolylineXY(pts))
            # 复制旧属性（跳过不存在的字段）
            for field in layer.fields():
                fname = field.name()
                try:
                    f.setAttribute(fname, best_feat.attribute(fname))
                except:
                    pass
            layer.addFeature(f)
        layer.deleteFeature(best_feat.id())
        layer.commitChanges()
        layer.triggerRepaint()
        self.iface.messageBar().pushMessage(
            "aQuaDrip", f"管道已切割为{len(segments)}段", level=0, duration=3)
