# -*- coding: utf-8 -*-
"""ManualLateralTool — 单根毛管手动放置工具(单击自动延伸)

适用场景:分析现有农田时,农民的毛管布置往往不规则
(间距不均、长短不一),批量自动生成无法复刻现状。
本工具让用户在田块内逐根点击放置:
每点击一次,就在点击位置沿田块行向生成一整根毛管
(与田块边界求交自动延伸/裁剪,凹形地块取最长段)。

毛管参数(滴头间距/k/x)来自田块字段——与自动生成同源,
保证手动/自动产物属性一致。

交互:
  左键  放置一根(可连续放置)
  移动  橡皮筋预览当前位置对应的毛管
  右键 / Esc  退出工具
"""

import math
from typing import Optional

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.gui import QgsMapTool, QgsMapMouseEvent, QgsRubberBand
from qgis.core import QgsWkbTypes, QgsGeometry


class ManualLateralTool(QgsMapTool):
    """单根毛管手动放置(单击自动延伸到田块边界)"""

    finished = pyqtSignal(int)  # 退出时发射已放置总数

    def __init__(self, iface, field_feat):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self._field_feat = field_feat
        self._generator = None       # LateralGenerator 延迟创建
        self._angle_rad = None       # 方向角(弧度),首次点击/移动时计算
        self._placed = 0

        # 预览橡皮筋(绿色半透明)
        self._rb = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self._rb.setStrokeColor(QColor(46, 204, 113))
        self._rb.setStrokeWidth(2)
        self._rb.setLineStyle(Qt.DashLine)

    # ── 生命周期 ──

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        from qgis.PyQt.QtWidgets import QApplication
        self.iface.messageBar().pushMessage(
            "aQuaDrip",
            QApplication.translate(
                "ManualLateralTool",
                "点击田块内位置放置毛管(方向沿田块行向,自动延伸到边界);"
                "右键或 Esc 退出").format(),
            level=0, duration=0)

    def deactivate(self):
        self._rb.reset()
        super().deactivate()

    def _finish(self):
        """退出工具并汇报总数"""
        self.canvas.unsetMapTool(self)
        self.finished.emit(self._placed)

    # ── 参数 ──

    def _field_geom(self):
        g = self._field_feat.geometry()
        return g if (g and not g.isEmpty()) else None

    def _direction_angle(self) -> Optional[float]:
        """毛管方向角(弧度):复用田块的 direction_type / row_direction"""
        from .lateral_generator import LateralGenerator
        feat = self._field_feat
        direction_type = str(feat.attribute("direction_type") or "long_edge")
        custom = float(feat.attribute("row_direction") or 0)
        geom = self._field_geom()
        if direction_type == "custom":
            # 自定义角不需要几何
            return math.radians(custom)
        if geom is None:
            return None
        # _calc_direction_angle 是实例方法(依赖 _get_polygon_ring)
        angle = LateralGenerator(self.iface)._calc_direction_angle(
            geom, direction_type, custom)
        return angle if angle is not None else 0.0

    # ── 交互 ──

    def canvasMoveEvent(self, event: QgsMapMouseEvent):
        geom = self._field_geom()
        if geom is None:
            return
        if self._angle_rad is None:
            self._angle_rad = self._direction_angle()
        from .lateral_generator import LateralGenerator
        pts = LateralGenerator.lateral_segment_at(
            event.mapPoint(), geom, self._angle_rad)
        if pts:
            self._rb.setToGeometry(QgsGeometry.fromPolylineXY(pts), None)
        else:
            self._rb.reset()

    def canvasPressEvent(self, event: QgsMapMouseEvent):
        if event.button() == Qt.LeftButton:
            self._place_at(event.mapPoint())
        elif event.button() == Qt.RightButton:
            self._finish()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._finish()

    def _place_at(self, point):
        """在点击位置放置一根毛管"""
        geom = self._field_geom()
        if geom is None:
            return
        if self._angle_rad is None:
            self._angle_rad = self._direction_angle()

        from .lateral_generator import LateralGenerator
        pts = LateralGenerator.lateral_segment_at(point, geom, self._angle_rad)
        if not pts:
            from qgis.PyQt.QtWidgets import QApplication
            self.iface.messageBar().pushWarning(
                "aQuaDrip",
                QApplication.translate(
                    "ManualLateralTool", "点击位置不在田块内,未放置"))
            return

        if self._generator is None:
            self._generator = LateralGenerator(self.iface)
        try:
            self._generator.write_manual_lateral(self._field_feat, pts)
            self._placed += 1
        except Exception as e:
            from qgis.PyQt.QtWidgets import QApplication
            self.iface.messageBar().pushWarning(
                "aQuaDrip",
                QApplication.translate(
                    "ManualLateralTool", "放置失败: {0}").format(e))
