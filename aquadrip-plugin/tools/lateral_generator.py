"""LateralGenerator — 从农艺参数自动生成毛管

读取已保存的农田参数（垄间距、每垄滴灌带数、滴灌带间距、方向角度等），
调用 wdrip-core builder 生成毛管拓扑，然后写入 aqd_pipes 图层。
"""

import math
from typing import List, Tuple, Optional

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsLineString,
)
from qgis.PyQt.QtCore import QVariant


class LateralGenerator:
    """毛管生成器"""

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()

    def generate(self, feat) -> int:
        """根据一条农田要素的农艺参数生成毛管
        
        Args:
            feat: aqd_fields 中的要素（需包含农艺参数字段）
            
        Returns:
            生成的毛管条数
        """
        # 1. 读取参数
        geom = feat.geometry()
        if not geom or geom.isEmpty():
            raise ValueError("农田几何为空")

        planting_pattern = str(feat.attribute("planting_pattern") or "ridge")
        row_spacing = float(feat.attribute("row_spacing") or 0.6)
        tapes_per_ridge = int(feat.attribute("tapes_per_ridge") or 1)
        tape_spacing = float(feat.attribute("tape_spacing") or 0.3)
        ridge_count = int(feat.attribute("ridge_count") or 0)
        direction_type = str(feat.attribute("direction_type") or "long_edge")
        custom_angle = float(feat.attribute("row_direction") or 0)
        emitter_spacing = float(feat.attribute("emitter_spacing") or 0.3)

        # 2. 计算方向角度
        angle = self._calc_direction_angle(geom, direction_type, custom_angle)

        # 3. 计算毛管位置
        if planting_pattern == "ridge_count" and ridge_count > 0:
            lines = self._ridge_count_layout(geom, ridge_count, tapes_per_ridge,
                                              tape_spacing, angle)
        else:
            lines = self._ridge_layout(geom, row_spacing, tapes_per_ridge,
                                        tape_spacing, angle)

        # 4. 写入 aqd_pipes
        return self._write_to_pipes(lines, emitter_spacing)

    def _calc_direction_angle(self, geom: QgsGeometry,
                               direction_type: str,
                               custom_angle: float) -> float:
        """计算毛管方向角度"""
        if direction_type == "custom":
            return math.radians(custom_angle)
        if direction_type in ("long_edge", "short_edge"):
            pts = self._get_polygon_ring(geom)
            if len(pts) < 2:
                return 0
            # 找到最长或最短边
            best_edge = None
            best_len = -1 if direction_type == "long_edge" else float("inf")
            for i in range(len(pts) - 1):
                dx = pts[i+1].x() - pts[i].x()
                dy = pts[i+1].y() - pts[i].y()
                length = dx*dx + dy*dy
                if (direction_type == "long_edge" and length > best_len) or \
                   (direction_type == "short_edge" and length < best_len):
                    best_len = length
                    best_edge = (dx, dy)
            if best_edge:
                return math.atan2(best_edge[1], best_edge[0])
        return 0

    def _ridge_layout(self, geom: QgsGeometry,
                      row_spacing: float,
                      tapes_per_ridge: int,
                      tape_spacing: float,
                      angle: float) -> List[QgsLineString]:
        """垄模式：等距生成毛管"""
        # 旋转多边形，使毛管方向与 X 轴平行
        rotated = self._rotate_geom(geom, -angle)
        bbox = rotated.boundingBox()

        lines = []
        effective_tape_spacing = tape_spacing if tapes_per_ridge > 1 else row_spacing

        y = bbox.yMinimum()
        ridge_idx = 0
        while y < bbox.yMaximum():
            # 每垄生成 tapes_per_ridge 条毛管
            for t in range(tapes_per_ridge):
                ly = y + t * effective_tape_spacing
                if ly > bbox.yMaximum():
                    break
                line = QgsLineString(
                    [QgsPointXY(bbox.xMinimum(), ly),
                     QgsPointXY(bbox.xMaximum(), ly)]
                )
                clipped = self._clip_line(line, rotated)
                if clipped and clipped.length() > 0.5:
                    lines.append(clipped)

            y += row_spacing
            ridge_idx += 1

        # 逆旋转回原坐标
        return [self._rotate_line(l, angle) for l in lines]

    def _ridge_count_layout(self, geom: QgsGeometry,
                            ridge_count: int,
                            tapes_per_ridge: int,
                            tape_spacing: float,
                            angle: float) -> List[QgsLineString]:
        """按垄数模式"""
        rotated = self._rotate_geom(geom, -angle)
        bbox = rotated.boundingBox()
        width = bbox.height()
        row_spacing = width / max(ridge_count, 1)

        effective_tape_spacing = tape_spacing if tapes_per_ridge > 1 else row_spacing

        lines = []
        for r in range(ridge_count):
            y = bbox.yMinimum() + row_spacing * (r + 0.5)
            for t in range(tapes_per_ridge):
                ly = y + t * effective_tape_spacing
                if ly > bbox.yMaximum():
                    break
                line = QgsLineString(
                    [QgsPointXY(bbox.xMinimum(), ly),
                     QgsPointXY(bbox.xMaximum(), ly)]
                )
                clipped = self._clip_line(line, rotated)
                if clipped and clipped.length() > 0.5:
                    lines.append(clipped)

        return [self._rotate_line(l, angle) for l in lines]

    def _write_to_pipes(self, lines: List[QgsLineString],
                        emitter_spacing: float) -> int:
        """写入 aqd_pipes 图层"""
        layer = self._get_pipes_layer()
        if not layer:
            raise RuntimeError("aqd_pipes 图层未找到，请先初始化图层")

        layer.startEditing()
        count = 0
        for i, line in enumerate(lines):
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry(line))
            feat.setAttribute("pipe_type", "lateral")
            feat.setAttribute("device", "none")
            feat.setAttribute("status", "open")
            feat.setAttribute("material", "PE")
            feat.setAttribute("roughness", 130)
            feat.setAttribute("emitter_spacing", emitter_spacing)
            layer.addFeature(feat)
            count += 1

        layer.commitChanges()
        layer.triggerRepaint()
        self.iface.messageBar().pushMessage(
            "aQuaDrip", f"已生成 {count} 条毛管", level=0, duration=5)
        return count

    # ── 几何辅助 ──

    @staticmethod
    def _get_polygon_ring(geom: QgsGeometry) -> list:
        """获取多边形外环"""
        if geom.isMultipart():
            parts = geom.asMultiPolygon()
            return parts[0][0] if parts else []
        parts = geom.asPolygon()
        return parts[0] if parts else []

    @staticmethod
    def _rotate_geom(geom: QgsGeometry, angle_rad: float) -> QgsGeometry:
        """绕原点旋转几何"""
        centroid = geom.centroid().asPoint()
        geom_copy = QgsGeometry(geom)
        geom_copy.translate(-centroid.x(), -centroid.y())
        geom_copy.rotate(math.degrees(angle_rad), QgsPointXY(0, 0))
        geom_copy.translate(centroid.x(), centroid.y())
        return geom_copy

    @staticmethod
    def _rotate_line(line: QgsLineString, angle_rad: float) -> QgsLineString:
        """旋转线"""
        import math
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        pts = [line.startPoint(), line.endPoint()]
        rotated = []
        for pt in pts:
            rx = pt.x() * cos_a - pt.y() * sin_a
            ry = pt.x() * sin_a + pt.y() * cos_a
            rotated.append(QgsPointXY(rx, ry))
        return QgsLineString(rotated)

    @staticmethod
    def _clip_line(line: QgsLineString, clip_geom: QgsGeometry) -> Optional[QgsLineString]:
        """将线裁剪到多边形内"""
        line_geom = QgsGeometry(line)
        clipped = line_geom.intersection(clip_geom)
        if clipped.isEmpty():
            return None
        if clipped.isMultipart():
            parts = clipped.asMultiPolyline()
            longest = max(parts, key=lambda p: QgsGeometry(p).length()) if parts else None
            return QgsLineString(longest) if longest else None
        pts = clipped.asPolyline()
        return QgsLineString(pts) if len(pts) >= 2 else None

    def _get_pipes_layer(self) -> Optional[QgsVectorLayer]:
        for layer in self.project.mapLayers().values():
            s = layer.source() if hasattr(layer, 'source') else ""
            if "aqd_pipes" in s:
                return layer
        return None
