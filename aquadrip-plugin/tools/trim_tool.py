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
                    point = event.snapPoint()
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
            tolerance = self.canvas.mapUnitsPerPixel() * 15

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
            self._do_split(layer, best_feat, [best_pos])
            if need_edit and not layer.commitChanges():
                raise RuntimeError(QApplication.translate("TrimTool", "提交失败: {0}").format('; '.join(layer.commitErrors())))
        except Exception as e:
            if need_edit:
                layer.rollBack()
            self.iface.messageBar().pushWarning("aQuaDrip", QApplication.translate("TrimTool", "切割失败: {0}").format(e))
            return
        layer.triggerRepaint()
        self.iface.messageBar().pushMessage(
            "aQuaDrip", QApplication.translate("TrimTool", "管道已切割"), level=0, duration=3)

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

                if len(positions) == 1:
                    count = self._do_split(layer, feat, positions)
                else:
                    # 多个交点：传入全部位置，一次性处理
                    count = self._do_split(layer, feat, positions)

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
        self.iface.messageBar().pushMessage(
            "aQuaDrip", QApplication.translate("TrimTool", "已切割 {0} 根管道").format(total_cut), level=0, duration=4)

    def _do_split(self, layer, feat, positions) -> int:
        """在管道指定位置(0~1)处分割并写入图层，返回生成段数

        positions: 沿线位置比例列表（已排序去重）
        注意：调用者负责管理编辑会话（startEditing/commitChanges）
        """
        geom = feat.geometry()
        line = geom.asPolyline()
        total_len = geom.length()

        # 切割长度是米，而 geom.length() 是图层单位（经纬度=度）。
        # 必须先用椭球度量把米换算成沿线比例，否则"2m"会按图层单位
        # 理解：经纬度下 1m/0.0008° ≈ 1250 → 钳位到 0.01~0.99 →
        # 整根管道被切除（远超设定长度）
        half_frac = 0.0
        if self.cut_length > 0:
            total_len_m = self._length_meters(layer, line)
            if total_len_m > 0:
                half_frac = (self.cut_length / 2) / total_len_m

        # 计算所有切割位置
        if half_frac <= 0:
            cut_positions = positions
        else:
            cut_positions = []
            for pos in positions:
                p1 = max(0.01, pos - half_frac)
                p2 = min(0.99, pos + half_frac)
                if p2 - p1 > 0.005:
                    cut_positions.extend([p1, p2])
                else:
                    cut_positions.append(pos)

        segments = self._split_polyline(line, total_len, cut_positions)

        # cut_length > 0：移除切除区间内的段
        if half_frac > 0:
            # 构建切除区间 [(p1, p2), ...]
            remove_zones = []
            for pos in positions:
                p1 = max(0.01, pos - half_frac)
                p2 = min(0.99, pos + half_frac)
                if p2 - p1 > 0.005:
                    remove_zones.append((p1, p2))

            if remove_zones:
                # 计算每段的中间位置，判断是否在切除区间内
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
            return 0

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

        return len(segments)

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

    @staticmethod
    def _length_meters(layer, line) -> float:
        """折线的椭球长度（米）——任何 CRS 下都返回米

        geom.length() 是图层单位（经纬度=度），与 UI 的米制切割长度
        不可直接混算。椭球度量在经纬度下按 WGS84 椭球精确换算，
        且东西向自动考虑纬度收缩（cos φ），无 x/y 比例失真。
        椭球不可用时兜底平面长度近似（经纬度 1°≈111km）。
        """
        try:
            from qgis.core import QgsDistanceArea, QgsProject
            da = QgsDistanceArea()
            crs = layer.crs() if layer is not None else None
            if crs is not None and crs.isValid():
                da.setSourceCrs(crs, QgsProject.instance().transformContext())
            da.setEllipsoid("WGS84")
            m = float(da.measureLine(line) or 0)
            if m > 0:
                return m
        except Exception:
            import traceback
            traceback.print_exc()
        # 兜底：平面长度 × 单位换算
        planar = QgsGeometry.fromPolylineXY(line).length()
        if layer is not None and layer.crs().isValid() and layer.crs().isGeographic():
            return planar * 111320.0
        return planar

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
