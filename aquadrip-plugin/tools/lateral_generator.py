"""LateralGenerator — 从农艺参数自动生成毛管

读取已保存的农田参数（垄间距、每垄滴灌带数、滴灌带间距、方向角度等），
调用 wdrip-core builder 生成毛管拓扑，然后写入 aqd_pipes 图层。
"""

import math
from typing import List, Tuple, Optional

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsLineString, QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant


class LateralGenerator:
    """毛管生成器"""

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()
        # 凹形地块时，一条扫描线与地块交成多段，仅保留最长段，
        # 此处累计被丢弃的段数用于提示用户
        self._dropped_parts = 0

    def generate(self, feat) -> int:
        """根据一条农田要素的农艺参数生成毛管

        Args:
            feat: aqd_fields 中的要素（需包含农艺参数字段）

        Returns:
            生成的毛管条数

        Raises:
            ValueError: 参数非法（间距 ≤ 0 会导致布局死循环，必须前置拦截）
        """
        # 1. 读取参数
        self._dropped_parts = 0
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
        emitter_k = float(feat.attribute("emitter_k") or 0.506)
        emitter_x = float(feat.attribute("emitter_x") or 0.5)

        # 2. 参数校验（间距 ≤ 0 会让布局 while 循环永不退出，必须拦截）
        errors = []
        if tape_spacing <= 0:
            errors.append(f"滴灌带间距必须大于 0（当前 {tape_spacing}）")
        if tapes_per_ridge < 1:
            errors.append(f"每垄滴灌带数必须 ≥ 1（当前 {tapes_per_ridge}）")
        if tapes_per_ridge > 1 and row_spacing <= 0:
            errors.append(f"垄间距必须大于 0（当前 {row_spacing}）")
        if planting_pattern == "ridge_count" and ridge_count <= 0:
            errors.append(f"按垄数模式必须指定垄数 > 0（当前 {ridge_count}）")
        if emitter_spacing <= 0:
            errors.append(f"滴头间距必须大于 0（当前 {emitter_spacing}）")
        if errors:
            raise ValueError("农艺参数非法：\n" + "\n".join(errors))

        # 3. 计算方向角度
        angle = self._calc_direction_angle(geom, direction_type, custom_angle)

        # 4. 计算毛管位置
        if planting_pattern == "ridge_count" and ridge_count > 0:
            lines = self._ridge_count_layout(geom, ridge_count, tapes_per_ridge,
                                              tape_spacing, angle)
        else:
            lines = self._ridge_layout(geom, row_spacing, tapes_per_ridge,
                                        tape_spacing, angle)

        # 诊断：输出实际生成的毛管数量
        self.iface.messageBar().pushMessage(
            "aQuaDrip",
            f"布局计算: pattern={planting_pattern} tpr={tapes_per_ridge} "
            f"rs={row_spacing} ts={tape_spacing} rc={ridge_count} "
            f"→ {len(lines)} 条毛管",
            level=0, duration=6)

        if not lines:
            raise ValueError(
                "未生成任何毛管：地块可能太小，或间距参数过大")

        # 5. 写入 aqd_pipes（先清除该地块的旧毛管，避免重复生成叠加）
        count = self._write_to_pipes(lines, emitter_spacing, emitter_k, emitter_x,
                                      field_geom=geom)
        if self._dropped_parts > 0:
            self.iface.messageBar().pushMessage(
                "aQuaDrip",
                f"注意：地块为凹形，{self._dropped_parts} 个毛管分段被省略"
                f"（每行仅保留最长段）",
                level=1, duration=6)
        return count

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
        """垄模式生成毛管

        规则（与 UI 联动一致）：
        - tapes_per_ridge == 1：单带模式，滴灌带按"垄间距"(row_spacing)等距排列
        - tapes_per_ridge > 1 ：垄模式，每垄 tapes_per_ridge 条带以垄中线
          对称分布（垄内间距 tape_spacing）；"垄间距"(row_spacing) 指相邻
          两垄**中心线**之间的距离。
        """
        center = geom.centroid().asPoint()
        rot_geom = self._rotate_around(geom, angle, center)
        bbox = rot_geom.boundingBox()

        # 1. 计算所有滴灌带的 y 位置
        #    用索引乘法而非累加，避免浮点累积误差在地块边界多生成一条线
        ys: List[float] = []
        if tapes_per_ridge <= 1:
            # 单带模式：每垄 1 条带，垄间距 = row_spacing
            i = 0
            while True:
                ly = bbox.yMinimum() + i * row_spacing
                if ly >= bbox.yMaximum():
                    break
                ys.append(ly)
                i += 1
        else:
            # 垄模式：row_spacing = 相邻两垄中心线距离
            # 每垄 tapes_per_ridge 条带以垄中线对称分布
            half = (tapes_per_ridge - 1) * tape_spacing / 2.0
            i = 0
            while True:
                y_center = bbox.yMinimum() + half + i * row_spacing
                if y_center - half >= bbox.yMaximum():
                    break
                for t in range(tapes_per_ridge):
                    ly = y_center - half + t * tape_spacing
                    if ly >= bbox.yMaximum():
                        break
                    ys.append(ly)
                i += 1

        # 2. 逐位置生成水平线并裁剪到地块内
        raw_lines = []
        last_y = None
        for ly in ys:
            # 参数过密（垄间距 < 垄内宽度）时，跳过与前一条重复的位置
            if last_y is not None and abs(ly - last_y) < 1e-6:
                continue
            line = QgsGeometry.fromPolylineXY([
                QgsPointXY(bbox.xMinimum(), ly),
                QgsPointXY(bbox.xMaximum(), ly)])
            clipped = line.intersection(rot_geom)
            if clipped.isEmpty() or clipped.isNull() or clipped.type() != QgsWkbTypes.LineGeometry:
                continue
            if clipped.isMultipart():
                # 凹形地块：一条扫描线交成多段，仅保留最长段并计数
                parts = clipped.asMultiPolyline()
                self._dropped_parts += len(parts) - 1
                pts = max(parts, key=lambda p: QgsGeometry(p).length())
            else:
                pts = clipped.asPolyline()
            if len(pts) >= 2 and QgsGeometry.fromPolylineXY(pts).length() > 0.5:
                raw_lines.append(QgsLineString(pts))
                last_y = ly

        # 统一绕多边形中心逆旋转
        return [QgsLineString(self._rotate_points(
            [p for p in l.vertices()], angle, center)) for l in raw_lines]

    def _ridge_count_layout(self, geom: QgsGeometry,
                            ridge_count: int, tapes_per_ridge: int,
                            tape_spacing: float, angle: float) -> List[QgsLineString]:
        """按垄数生成：地块高度 ridge_count 等分，每垄中线处布置滴灌带

        每垄 tapes_per_ridge 条带以垄中线对称分布（垄内间距 tape_spacing）。
        """
        center = geom.centroid().asPoint()
        rot_geom = self._rotate_around(geom, angle, center)
        bbox = rot_geom.boundingBox()
        row_sp = bbox.height() / max(ridge_count, 1)
        # 垄内带相对垄中线的对称偏移
        half = (tapes_per_ridge - 1) * tape_spacing / 2.0

        raw_lines = []
        last_y = None
        for r in range(ridge_count):
            y = bbox.yMinimum() + row_sp * (r + 0.5)
            for t in range(tapes_per_ridge):
                ly = y - half + t * tape_spacing
                if ly >= bbox.yMaximum():
                    break
                # 带间距过大导致与邻垄重叠时，跳过重复位置
                if last_y is not None and abs(ly - last_y) < 1e-6:
                    continue
                line = QgsGeometry.fromPolylineXY([
                    QgsPointXY(bbox.xMinimum(), ly),
                    QgsPointXY(bbox.xMaximum(), ly)])
                clipped = line.intersection(rot_geom)
                if clipped.isEmpty() or clipped.isNull() or clipped.type() != QgsWkbTypes.LineGeometry:
                    continue
                if clipped.isMultipart():
                    parts = clipped.asMultiPolyline()
                    self._dropped_parts += len(parts) - 1
                    pts = max(parts, key=lambda p: QgsGeometry.fromPolyline(p).length())
                else:
                    pts = clipped.asPolyline()
                if len(pts) >= 2 and QgsGeometry.fromPolylineXY(pts).length() > 0.5:
                    raw_lines.append(QgsLineString(pts))
                    last_y = ly

        return [QgsLineString(self._rotate_points(
            [p for p in l.vertices()], angle, center)) for l in raw_lines]

    @staticmethod
    def _rotate_around(geom: QgsGeometry, angle_rad: float,
                       center: QgsPointXY) -> QgsGeometry:
        """绕指定中心旋转"""
        g = QgsGeometry(geom)
        g.translate(-center.x(), -center.y())
        g.rotate(math.degrees(angle_rad), QgsPointXY(0, 0))
        g.translate(center.x(), center.y())
        return g

    @staticmethod
    def _rotate_points(pts: list, angle_rad: float,
                       center: QgsPointXY) -> list:
        """绕指定中心旋转点列表"""
        cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
        result = []
        for p in pts:
            dx, dy = p.x() - center.x(), p.y() - center.y()
            rx = dx * cos_a - dy * sin_a + center.x()
            ry = dx * sin_a + dy * cos_a + center.y()
            result.append(QgsPointXY(rx, ry))
        return result

    @staticmethod
    def _rotate_geometry(geom: QgsGeometry, angle_rad: float) -> Optional[QgsGeometry]:
        """绕几何中心旋转"""
        centroid = geom.centroid().asPoint()
        g = QgsGeometry(geom)
        g.translate(-centroid.x(), -centroid.y())
        g.rotate(math.degrees(angle_rad), QgsPointXY(0, 0))
        g.translate(centroid.x(), centroid.y())
        return g

    def _write_to_pipes(self, lines: List[QgsLineString],
                        emitter_spacing: float,
                        emitter_k: float,
                        emitter_x: float,
                        field_geom: QgsGeometry = None) -> int:
        """写入 aqd_pipes 图层（先清除该地块旧毛管，避免重复生成叠加）"""
        layer = self._get_pipes_layer()
        if not layer:
            raise RuntimeError("aqd_pipes 图层未找到，请先初始化图层")

        need_edit = not layer.isEditable()
        if need_edit:
            layer.startEditing()
        try:
            # 清除该地块的旧毛管
            deleted = 0
            if field_geom is not None:
                deleted = self._delete_existing_laterals(layer, field_geom)

            count = 0
            for line in lines:
                feat = QgsFeature(layer.fields())
                feat.setGeometry(QgsGeometry(line))
                feat.setAttribute("pipe_type", "lateral")
                feat.setAttribute("device", "none")
                feat.setAttribute("status", "open")
                feat.setAttribute("material", "PE")
                feat.setAttribute("roughness", 130)
                feat.setAttribute("diameter", 16)  # 毛管默认直径 16mm
                feat.setAttribute("emitter_spacing", emitter_spacing)
                feat.setAttribute("emitter_k", emitter_k)
                feat.setAttribute("emitter_x", emitter_x)
                if not layer.addFeature(feat):
                    raise RuntimeError("写入毛管要素失败")
                count += 1

            if need_edit and not layer.commitChanges():
                raise RuntimeError(
                    f"提交失败: {'; '.join(layer.commitErrors())}")
        except Exception:
            if need_edit:
                layer.rollBack()
            raise

        layer.triggerRepaint()
        msg = f"已生成 {count} 条毛管"
        if deleted:
            msg += f"（已清除 {deleted} 条旧毛管）"
        self.iface.messageBar().pushMessage("aQuaDrip", msg, level=0, duration=5)
        return count

    @staticmethod
    def _delete_existing_laterals(layer: QgsVectorLayer,
                                   field_geom: QgsGeometry) -> int:
        """删除质心位于该地块内（或边界附近）的现有毛管

        用质心判定避免误删跨地块手画毛管。
        contains() 严格判定——边界上的质心不算"内部"，
        而毛管横跨地块时质心恰好在边界附近。用距离容差补偿。
        """
        to_delete = []
        for feat in layer.getFeatures():
            if str(feat.attribute("pipe_type") or "") != "lateral":
                continue
            g = feat.geometry()
            if not g or g.isEmpty():
                continue
            centroid = g.centroid()
            # 质心在地块内，或距边界 < 0.01（边界上的毛管也算）
            if field_geom.contains(centroid) or \
               field_geom.distance(centroid) < 0.01:
                to_delete.append(feat.id())
        if to_delete:
            layer.deleteFeatures(to_delete)
        return len(to_delete)

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
        if clipped.isEmpty() or clipped.isNull():
            return None
        if clipped.type() != QgsWkbTypes.LineGeometry:
            return None
        if clipped.isMultipart():
            parts = clipped.asMultiPolyline()
            longest = max(parts, key=lambda p: QgsGeometry(p).length()) if parts else None
            return QgsLineString(longest) if longest else None
        pts = clipped.asPolyline()
        return QgsLineString(pts) if len(pts) >= 2 else None

    def _get_pipes_layer(self) -> Optional[QgsVectorLayer]:
        for layer in self.project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            s = layer.source() if hasattr(layer, 'source') else ""
            if "aqd_pipes" in s:
                return layer
        return None
