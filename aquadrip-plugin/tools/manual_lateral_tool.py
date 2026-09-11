# -*- coding: utf-8 -*-
"""ManualLateralTool — 单根毛管手动放置工具(单击自动延伸)

适用场景:分析现有农田时,农民的毛管布置往往不规则
(间距不均、长短不一),批量自动生成无法复刻现状。
本工具让用户在田块内逐根点击放置:
每点击一次,就在点击位置沿田块行向生成一整根毛管
(与田块边界求交自动延伸/裁剪)。断续田块(一行穿过多个
不相邻区段)时:整行各区段细线提示,**只放置点击所在段**,
各区段由用户分别点击、分开放置。

毛管参数(滴头间距/k/x)来自田块字段——与自动生成同源,
保证手动/自动产物属性一致。

交互:
  左键  放置一根(可连续放置;断续行放点击所在段)
  移动  橡皮筋预览:整行全部区段(细线)+ 将放置段(粗绿虚线)
  右键 / Esc  退出工具
"""

import math
from typing import Optional

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.gui import QgsMapTool, QgsMapMouseEvent, QgsRubberBand
from qgis.core import QgsWkbTypes, QgsGeometry, QgsPointXY

# 构建标记:激活提示中显示,用于确认运行的代码版本
# (拷贝更新插件文件后必须重启 QGIS/重载插件,旧模块仍在内存)
BUILD_TAG = "b20260911.1"


