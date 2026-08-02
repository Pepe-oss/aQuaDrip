"""LateralGenerator — 从农艺参数自动生成毛管

读取已保存的农田参数（垄间距、每垄滴灌带数、滴灌带间距、方向角度等），
调用 wdrip-core builder 生成毛管拓扑，然后写入 aqd_pipes 图层。
"""

import math
from typing import List, Tuple, Optional

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsLineString, QgsWkbTypes,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
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
        # 当前生成所在的图层 CRS（用于单位判定）
        self._src_crs: Optional[QgsCoordinateReferenceSystem] = None
        # 几何是否为地理坐标系（度）——决定是否需要重投影
        self._is_geographic: bool = False

    # ── CRS / 单位适配 ──

    def _resolve_crs(self, feat):
        """推断几何所在 CRS。

        优先用项目 CRS（与「新建项目」流程一致：图层 CRS = 项目 CRS）。
        若项目 CRS 无效，回退到 aqd_fields 图层 CRS，最终回退 EPSG:4326。
        """
        if self.project.crs().isValid():
            return self.project.crs()
        # 回退：从 aqd_fields 图层读 CRS
        for lyr in self.project.mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and "aqd_fields" in (lyr.source() or ""):
                if lyr.crs().isValid():
                    return lyr.crs()
                break
        return QgsCoordinateReferenceSystem("EPSG:4326")

    @staticmethod
    def _utm_zone_crs(lat: float, lon: float) -> QgsCoordinateReferenceSystem:
        """根据经纬度返回对应的 UTM zone EPSG（北/南半球自动判断）。"""
        zone = int(math.floor((lon + 180) / 6) + 1)
        epsg = 32600 + zone if lat >= 0 else 32700 + zone
        return QgsCoordinateReferenceSystem(f"EPSG:{epsg}")

    def _reproject_for_layout(self, geom: QgsGeometry) -> QgsGeometry:
        """若几何为地理坐标系（度），重投影到 UTM（米）以便米单位布局计算。

        Returns:
            用于布局计算的几何（米制）。无需变换时返回原几何。
            回投变换器同时保存到 self._back_xform，供 _lines_back_to_src 使用。
        """
        if not self._is_geographic:
            return geom

        centroid = geom.centroid().asPoint()
        utm = self._utm_zone_crs(centroid.y(), centroid.x())
        fwd = QgsCoordinateTransform(self._src_crs, utm, self.project)
        # back_xform 保存到 self，供 _lines_back_to_src 使用
        self._back_xform = QgsCoordinateTransform(utm, self._src_crs, self.project)
        # QgsGeometry.transform(ct) 原地修改并返回 bool，先拷贝避免污染原对象
        layout_geom = QgsGeometry(geom)
        layout_geom.transform(fwd)
        return layout_geom

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

        # 解析 CRS，判定单位：地理坐标系（度）需重投影到 UTM（米）做布局
        self._src_crs = self._resolve_crs(feat)
        self._is_geographic = self._src_crs.isGeographic()
        self._back_xform = None

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

        # 3. CRS 适配：地理坐标系（度）→ UTM（米）做布局，算完转回原 CRS
        layout_geom = self._reproject_for_layout(geom)
        if self._is_geographic:
            self.iface.messageBar().pushMessage(
                "aQuaDrip",
                f"图层为地理坐标系（{self._src_crs.authid()}），已临时投影到 "
                f"UTM（米制）进行布局计算，结果转回原 CRS",
                level=0, duration=5)

        # 4. 计算方向角度（在投影几何上）
        angle = self._calc_direction_angle(layout_geom, direction_type, custom_angle)

        # 5. 计算毛管位置（米单位空间）
        if planting_pattern == "ridge_count" and ridge_count > 0:
            lines = self._ridge_count_layout(layout_geom, ridge_count, tapes_per_ridge,
                                              tape_spacing, angle)
        else:
            lines = self._ridge_layout(layout_geom, row_spacing, tapes_per_ridge,
                                        tape_spacing, angle)

        # 6. 若做了重投影，把 LineString 转回原 CRS
        if self._is_geographic and self._back_xform is not None and lines:
            lines = self._lines_back_to_src(lines)

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

        # 7. 写入 aqd_pipes（先清除该地块的旧毛管，避免重复生成叠加）
        count = self._write_to_pipes(lines, emitter_spacing, emitter_k, emitter_x,
                                      field_geom=geom)
        if self._dropped_parts > 0:
            self.iface.messageBar().pushMessage(
                "aQuaDrip",
                f"注意：地块为凹形，{self._dropped_parts} 个毛管分段被省略"
                f"（每行仅保留最长段）",
                level=1, duration=6)
        return count

    # ── CRS 回投 ──

    def _lines_back_to_src(self, lines: List[QgsLineString]) -> List[QgsLineString]:
        """把布局生成的 LineString（UTM 米制）转回要素原 CRS。"""
        if self._back_xform is None:
            return lines
        result = []
        for ln in lines:
            pts = [QgsPointXY(p.x(), p.y()) for p in ln.vertices()]
            transformed = [self._back_xform.transform(p) for p in pts]
            result.append(QgsLineString(transformed))
        return result

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
        而毛管横跨地块时质心恰好在边界附近。用距离容差补偿
        （投影坐标 1m，地理坐标 1e-5°≈1m）。
        """
        # 自适应容差：随图层 CRS 单位
        tol = 1e-5 if (layer.crs().isValid() and layer.crs().isGeographic()) else 0.01
        to_delete = []
        for feat in layer.getFeatures():
            if str(feat.attribute("pipe_type") or "") != "lateral":
                continue
            g = feat.geometry()
            if not g or g.isEmpty():
                continue
            centroid = g.centroid()
            # 质心在地块内，或距边界 < tol（边界上的毛管也算）
            if field_geom.contains(centroid) or \
               field_geom.distance(centroid) < tol:
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

    def _get_pipes_layer(self) -> Optional[QgsVectorLayer]:
        for layer in self.project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            s = layer.source() if hasattr(layer, 'source') else ""
            if "aqd_pipes" in s:
                return layer
        return None
