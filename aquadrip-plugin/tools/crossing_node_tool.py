"""CrossingNodeGenerator — 支管与毛管交叉节点生成器

手动绘制范式下，干管/支管由用户在 QGIS 中用"添加线要素"绘制。
本工具处理其中的关键一步：用户选中一条支管后，自动检测该支管与
所有毛管（pipe_type=lateral）的几何交叉点，并在 aqd_nodes 图层
写入 node_type=junction 的点要素作为连接标记。

说明（与 DEVELOPMENT_PLAN.md 7.3.3 的关系）：
- 这里实现的是"只生成交叉节点、不打断毛管"的简化版本
- 文档 Case B（在交叉点切断毛管为两段）不在本次范围
- 交叉节点暂不回写 from_node/to_node（待 SyncManager 接线）
"""

from typing import List, Optional

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsGeometry, QgsPointXY,
    QgsFeature, QgsWkbTypes,
)


class CrossingNodeGenerator:
    """支管↔毛管交叉节点生成器"""

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()

    def generate(self, submain_feature: QgsFeature) -> int:
        """为选中的支管生成与所有毛管的交叉节点

        Args:
            submain_feature: aqd_pipes 中选中的支管要素（pipe_type=submain）

        Returns:
            生成的交叉节点数量

        Raises:
            RuntimeError: 图层未初始化 / 几何为空
        """
        submain_geom = submain_feature.geometry()
        if not submain_geom or submain_geom.isEmpty():
            raise RuntimeError("选中支管的几何为空")

        pipes = self._find_pipes_layer()
        nodes = self._find_nodes_layer()
        if pipes is None:
            raise RuntimeError("未找到 aqd_pipes 图层，请先初始化图层")
        if nodes is None:
            raise RuntimeError("未找到 aqd_nodes 图层，请先初始化图层")

        # 1. 求支管与所有毛管的几何交点
        #    （含支管端点与毛管近似接触的容差补偿，见 _endpoint_snap_points）
        connect_tol = self._connect_tolerance(nodes)
        crossing_points: List[QgsPointXY] = []
        for feat in pipes.getFeatures():
            if str(feat.attribute("pipe_type") or "") != "lateral":
                continue
            lat_geom = feat.geometry()
            if not lat_geom or lat_geom.isEmpty():
                continue
            inter = submain_geom.intersection(lat_geom)
            crossing_points.extend(self._extract_points(inter))
            crossing_points.extend(
                self._endpoint_snap_points(submain_geom, lat_geom, connect_tol))

        if not crossing_points:
            self.iface.messageBar().pushMessage(
                "aQuaDrip", "未检测到支管与毛管的交叉点", level=1, duration=4)
            return 0

        # 2. 容差去重（本次计算的交叉点内部去重）
        tol = self._dedup_tolerance(nodes)
        crossing_points = self._dedupe(crossing_points, tol)

        # 3. 过滤 aqd_nodes 中已存在的节点
        #    （重复点击同一支管、或不同支管在同一毛管位置交叉时不重复生成）
        existing = self._existing_node_points(nodes)
        crossing_points = [
            p for p in crossing_points
            if not any(self._is_near(p, e, tol) for e in existing)
        ]

        if not crossing_points:
            self.iface.messageBar().pushMessage(
                "aQuaDrip", "交叉节点均已存在，未生成新节点", level=1, duration=4)
            return 0

        # 3. 写入 aqd_nodes
        written = self._write_nodes(nodes, crossing_points)
        nodes.triggerRepaint()
        self.iface.messageBar().pushMessage(
            "aQuaDrip", f"已生成 {written} 个交叉节点", level=0, duration=4)
        return written

    # ── 几何辅助 ──

    @staticmethod
    def _extract_points(geom: QgsGeometry) -> List[QgsPointXY]:
        """从交点几何提取点坐标

        intersection() 对两条线的相交可能返回：
        - Point / MultiPoint：正常交叉点（含端点接触）
        - GeometryCollection：端点接触 + 局部共线时的混合结果（递归提取其中的点）
        - LineString：共线段，不算"交叉点"，跳过
        """
        if geom is None or geom.isEmpty() or geom.isNull():
            return []
        flat = QgsWkbTypes.flatType(geom.wkbType())
        if flat == QgsWkbTypes.Point:
            p = geom.asPoint()
            return [QgsPointXY(p.x(), p.y())] if not p.isEmpty() else []
        if flat == QgsWkbTypes.MultiPoint:
            return [QgsPointXY(pt.x(), pt.y()) for pt in geom.asMultiPoint()]
        if flat == QgsWkbTypes.GeometryCollection:
            pts: List[QgsPointXY] = []
            for part in geom.asGeometryCollection():
                pts.extend(CrossingNodeGenerator._extract_points(part))
            return pts
        # LineString（共线）/ Polygon 等不作为节点
        return []

    @staticmethod
    def _connect_tolerance(layer: QgsVectorLayer) -> float:
        """支管端点与毛管的连接容差

        应大于去重容差，用于容忍 snapping 后的浮点误差和轻微未对准。
        投影坐标系 0.1m，地理坐标系 1e-6 度（约 0.11m）。
        """
        if layer.crs().isGeographic():
            return 1e-6
        return 0.1

    @staticmethod
    def _submain_endpoints(geom: QgsGeometry) -> List[QgsPointXY]:
        """获取支管折线的两个端点（支持单线与多线）"""
        if geom.isMultipart():
            parts = geom.asMultiPolyline()
            if not parts:
                return []
            endpoints: List[QgsPointXY] = []
            first, last = parts[0], parts[-1]
            if first:
                endpoints.append(first[0])
            if last:
                endpoints.append(last[-1])
            return endpoints
        line = geom.asPolyline()
        if len(line) < 2:
            return []
        return [line[0], line[-1]]

    @staticmethod
    def _endpoint_snap_points(submain_geom: QgsGeometry,
                              lat_geom: QgsGeometry,
                              tol: float) -> List[QgsPointXY]:
        """端点容差补偿：支管端点与毛管距离在容差内时，
        返回端点在毛管上的投影点作为交叉节点。

        解决 intersection() 在端点接触时因浮点精度返回空、
        或返回 GeometryCollection/LineString 被过滤导致的端点节点缺失。
        """
        pts: List[QgsPointXY] = []
        for ep in CrossingNodeGenerator._submain_endpoints(submain_geom):
            ep_geom = QgsGeometry.fromPointXY(ep)
            if lat_geom.distance(ep_geom) <= tol:
                # nearestPoint 返回 QgsGeometry，需 asPoint() 转为 QgsPointXY
                snap_geom = lat_geom.nearestPoint(ep_geom)
                if snap_geom is None or snap_geom.isEmpty():
                    continue
                snap = snap_geom.asPoint()
                if not snap.isEmpty():
                    pts.append(QgsPointXY(snap.x(), snap.y()))
        return pts

    @staticmethod
    def _is_near(p: QgsPointXY, q: QgsPointXY, tol: float) -> bool:
        """两点是否在容差内（矩形距离，与 _dedupe 一致）"""
        return abs(p.x() - q.x()) <= tol and abs(p.y() - q.y()) <= tol

    @classmethod
    def _dedupe(cls, points: List[QgsPointXY], tol: float) -> List[QgsPointXY]:
        """按容差去重（O(n²)，节点数通常很小）"""
        result: List[QgsPointXY] = []
        for p in points:
            if any(cls._is_near(p, q, tol) for q in result):
                continue
            result.append(p)
        return result

    @staticmethod
    def _existing_node_points(nodes_layer: QgsVectorLayer) -> List[QgsPointXY]:
        """读取 aqd_nodes 中所有已存在节点的坐标（用于重复过滤）"""
        pts: List[QgsPointXY] = []
        for feat in nodes_layer.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty() or geom.isNull():
                continue
            if geom.type() != QgsWkbTypes.PointGeometry:
                continue
            if geom.isMultipart():
                pts.extend(geom.asMultiPoint())
            else:
                p = geom.asPoint()
                if not p.isEmpty():
                    pts.append(p)
        return pts

    @staticmethod
    def _dedup_tolerance(nodes_layer: QgsVectorLayer) -> float:
        """根据图层 CRS 选择去重容差

        投影坐标系（米）用 0.01m，地理坐标系（度）用 1e-6 度。
        """
        crs = nodes_layer.crs()
        if crs.isGeographic():
            return 1e-6
        return 0.01

    # ── 图层写入 ──

    def _write_nodes(self, nodes: QgsVectorLayer,
                     points: List[QgsPointXY]) -> int:
        """把交叉点写入 aqd_nodes，返回写入数量"""
        nodes.startEditing()
        count = 0
        try:
            for pt in points:
                feat = QgsFeature(nodes.fields())
                feat.setGeometry(QgsGeometry.fromPointXY(pt))
                feat.setAttribute("node_type", "junction")
                if not nodes.addFeature(feat):
                    self.iface.messageBar().pushWarning(
                        "aQuaDrip", "添加交叉节点失败")
                    nodes.rollBack()
                    return count
                count += 1
            nodes.commitChanges()
        except Exception:
            nodes.rollBack()
            raise
        return count

    # ── 图层查找（与 trim_tool.py 一致的按 source 匹配模式）──

    def _find_pipes_layer(self) -> Optional[QgsVectorLayer]:
        return self._find_layer("aqd_pipes")

    def _find_nodes_layer(self) -> Optional[QgsVectorLayer]:
        return self._find_layer("aqd_nodes")

    def _find_layer(self, keyword: str) -> Optional[QgsVectorLayer]:
        for layer in self.project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            s = layer.source() if hasattr(layer, "source") else ""
            if keyword in s:
                return layer
        return None