class ManualLateralTool(QgsMapTool):
    """单根毛管手动放置(单击自动延伸到田块边界)"""

    finished = pyqtSignal(int)  # 退出时发射已放置总数

    def __init__(self, iface, field_feat, field_layer=None):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self._field_feat = field_feat
        self._field_layer = field_layer   # 用于 CRS 变换(画布↔图层)
        self._generator = None       # LateralGenerator 延迟创建
        self._angle_rad = None       # 方向角(弧度),首次点击/移动时计算
        self._placed = 0
        self._work_geom_cache = None  # 工作几何(惰性):无效几何 makeValid 修正
        self._warned_fixed = False   # 修正提示只弹一次

        # 目标段预览(绿色粗虚线):点击将放置的那一段
        self._rb = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self._rb.setColor(QColor(46, 204, 113, 200))
        self._rb.setWidth(2)
        self._rb.setLineStyle(Qt.DashLine)
        # 整行预览(白色细半透明):断续行显示全部区段,提示还有哪些段可放
        self._rb_row = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self._rb_row.setColor(QColor(255, 255, 255, 90))
        self._rb_row.setWidth(1)

    # ── 生命周期 ──

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        from qgis.PyQt.QtWidgets import QApplication
        print(f"[aQuaDrip] ManualLateralTool {BUILD_TAG} activated "
              f"from {__file__}")
        self.iface.messageBar().pushMessage(
            "aQuaDrip",
            QApplication.translate(
                "ManualLateralTool",
                "点击田块内位置放置毛管(方向沿田块行向,自动延伸到边界);"
                "右键或 Esc 退出").format() + f"  [{BUILD_TAG}]",
            level=0, duration=0)

    def deactivate(self):
        self._rb.reset()
        self._rb_row.reset()
        super().deactivate()

    def _finish(self):
        """退出工具并汇报总数"""
        self.canvas.unsetMapTool(self)
        self.finished.emit(self._placed)

    # ── 参数 ──

    def _work_geom(self):
        """田块工作几何(惰性缓存):GEOS 无效时 makeValid 修正

        手绘不规则田块常有自相交/环自触碰/重复点等无效几何,
        GEOS 求交直接拓扑失败 → 预览/放置全部失效。修正一次
        缓存复用,避免每次鼠标移动都做 makeValid。
        """
        if self._work_geom_cache is not None:
            return self._work_geom_cache if not self._work_geom_cache.isEmpty() else None
        g = self._field_feat.geometry()
        if g is None or g.isEmpty():
            self._work_geom_cache = QgsGeometry()
            return None
        if g.isGeosValid():
            self._work_geom_cache = g
        else:
            fixed = g.makeValid()
            if fixed is not None and not fixed.isEmpty():
                self._work_geom_cache = fixed
                if not self._warned_fixed:
                    self._warned_fixed = True
                    from qgis.PyQt.QtWidgets import QApplication
                    self.iface.messageBar().pushMessage(
                        "aQuaDrip",
                        QApplication.translate(
                            "ManualLateralTool",
                            "田块几何不规则(自相交等),已自动修正用于毛管放置"),
                        level=1, duration=6)
            else:
                self._work_geom_cache = g
        return self._work_geom_cache

    def _layer_crs(self):
        return self._field_layer.crs() if self._field_layer else None

    def _min_len(self):
        """碎屑段过滤阈值:0.5 m 换算到图层单位

        经纬度图层 QgsGeometry.length() 返回度(1° ≈ 111320 m);
        CRS 无效时返回 0 不过滤——绝不能因阈值单位错误把整行误杀。
        """
        crs = self._layer_crs()
        if crs is None or not crs.isValid():
            return 0.0
        if crs.isGeographic():
            return 0.5 / 111320.0
        return 0.5

    def _pick_segment(self, segments, point):
        """断续行选段:取距点击最近的区段(即点击所在段)

        点击在田块内时必然落在某个区段上(距离≈0);
        点击在缺口/田块外时由调用方先行判定。
        """
        pt_geom = QgsGeometry.fromPointXY(point)
        best, best_d = None, None
        for seg in segments:
            d = QgsGeometry.fromPolylineXY(seg).distance(pt_geom)
            if best_d is None or d < best_d:
                best, best_d = seg, d
        return best

    def _to_layer_point(self, map_point):
        """画布坐标(项目 CRS) → 田块图层 CRS"""
        layer_crs = self._layer_crs()
        dest = self.canvas.mapSettings().destinationCrs()
        if layer_crs is None or not layer_crs.isValid() or dest == layer_crs:
            return QgsPointXY(map_point)
        from qgis.core import QgsCoordinateTransform
        xform = QgsCoordinateTransform(
            dest, layer_crs, self.canvas.mapSettings().transformContext())
        return xform.transform(map_point)

    def _direction_angle(self) -> Optional[float]:
        """毛管方向角(弧度):复用田块的 direction_type / row_direction"""
        from .lateral_generator import LateralGenerator
        feat = self._field_feat
        direction_type = str(feat.attribute("direction_type") or "long_edge")
        custom = float(feat.attribute("row_direction") or 0)
        if direction_type == "custom":
            # 自定义角不需要几何
            return math.radians(custom)
        # 方向角取原始几何的环(即使无效也能提取顶点序,更忠实手绘现状)
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            return None
        # _calc_direction_angle 是实例方法(依赖 _get_polygon_ring)
        angle = LateralGenerator(self.iface)._calc_direction_angle(
            geom, direction_type, custom)
        return angle if angle is not None else 0.0

    # ── 交互 ──

    def canvasMoveEvent(self, event: QgsMapMouseEvent):
        try:
            geom = self._work_geom()
            if geom is None:
                return
            if self._angle_rad is None:
                self._angle_rad = self._direction_angle()
            from .lateral_generator import LateralGenerator
            pt = self._to_layer_point(event.mapPoint())
            segs = LateralGenerator.lateral_segment_at(
                pt, geom, self._angle_rad, self._min_len())
            # 整行全部区段(细线)——断续行提示还有哪些段可放
            if segs:
                self._rb_row.setToGeometry(
                    QgsGeometry.fromMultiPolylineXY(segs), self._layer_crs())
            else:
                self._rb_row.reset()
            # 目标段(粗绿虚线)= 点击所在段;在缺口处不高亮
            if segs and geom.intersects(QgsGeometry.fromPointXY(pt)):
                target = self._pick_segment(segs, pt)
                self._rb.setToGeometry(
                    QgsGeometry.fromPolylineXY(target), self._layer_crs())
            else:
                self._rb.reset()
        except Exception:
            # 几何异常不能让事件处理器静默死掉(预览从此不再更新)
            import traceback
            traceback.print_exc()
            self._rb.reset()
            self._rb_row.reset()

    def canvasPressEvent(self, event: QgsMapMouseEvent):
        if event.button() == Qt.LeftButton:
            self._place_at(self._to_layer_point(event.mapPoint()))
        elif event.button() == Qt.RightButton:
            self._finish()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._finish()

    def _place_at(self, point):
        """在点击位置放置一根毛管(point 已是图层 CRS)

        断续行只放置点击所在的那一段;其余区段由用户分别点击放置。
        """
        geom = self._work_geom()
        if geom is None:
            return
        if self._angle_rad is None:
            self._angle_rad = self._direction_angle()

        # 田块内外判定(缺口处点击 → 提示并拒绝)
        if not geom.intersects(QgsGeometry.fromPointXY(point)):
            from qgis.PyQt.QtWidgets import QApplication
            self.iface.messageBar().pushWarning(
                "aQuaDrip",
                QApplication.translate(
                    "ManualLateralTool", "点击位置不在田块内,未放置"))
            return

        from .lateral_generator import LateralGenerator
        segs = LateralGenerator.lateral_segment_at(
            point, geom, self._angle_rad, self._min_len())
        if not segs:
            from qgis.PyQt.QtWidgets import QApplication
            self.iface.messageBar().pushWarning(
                "aQuaDrip",
                QApplication.translate(
                    "ManualLateralTool", "点击位置不在田块内,未放置"))
            return
        target = self._pick_segment(segs, point)

        if self._generator is None:
            self._generator = LateralGenerator(self.iface)
        try:
            self._generator.write_manual_lateral(self._field_feat, target)
            self._placed += 1
        except Exception as e:
            from qgis.PyQt.QtWidgets import QApplication
            self.iface.messageBar().pushWarning(
                "aQuaDrip",
                QApplication.translate(
                    "ManualLateralTool", "放置失败: {0}").format(e))
