"""TrimTool — 管道切割工具（点选 / 画线两种模式）"""

from qgis.gui import QgsMapTool, QgsMapMouseEvent, QgsRubberBand
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsGeometry, QgsPointXY,
    QgsFeature, QgsWkbTypes, QgsPoint,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QApplication


class TrimTool(QgsMapTool):
    """管道切割工具

    两种模式:
      - click: 逐根点击管道切割
      - line:   画线批量切割所有相交管道
    """

    def __init__(self, iface, pipe_types=None, cut_length=0, mode="click"):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.pipe_types = pipe_types or ["lateral"]
        self.cut_length = cut_length
        self.mode = mode  # "click" or "line"

        # 橡皮筋
        self.rb = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rb.setStrokeColor(QColor(231, 76, 60))
        self.rb.setWidth(2)

        # 画线模式状态
        self._drawing = False
        self._draw_start = None

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        type_names = {"mainline": QApplication.translate("TrimTool", "干管"), "submain": QApplication.translate("TrimTool", "支管"), "lateral": QApplication.translate("TrimTool", "毛管")}
        types_str = "/".join(type_names.get(t, t) for t in self.pipe_types)

        if self.mode == "line":
            msg = QApplication.translate("TrimTool", "按住拖动画线，批量切割相交{0}").format(types_str)
        else:
            msg = QApplication.translate("TrimTool", "点击{0}进行切割").format(types_str)
        if self.cut_length > 0:
            msg += QApplication.translate("TrimTool", "（切除{0:.2f}m）").format(self.cut_length)
        self.iface.messageBar().pushMessage("aQuaDrip", msg, level=0, duration=5)

    def deactivate(self):
        self.rb.reset()
        self._drawing = False
        self._draw_start = None
        super().deactivate()

    # ── 鼠标事件 ──

    def canvasPressEvent(self, event: QgsMapMouseEvent):
        try:
            if event.button() == Qt.LeftButton:
                if self.mode == "line":
                    if not self._drawing:
                        self._start_draw(event)
                else:
                    # 用原始点击位置做几何命中——不用 snapPoint():
                    # 插件默认开启全局捕捉(AllLayers 顶点+线段 15px)，
                    # 点击会被吸到附近的节点/别的管段上，导致切错
                    # 位置、切错管甚至找不到管(要点好几下)
                    point = QgsPointXY(event.mapPoint())
                    self._trim_at_point(point)
            elif event.button() == Qt.RightButton:
                if self.mode == "line" and self._drawing:
                    self._drawing = False
                    self.rb.reset()
                else:
                    self.canvas.unsetMapTool(self)
        except Exception:
            import traceback
            traceback.print_exc()

    def canvasMoveEvent(self, event: QgsMapMouseEvent):
        try:
            if self.mode == "line" and self._drawing and self._draw_start:
                end = QgsPointXY(event.mapPoint())
                self.rb.setToGeometry(
                    QgsGeometry.fromPolylineXY([self._draw_start, end]), None)
        except Exception:
            import traceback
            traceback.print_exc()

    def canvasReleaseEvent(self, event: QgsMapMouseEvent):
        try:
            if event.button() == Qt.LeftButton and self.mode == "line" and self._drawing:
                self._drawing = False
                end = QgsPointXY(event.mapPoint())
                if self._draw_start and self._draw_start.distance(end) < self.canvas.mapUnitsPerPixel() * 10:
                    self.rb.reset()
                    self._draw_start = None
                    return  # 太短，忽略
                draw_geom = QgsGeometry.fromPolylineXY([self._draw_start, end])
                self.rb.reset()
                self._draw_start = None
                self._batch_trim_by_line(draw_geom)
        except Exception:
            import traceback
            traceback.print_exc()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.mode == "line" and self._drawing:
                self._drawing = False
                self.rb.reset()
            self.canvas.unsetMapTool(self)

    # ── 画线模式（按住拖拽）──

    def _start_draw(self, event: QgsMapMouseEvent):
        """开始拖拽画线"""
        self._drawing = True
        self._draw_start = QgsPointXY(event.mapPoint())
        self.rb.reset()

    # ── 点选模式 ──

    def _trim_at_point(self, point: QgsPointXY, tolerance=None):
        """点选模式：在点击位置切割最近管道"""
        layer = self._find_pipe_layer()
        if not layer:
            self.iface.messageBar().pushWarning("aQuaDrip", QApplication.translate("TrimTool", "aqd_pipes 未找到"))
            return

        if tolerance is None:
            tolerance = self._pixel_tolerance(layer)

        # 查找最近管道
        best_feat = None
        best_dist = tolerance
        best_pos = 0.0

        for feat in layer.getFeatures():
            ptype = str(feat.attribute("pipe_type") or "")
            if ptype not in self.pipe_types:
                continue
            pos = self._hit_test(feat, point, best_dist)
            if pos is not None:
                best_dist, best_feat, best_pos = pos

        if not best_feat:
            self.iface.messageBar().pushWarning("aQuaDrip", QApplication.translate("TrimTool", "未选中有效管道"))
            return

        need_edit = not layer.isEditable()
        if need_edit:
            layer.startEditing()
        try:
            _, removed_m = self._do_split(layer, best_feat, [best_pos])
            if need_edit and not layer.commitChanges():
                raise RuntimeError(QApplication.translate("TrimTool", "提交失败: {0}").format('; '.join(layer.commitErrors())))
        except Exception as e:
            if need_edit:
                layer.rollBack()
            self.iface.messageBar().pushWarning("aQuaDrip", QApplication.translate("TrimTool", "切割失败: {0}").format(e))
            return
        layer.triggerRepaint()
        if self.cut_length > 0:
            self.iface.messageBar().pushMessage(
                "aQuaDrip", QApplication.translate("TrimTool", "已切除 {0:.1f} m").format(removed_m), level=0, duration=3)
        else:
            self.iface.messageBar().pushMessage(
                "aQuaDrip", QApplication.translate("TrimTool", "管道已分割"), level=0, duration=3)

    def _pixel_tolerance(self, layer):
        """点击命中容差（图层单位）：15 像素距离，钳位在 2~50 米之间

        纯像素容差在紧 zoom 时不足 2m（点不准），在远 zoom 的经纬度
        下又可达公里级（误切远处的管）——统一换算成米再钳位。"""
        try:
            geo = layer.crs().isValid() and layer.crs().isGeographic()
        except Exception:
            geo = False
        px_m = self.canvas.mapUnitsPerPixel() * (111320.0 if geo else 1.0)
        tol_m = max(2.0, min(px_m * 15, 50.0))
        return tol_m / (111320.0 if geo else 1.0)

    # ── 画线批量切割 ──

    def _batch_trim_by_line(self, draw_geom: QgsGeometry):
        """画线模式：查找所有相交管道并批量切割"""
        layer = self._find_pipe_layer()
        if not layer:
            self.iface.messageBar().pushWarning("aQuaDrip", QApplication.translate("TrimTool", "aqd_pipes 未找到"))
            return

        # 先收集所有切割任务（不能在遍历 features 时修改 layer）
        tasks = []  # [(feat_id, [split_positions_along_pipe]), ...]
        for feat in layer.getFeatures():
            ptype = str(feat.attribute("pipe_type") or "")
            if ptype not in self.pipe_types:
                continue
            positions = self._find_intersections(feat, draw_geom)
            if positions:
                tasks.append((feat.id(), positions))

        if not tasks:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("TrimTool", "画线与选中管道无交点"))
            return

        total_cut = 0
        total_removed = 0.0
        need_edit = not layer.isEditable()
        if need_edit:
            layer.startEditing()
        try:
            for fid, positions in tasks:
                # 重新查找 feature（ID 可能已因前面的修改而改变，
                # 但由于我们只删不增在同一事务中，ID 稳定）
                fid_map = {f.id(): f for f in layer.getFeatures()}
                feat = fid_map.get(fid)
                if feat is None:
                    continue

                count, removed_m = self._do_split(layer, feat, positions)
                total_removed += removed_m
                if count >= 2:
                    total_cut += 1

            if need_edit and not layer.commitChanges():
                raise RuntimeError(QApplication.translate("TrimTool", "提交失败: {0}").format('; '.join(layer.commitErrors())))
        except Exception as e:
            if need_edit:
                layer.rollBack()
            self.iface.messageBar().pushWarning("aQuaDrip", QApplication.translate("TrimTool", "批量切割失败: {0}").format(e))
            return

        layer.triggerRepaint()
        if self.cut_length > 0:
            self.iface.messageBar().pushMessage(
                "aQuaDrip",
                QApplication.translate("TrimTool", "已切割 {0} 根管道，共切除 {1:.1f} m").format(total_cut, total_removed),
                level=0, duration=4)
        else:
            self.iface.messageBar().pushMessage(
                "aQuaDrip", QApplication.translate("TrimTool", "已切割 {0} 根管道").format(total_cut), level=0, duration=4)

    def _do_split(self, layer, feat, positions) -> tuple:
        """在管道指定位置(0~1)处分割并写入图层

        positions: 沿线位置比例列表（层长比例，已排序去重）
        返回 (生成段数, 实际切除米数)
        注意：调用者负责管理编辑会话（startEditing/commitChanges）
        """
        geom = feat.geometry()
        line = geom.asPolyline()
        total_len = geom.length()

        # 切割长度是米，而 geom.length() 是图层单位（经纬度=度）。
        # 所有区间阈值/钳位一律在【米】空间计算，再经层长↔米长
        # 累计换算（折线各向异性精确）映射回层长比例——
        # 原先的"比例阈值 0.005"在 650m 毛管上等于 3.25m，
        # 设 2m 时整个切除区间被丢弃（表现为切了没反应）；
        # "0.01/0.99 比例钳位"在长管上则是 6.5m 的端部禁区
        cut_positions = list(positions)
        remove_zones = []  # (层长比例 lo, 层长比例 hi)
        removed_m = 0.0
        if self.cut_length > 0:
            total_len_m, cum_l, cum_m = self._cumulative_lengths(layer, line)
            if total_len_m > 0:
                half = self.cut_length / 2
                for pos in positions:
                    # 点击位置(层长比例) → 米长比例，在米空间定区间
                    m = self._convert_frac(line, total_len, total_len_m,
                                           cum_l, cum_m, pos, to_meters=True)
                    lo_m = max(0.0, m - half / total_len_m)
                    hi_m = min(1.0, m + half / total_len_m)
                    zone_m = (hi_m - lo_m) * total_len_m
                    if zone_m < 0.01:
                        # 区间退化(<1cm)：按纯分割处理
                        continue
                    lo = self._convert_frac(line, total_len, total_len_m,
                                            cum_l, cum_m, lo_m, to_meters=False)
                    hi = self._convert_frac(line, total_len, total_len_m,
                                            cum_l, cum_m, hi_m, to_meters=False)
                    cut_positions.extend([lo, hi])
                    remove_zones.append((lo, hi))
                    removed_m += zone_m

        segments = self._split_polyline(line, total_len, cut_positions)

        # 移除切除区间内的段（区间端点已换算为层长比例，
        # 段中点同为层长比例，直接比较）
        if remove_zones:
            kept = []
            cum = 0.0
            for seg in segments:
                seg_len = sum(
                    seg[i].distance(seg[i + 1]) for i in range(len(seg) - 1)
                ) if len(seg) >= 2 else 0.0
                seg_mid = (cum + seg_len / 2) / total_len if total_len > 0 else 0
                cum += seg_len
                # 如果段的中点在任何切除区间内，跳过
                in_remove = any(p1 <= seg_mid <= p2 for p1, p2 in remove_zones)
                if not in_remove:
                    kept.append(seg)
            segments = kept

        if not segments:
            return 0, removed_m

        # 写入图层
        skip_fields = {"fid", "id"}
        clear_fields = {"flow", "velocity"}

        for idx, pts in enumerate(segments):
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPolylineXY(pts))
            for field in layer.fields():
                fname = field.name()
                if fname.lower() in skip_fields or fname in clear_fields:
                    continue
                if fname == "to_node" and idx < len(segments) - 1:
                    continue
                if fname == "from_node" and idx > 0:
                    continue
                val = feat.attribute(fname)
                if val is not None:
                    try:
                        f.setAttribute(fname, val)
                    except TypeError:
                        pass
            if not layer.addFeature(f):
                raise RuntimeError(QApplication.translate("TrimTool", "添加切割段失败"))
        layer.deleteFeature(feat.id())

        return len(segments), removed_m

    @staticmethod
    def _cumulative_lengths(layer, line):
        """折线的层长/米长累计表（切割区间换算的单一数据源）

        Returns:
            (总米长, cum_layer 顶点累计层长列表, cum_meter 顶点累计米长列表)
            椭球不可用时米长按平面长度近似（经纬度 ×111320）
        """
        n = len(line)
        cum_l = [0.0] * n
        cum_m = [0.0] * n
        try:
            from qgis.core import QgsDistanceArea, QgsProject
            da = QgsDistanceArea()
            crs = layer.crs() if layer is not None else None
            if crs is not None and crs.isValid():
                da.setSourceCrs(crs, QgsProject.instance().transformContext())
            da.setEllipsoid("WGS84")
            use_ellipsoid = True
        except Exception:
            use_ellipsoid = False
            geographic = (layer is not None and layer.crs().isValid()
                          and layer.crs().isGeographic())
        for i in range(n - 1):
            sl = line[i].distance(line[i + 1])
            if use_ellipsoid:
                sm = float(da.measureLine(line[i], line[i + 1]) or 0)
                if sm <= 0:
                    sm = sl * (111320.0 if (crs is not None and crs.isGeographic()) else 1.0)
            else:
                sm = sl * (111320.0 if geographic else 1.0)
            cum_l[i + 1] = cum_l[i] + sl
            cum_m[i + 1] = cum_m[i] + sm
        return cum_m[-1], cum_l, cum_m

    @staticmethod
    def _convert_frac(line, total_len, total_len_m, cum_l, cum_m, frac,
                      to_meters: bool):
        """层长比例 ↔ 米长比例 换算（顶点间线性插值，折线各向异性精确）

        直线两种比例天然一致；折线因各段米/层换算率随方向不同
        （经纬度下东西向 ×cosφ），必须按累计表换算。
        """
        if total_len <= 0 or total_len_m <= 0 or len(line) < 2:
            return frac
        src_cum, dst_cum = (cum_l, cum_m) if to_meters else (cum_m, cum_l)
        src_total, dst_total = (total_len, total_len_m) if to_meters \
            else (total_len_m, total_len)
        target = frac * src_total
        for i in range(len(line) - 1):
            s0, s1 = src_cum[i], src_cum[i + 1]
            if s1 >= target or i == len(line) - 2:
                r = (target - s0) / (s1 - s0) if s1 > s0 else 0.0
                r = max(0.0, min(1.0, r))
                return (dst_cum[i] + (dst_cum[i + 1] - dst_cum[i]) * r) / dst_total
        return frac

    def _split_polyline(self, line, total_len, positions):
        """在多个沿线比例位置分割折线，返回段列表（每段至少2个顶点）"""
        if not positions or total_len <= 0 or len(line) < 2:
            return [line]

        # 排序并去重
        unique = sorted(set(round(p, 6) for p in positions))
        if not unique:
            return [line]

        # 为每个切割位置计算线段索引和坐标
        cuts = []  # [(seg_idx, point)]
        for pos in unique:
            target = total_len * pos
            cum = 0.0
            for i in range(len(line) - 1):
                sl = line[i].distance(line[i + 1])
                if sl <= 0:
                    continue
                if cum + sl >= target:
                    r = (target - cum) / sl
                    r = max(0.001, min(0.999, r))
                    x = line[i].x() + (line[i + 1].x() - line[i].x()) * r
                    y = line[i].y() + (line[i + 1].y() - line[i].y()) * r
                    cuts.append((i, QgsPointXY(x, y)))
                    break
                cum += sl
        cuts.sort(key=lambda c: c[0])

        # 遍历所有线段，遇到切点就分段
        segments = []
        current_seg = [line[0]]
        ci = 0  # 当前处理的 cut 索引

        for i in range(len(line) - 1):
            # 收集当前线段 (i → i+1) 上的所有切点
            seg_cuts = []
            while ci < len(cuts) and cuts[ci][0] == i:
                seg_cuts.append(cuts[ci][1])
                ci += 1

            if seg_cuts:
                for pt in seg_cuts:
                    current_seg.append(pt)
                    if len(current_seg) >= 2:
                        segments.append(list(current_seg))
                    current_seg = [pt]
            # 添加线段终点
            current_seg.append(line[i + 1])

        # 最后一段
        if len(current_seg) >= 2:
            segments.append(list(current_seg))

        return segments if segments else [line]

    # ── 辅助方法 ──

    def _find_intersections(self, feat, draw_geom):
        """找到管道与画线的所有交点，返回沿管道的位置比例列表（排序）"""
        pipe_geom = feat.geometry()
        if not pipe_geom:
            return []

        inter = pipe_geom.intersection(draw_geom)
        if inter.isEmpty():
            return []

        # 提取交点坐标
        pts = []
        wkb_type = inter.type() if hasattr(inter, 'type') else None

        if wkb_type == QgsWkbTypes.PointGeometry:
            p = inter.asPoint()
            pts.append(QgsPointXY(p.x(), p.y()))
        elif wkb_type == QgsWkbTypes.LineGeometry:
            # 线与线重合：取首尾端点
            pline = inter.asPolyline()
            if pline:
                pts.append(pline[0])
                if len(pline) > 1:
                    pts.append(pline[-1])
        elif wkb_type is not None:
            # MultiPoint / GeometryCollection
            try:
                coll = inter.asGeometryCollection()
                for g in coll:
                    if hasattr(g, 'asPoint'):
                        p = g.asPoint()
                        pts.append(QgsPointXY(p.x(), p.y()))
            except Exception:
                pass
        else:
            # 尝试 asMultiPoint
            try:
                mp = inter.asMultiPoint()
                for p in mp:
                    pts.append(QgsPointXY(p.x(), p.y()))
            except Exception:
                pass

        if not pts:
            return []

        # 去重
        total_len = pipe_geom.length()
        if total_len <= 0:
            return []
        line = pipe_geom.asPolyline()
        if len(line) < 2:
            return []

        positions = []
        seen = set()
        for pt in pts:
            key = (round(pt.x(), 8), round(pt.y(), 8))
            if key in seen:
                continue
            seen.add(key)
            pos = self._point_position_on_line(line, total_len, pt)
            if pos is not None:
                positions.append(pos)

        positions.sort()
        return positions

    def _find_pipe_layer(self):
        from .layer_utils import find_layer
        return find_layer(QgsProject.instance(), "aqd_pipes")

    def _hit_test(self, feat, point, tolerance):
        """检测点是否命中管道，返回 (dist, feat, position) 或 None"""
        geom = feat.geometry()
        if not geom:
            return None
        line = geom.asPolyline()
        if len(line) < 2:
            return None
        total_len = geom.length()
        if total_len <= 0:
            return None
        best_dist = tolerance
        best_feat = feat
        best_pos = 0.0
        hit = False

        for i in range(len(line) - 1):
            seg = QgsGeometry.fromPolylineXY([line[i], line[i + 1]])
            dist = seg.distance(QgsGeometry.fromPointXY(point))
            if dist < best_dist:
                best_dist = dist
                hit = True
                cum = 0
                for j in range(i):
                    cum += line[j].distance(line[j + 1])
                seg_len = line[i].distance(line[i + 1])
                if seg_len > 0:
                    ratio = min(max(line[i].distance(point) / seg_len, 0.01), 0.99)
                    cum += seg_len * ratio
                    best_pos = cum / total_len
        if hit:
            return (best_dist, best_feat, best_pos)
        return None

    def _point_position_on_line(self, line, total_len, point):
        """计算点在折线上的沿线比例(0~1)，不在线上返回 None"""
        best_dist = self.canvas.mapUnitsPerPixel() * 3
        best_pos = None
        cum = 0.0
        for i in range(len(line) - 1):
            seg = QgsGeometry.fromPolylineXY([line[i], line[i + 1]])
            dist = seg.distance(QgsGeometry.fromPointXY(point))
            if dist < best_dist:
                best_dist = dist
                seg_len = line[i].distance(line[i + 1])
                if seg_len > 0:
                    dot = ((point.x() - line[i].x()) * (line[i + 1].x() - line[i].x()) +
                           (point.y() - line[i].y()) * (line[i + 1].y() - line[i].y())) / (seg_len * seg_len)
                    r = max(0.001, min(0.999, dot))
                    best_pos = (cum + seg_len * r) / total_len
            cum += line[i].distance(line[i + 1])
        return best_pos
