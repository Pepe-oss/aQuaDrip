"""CrossingNodeGenerator — 管道连接节点生成器

手动绘制范式下，干管/支管/毛管由用户在 QGIS 中绘制。
本工具：用户选中一条管道后，自动检测该管道与**所有不同类型管道**的交叉点，
并在 aqd_nodes 图层写入 node_type=junction 的点要素作为连接节点。

检测的交叉类型：
  - 端点落在线上（T 型）：管道 A 端点距管道 B 中心线 < 容差
  - 真交叉（X 型）：两条管道几何相交

连接节点在**所有类型**的管道之间生成（含同类型）：
  - mainline ↔ submain ✅
  - mainline ↔ lateral ✅
  - submain ↔ lateral ✅
  - submain ↔ submain ✅（并列支管、环状干管需连接）
"""

from typing import List, Optional

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsGeometry, QgsPointXY,
    QgsFeature, QgsWkbTypes,
)


class CrossingNodeGenerator:
    """管道连接节点生成器（全类型交叉检测）"""

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()

    def generate(self, selected_feature: QgsFeature) -> int:
        """为选中的管道生成与所有其他管道（含同类型）的连接节点

        Args:
            selected_feature: aqd_pipes 中选中的管道要素（任意 pipe_type）

        Returns:
            生成的连接节点数量

        Raises:
            RuntimeError: 图层未初始化 / 几何为空
        """
        sel_geom = selected_feature.geometry()
        if not sel_geom or sel_geom.isEmpty():
            raise RuntimeError("选中管道的几何为空")

        pipes = self._find_pipes_layer()
        nodes = self._find_nodes_layer()
        if nodes is None:
            raise RuntimeError("未找到 aqd_nodes 图层，请先初始化图层")

        all_link_layers = self._all_link_layers()
        if not all_link_layers:
            raise RuntimeError("未找到 aqd_pipes/aqd_pumps/aqd_valves 图层，请先初始化图层")

        # 阀门/水泵图层没有 pipe_type 字段，用图层名推断
        sel_layer = self._find_layer_for_feature(selected_feature)
        if sel_layer is not None:
            src = sel_layer.source() or ""
            if "aqd_pumps" in src:
                sel_type = "pump"
            elif "aqd_valves" in src:
                sel_type = "valve"
        sel_id = selected_feature.id()

        # 1. 遍历所有 link 图层中的所有要素，求交叉点
        connect_tol = self._connect_tolerance(nodes)
        crossing_points: List[QgsPointXY] = []

        for link_layer in all_link_layers:
            for feat in link_layer.getFeatures():
                # 跳过自身（同图层+同 fid）
                if feat.id() == sel_id:
                    continue

                other_geom = feat.geometry()
                if not other_geom or other_geom.isEmpty():
                    continue

                inter = sel_geom.intersection(other_geom)
                crossing_points.extend(self._extract_points(inter))

                crossing_points.extend(
                    self._endpoint_snap_points(sel_geom, other_geom, connect_tol))
                crossing_points.extend(
                    self._endpoint_snap_points(other_geom, sel_geom, connect_tol))

        if not crossing_points:
            self.iface.messageBar().pushMessage(
                "aQuaDrip",
                f"未检测到 {sel_type} 与其他类型管道的交叉点",
                level=1, duration=4)
            return 0

        # 2. 容差去重
        tol = self._dedup_tolerance(nodes)
        crossing_points = self._dedupe(crossing_points, tol)

        # 3. 过滤 aqd_nodes 中已存在的节点
        existing = self._existing_node_points(nodes)
        crossing_points = [
            p for p in crossing_points
            if not any(self._is_near(p, e, tol) for e in existing)
        ]

        if not crossing_points:
            self.iface.messageBar().pushMessage(
                "aQuaDrip", "连接节点均已存在，未生成新节点",
                level=1, duration=4)
            return 0

        # 4. 写入 aqd_nodes
        written = self._write_nodes(nodes, crossing_points)
        nodes.triggerRepaint()
        self.iface.messageBar().pushMessage(
            "aQuaDrip", f"已生成 {written} 个连接节点", level=0, duration=4)
        return written

    # ── 几何辅助 ──

    @staticmethod
    def _extract_points(geom: QgsGeometry) -> List[QgsPointXY]:
        """从交点几何提取点坐标

        intersection() 对两条线的相交可能返回：
        - Point / MultiPoint：正常交叉点（含端点接触）
        - GeometryCollection：端点接触 + 局部共线时的混合结果（递归提取）
        - LineString：共线段，不算交叉点，跳过
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
        return []

    @staticmethod
    def _connect_tolerance(layer: QgsVectorLayer) -> float:
        """端点连接容差：投影坐标 0.1m，地理坐标 1e-6°"""
        if layer.crs().isGeographic():
            return 1e-6
        return 0.1

    @staticmethod
    def _line_endpoints(geom: QgsGeometry) -> List[QgsPointXY]:
        """获取折线的两个端点（支持单线与多线）"""
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
    def _endpoint_snap_points(pipe_a: QgsGeometry,
                              pipe_b: QgsGeometry,
                              tol: float) -> List[QgsPointXY]:
        """端点容差补偿：管道 A 的端点距管道 B < 容差时，
        返回端点在管道 B 上的投影点作为连接节点。

        解决 intersection() 在端点接触时因浮点精度返回空的情况。
        """
        pts: List[QgsPointXY] = []
        for ep in CrossingNodeGenerator._line_endpoints(pipe_a):
            ep_geom = QgsGeometry.fromPointXY(ep)
            if pipe_b.distance(ep_geom) <= tol:
                snap_geom = pipe_b.nearestPoint(ep_geom)
                if snap_geom is None or snap_geom.isEmpty():
                    continue
                snap = snap_geom.asPoint()
                if not snap.isEmpty():
                    pts.append(QgsPointXY(snap.x(), snap.y()))
        return pts

    @staticmethod
    def _is_near(p: QgsPointXY, q: QgsPointXY, tol: float) -> bool:
        return abs(p.x() - q.x()) <= tol and abs(p.y() - q.y()) <= tol

    @classmethod
    def _dedupe(cls, points: List[QgsPointXY], tol: float) -> List[QgsPointXY]:
        result: List[QgsPointXY] = []
        for p in points:
            if any(cls._is_near(p, q, tol) for q in result):
                continue
            result.append(p)
        return result

    @staticmethod
    def _existing_node_points(nodes_layer: QgsVectorLayer) -> List[QgsPointXY]:
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
        if nodes_layer.crs().isGeographic():
            return 1e-6
        return 0.01

    # ── 图层写入 ──

    def _write_nodes(self, nodes: QgsVectorLayer,
                     points: List[QgsPointXY]) -> int:
        nodes.startEditing()
        count = 0
        try:
            for pt in points:
                feat = QgsFeature(nodes.fields())
                feat.setGeometry(QgsGeometry.fromPointXY(pt))
                feat.setAttribute("node_type", "junction")
                if not nodes.addFeature(feat):
                    self.iface.messageBar().pushWarning(
                        "aQuaDrip", "添加连接节点失败")
                    nodes.rollBack()
                    return count
                count += 1
            nodes.commitChanges()
        except Exception:
            nodes.rollBack()
            raise
        return count

    # ── 图层查找 ──

    def _find_pipes_layer(self) -> Optional[QgsVectorLayer]:
        return self._find_layer("aqd_pipes")

    def _find_pumps_layer(self) -> Optional[QgsVectorLayer]:
        return self._find_layer("aqd_pumps")

    def _find_valves_layer(self) -> Optional[QgsVectorLayer]:
        return self._find_layer("aqd_valves")

    def _all_link_layers(self) -> List[QgsVectorLayer]:
        """返回项目中所有 link 图层（管道/水泵/阀门）。"""
        layers = []
        for key in ("aqd_pipes", "aqd_pumps", "aqd_valves"):
            ly = self._find_layer(key)
            if ly is not None:
                layers.append(ly)
        return layers

    def _find_nodes_layer(self) -> Optional[QgsVectorLayer]:
        return self._find_layer("aqd_nodes")

    def _find_layer_for_feature(self, feat: QgsFeature) -> Optional[QgsVectorLayer]:
        """根据要素 fid 反查所属 link 图层。"""
        target_fid = feat.id()
        for key in ("aqd_pipes", "aqd_pumps", "aqd_valves"):
            ly = self._find_layer(key)
            if ly is None:
                continue
            for f in ly.getFeatures():
                if f.id() == target_fid:
                    return ly
        return None

    def _find_layer(self, keyword: str) -> Optional[QgsVectorLayer]:
        for layer in self.project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            s = layer.source() if hasattr(layer, "source") else ""
            if keyword in s:
                return layer
        return None
