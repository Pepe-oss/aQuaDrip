"""TopologyBuilder — 几何相交驱动的统一拓扑构建器

替代旧的 _planarize + _match_node + _split_line 三件套。

核心原则：拓扑关系由几何直接确定，不经坐标匹配。

流程：
  A. 节点空间索引
  B. 管道端点 snap 到节点（容差内自动连接）
  C. 管道-管道交叉检测（受层级规则约束）→ 在合法交叉点切断
  D. 建立 DripNetwork 拓扑（节点 ID 引用，坐标统一）
"""

from typing import Dict, List, Optional, Tuple

from qgis.core import (
    QgsSpatialIndex, QgsFeature, QgsGeometry, QgsPointXY,
    QgsVectorLayer, QgsWkbTypes,
)


# ── 管道层级规则 ──
# 只有相邻层级（或同级）的管道才允许在交叉点建立连接。
# 这确保了水流的层级结构：水源 → 主管 → 支管 → 毛管。
# 跨级交叉（如主管×毛管视觉相交）被完全忽略，不生成节点、不切断管道。

PIPE_LEVELS = {"mainline": 0, "submain": 1, "lateral": 2}

# 节点级别 → node_type 映射（CrossingNodeGenerator 按选中管道层级写入）
NODE_TYPE_BY_PIPE = {
    "mainline": "main_junction",
    "submain": "sub_junction",
    "lateral": "lateral_junction",
}


def can_connect(type_a: str, type_b: str) -> bool:
    """判断两种管道类型是否允许在交叉点建立连接

    规则：只有相邻层级或同级的管道可以连接（|level_a - level_b| ≤ 1）。
    例如 mainline×submain 允许，mainline×lateral 不允许。

    未知类型（空值/自定义值）不阻断连接，保持向后兼容。
    """
    la = PIPE_LEVELS.get(type_a)
    lb = PIPE_LEVELS.get(type_b)
    if la is None or lb is None:
        return True
    return abs(la - lb) <= 1


class TopologyBuilder:
    """几何相交驱动的统一拓扑构建器"""

    def __init__(self, net, crs_is_geographic: bool):
        self.net = net
        # 统一容差：投影 1cm，经纬度 1e-6°
        self.tol = 1e-6 if crs_is_geographic else 0.01
        self._node_counter = 0

    def build(self, node_features: List[QgsFeature],
              pipe_features: List[QgsFeature],
              pump_features: List[QgsFeature] = None,
              valve_features: List[QgsFeature] = None) -> List[dict]:
        """构建完整拓扑

        Args:
            node_features: aqd_nodes 图层的要素列表
            pipe_features: aqd_pipes 图层的要素列表
            pump_features: aqd_pumps 图层的要素列表（可选）
            valve_features: aqd_valves 图层的要素列表（可选）

        Returns:
            segments 列表 [{fid, lid, pipe_type, device, pts,
                           from_node, to_node}]
        """
        # 阶段 A: 节点 → net.nodes + 空间索引
        self._build_nodes(node_features)

        # 阶段 B: 管道预处理 → 收集所有 link 记录
        pipe_records = self._collect_links(
            pipe_features, device="none", default_pipe_type=None, lid_prefix="L")
        pump_records = self._collect_links(
            pump_features or [], device="pump", default_pipe_type="mainline", lid_prefix="PU")
        valve_records = self._collect_links(
            valve_features or [], device="valve", default_pipe_type="mainline", lid_prefix="V")
        all_records = pipe_records + pump_records + valve_records

        # 阶段 C: 管道-管道交叉检测 + 切断
        segments = self._detect_and_split(all_records)

        # 阶段 D: 端点 snap + 建立拓扑引用
        segments = self._assign_endpoints(segments)

        return segments

    # ── 阶段 A: 节点 ──

    def _build_nodes(self, node_features: List[QgsFeature]):
        """读取节点到 net.nodes，构建空间索引"""
        from wdrip.network import SourceNode, Junction

        self._node_index = QgsSpatialIndex()
        self._node_coords = {}  # {node_id: (x, y)}
        self._coord_to_node = {}  # {(x, y): node_id}
        self._fid_to_nid = {}  # {qgs_fid: node_id} 空间索引反查用

        for feat in node_features:
            geom = feat.geometry()
            if not geom or geom.isEmpty():
                continue
            pt = geom.asPoint()
            # 安全读取 id: aqd_nodes 无 id 字段，用 fid 兜底
            nid = self._safe_attr_str(feat, "id", f"N{feat.id()}")
            node_type = self._safe_attr_str(feat, "node_type", "junction")
            elev = self._safe_attr(feat, "elevation", 0)
            source_type = self._safe_attr_str(feat, "source_type", "well")
            head = self._safe_attr(feat, "head", 0)
            available_flow = self._safe_attr(feat, "available_flow", 0)

            if node_type == "source":
                node = SourceNode(
                    nid, pt.x(), pt.y(), elevation=elev,
                    source_type=source_type,
                    head=head,
                    available_flow=available_flow)
            else:
                node = Junction(nid, pt.x(), pt.y(), elevation=elev)

            self.net.add_node(node)
            self._node_coords[nid] = (pt.x(), pt.y())
            self._coord_to_node[self._key(pt.x(), pt.y())] = nid

            # 空间索引
            idx_feat = QgsFeature(feat.id())
            idx_feat.setGeometry(QgsGeometry.fromPointXY(pt))
            self._node_index.addFeature(idx_feat)
            self._fid_to_nid[feat.id()] = nid

    # ── 阶段 B: link 收集 ──

    def _collect_links(self, features: List[QgsFeature],
                        device: str = "none",
                        default_pipe_type: Optional[str] = None,
                        lid_prefix: str = "L") -> List[dict]:
        """收集 link 记录（管道 / 水泵 / 阀门通用）

        Args:
            features: 图层要素列表
            device: 设备类型（"none"/"pump"/"valve"）
            default_pipe_type: pipe_type 回退值。None 表示从 feature 读取
            lid_prefix: 默认 link ID 前缀。区分图层避免 FID 冲突
                         ("L"=管道, "PU"=水泵, "V"=阀门)
        """
        records = []
        for feat in features:
            geom = feat.geometry()
            if not geom or geom.isEmpty():
                continue
            line = geom.asPolyline()
            if len(line) < 2:
                continue
            fid = feat.id()
            # 优先读自定义 id 字段，否则用前缀+fid（各图层FID独立，不用前缀会冲突）
            lid = self._safe_attr_str(feat, "id", f"{lid_prefix}{fid}")
            pt = self._safe_attr_str(feat, "pipe_type", default_pipe_type or "mainline")
            records.append({
                "fid": fid,
                "lid": lid,
                "geom": geom,
                "line": line,
                "pipe_type": pt,
                "device": device,
                "feat": feat,
            })
        return records

    # ── 阶段 C: 交叉检测 + 切断 ──

    def _detect_and_split(self, records: List[dict]) -> List[dict]:
        """检测不同 pipe_type 管道之间的交叉，在交叉点切断

        Returns:
            segments 列表（每段含 pts 几何）
        """
        all_segments = []

        for rec in records:
            line = rec["line"]
            my_type = rec["pipe_type"]

            # 找所有其他管道的交叉点（受层级规则约束）
            crossing_points = []
            for other in records:
                if other["fid"] == rec["fid"]:
                    continue
                other_type = other["pipe_type"]
                if not other_type:
                    continue  # 跳过类型缺失的管道

                # 层级约束：跨级组合（如 mainline×lateral）不建立连接。
                # 但设备（水泵/阀门）可连接任意层级——它们是受控连接点，
                # 不受管道层级规则限制。
                my_is_device = rec.get("device") in ("pump", "valve")
                other_is_device = other.get("device") in ("pump", "valve")
                if not (my_is_device or other_is_device):
                    if not can_connect(my_type, other_type):
                        continue

                inter = rec["geom"].intersection(other["geom"])
                pts = self._extract_points(inter)
                crossing_points.extend(pts)

                # T 型：另一管道端点落在当前管道上
                for ep in [other["line"][0], other["line"][-1]]:
                    ep_geom = QgsGeometry.fromPointXY(ep)
                    if rec["geom"].distance(ep_geom) <= self.tol:
                        snap = rec["geom"].nearestPoint(ep_geom)
                        if snap and not snap.isEmpty():
                            sp = snap.asPoint()
                            if not sp.isEmpty():
                                crossing_points.append(
                                    QgsPointXY(sp.x(), sp.y()))
                # T 型：当前管道端点落在另一管道上
                for ep in [line[0], line[-1]]:
                    ep_geom = QgsGeometry.fromPointXY(ep)
                    if other["geom"].distance(ep_geom) <= self.tol:
                        snap = other["geom"].nearestPoint(ep_geom)
                        if snap and not snap.isEmpty():
                            sp = snap.asPoint()
                            if not sp.isEmpty():
                                crossing_points.append(
                                    QgsPointXY(sp.x(), sp.y()))

            if not crossing_points:
                all_segments.append({
                    **rec, "part": 0, "pts": line,
                    "from_node": None, "to_node": None,
                })
                continue

            # 按沿线累积长度排序、去重
            sorted_pts = self._sort_along_line(crossing_points, line)

            # 切段（保留折线顶点）
            parts = self._split_at_points(line, sorted_pts)
            for i, pts in enumerate(parts):
                if len(pts) < 2:
                    continue
                seg_len = QgsGeometry.fromPolylineXY(pts).length()
                if seg_len < self.tol:
                    continue
                all_segments.append({
                    **rec, "part": i, "pts": pts,
                    "from_node": None, "to_node": None,
                })

        return all_segments

    def _sort_along_line(self, points: List[QgsPointXY],
                          line: List[QgsPointXY]) -> List[QgsPointXY]:
        """把交叉点按沿线位置排序并去重"""
        total = QgsGeometry.fromPolylineXY(line).length()
        if total <= 0:
            return []

        # 计算每个点的沿线累积位置
        positioned = []
        for pt in points:
            cum = self._project_onto_line(pt, line)
            if cum is not None:
                positioned.append((cum, pt))

        positioned.sort(key=lambda x: x[0])

        # 去重（间距 < tol 的合并）
        deduped = []
        for cum, pt in positioned:
            if deduped and abs(cum - deduped[-1][0]) < self.tol:
                continue
            # 排除太靠近端点的（端点由 snap 处理）
            if cum < self.tol or cum > total - self.tol:
                continue
            deduped.append((cum, pt))

        return [pt for _, pt in deduped]

    def _project_onto_line(self, pt: QgsPointXY,
                            line: List[QgsPointXY]) -> Optional[float]:
        """计算点到折线的沿线累积位置"""
        pt_geom = QgsGeometry.fromPointXY(pt)
        cum = 0.0
        for i in range(len(line) - 1):
            seg_len = line[i].distance(line[i + 1])
            if seg_len > 0:
                seg_geom = QgsGeometry.fromPolylineXY([line[i], line[i + 1]])
                if seg_geom.distance(pt_geom) <= self.tol:
                    r = line[i].distance(pt) / seg_len
                    r = max(0.0, min(1.0, r))
                    return cum + seg_len * r
            cum += seg_len
        return None

    def _split_at_points(self, line: List[QgsPointXY],
                          split_pts: List[QgsPointXY]) -> List[List[QgsPointXY]]:
        """在指定点处把折线拆为多段（保留中间顶点）"""
        if not split_pts:
            return [line]

        # 计算总长和各段长度
        seg_lens = [line[i].distance(line[i + 1])
                    for i in range(len(line) - 1)]
        total = sum(seg_lens)

        # 把分割点按沿线累积位置排序
        positioned = []
        for sp in split_pts:
            cum = self._project_onto_line(sp, line)
            if cum is not None and self.tol < cum < total - self.tol:
                positioned.append(cum)
        positioned.sort()

        if not positioned:
            return [line]

        # 沿折线遍历，在分割点处截断
        parts = []
        current = [line[0]]
        cum = 0.0
        pi = 0  # 分割点索引
        for i in range(len(line) - 1):
            seg_end = line[i + 1]
            seg_len = seg_lens[i]
            cum += seg_len

            # 处理当前段内的所有分割点
            while pi < len(positioned) and positioned[pi] <= cum + 1e-10:
                dist_in_seg = positioned[pi] - (cum - seg_len)
                if dist_in_seg >= -1e-10:
                    r = max(0.0, min(1.0, dist_in_seg / seg_len)) if seg_len > 0 else 0
                    sp = QgsPointXY(
                        line[i].x() + (seg_end.x() - line[i].x()) * r,
                        line[i].y() + (seg_end.y() - line[i].y()) * r)
                    current.append(sp)
                    parts.append(current)
                    current = [sp]
                pi += 1

            current.append(seg_end)

        if len(current) >= 2:
            parts.append(current)

        return [p for p in parts if len(p) >= 2]

    # ── 阶段 D: 端点 snap + 拓扑引用 ──

    def _assign_endpoints(self, segments: List[dict]) -> List[dict]:
        """为每段的端点分配节点 ID（snap 到已有节点或创建新节点）"""
        from wdrip.network import Junction

        for seg in segments:
            pts = seg["pts"]
            seg["from_node"] = self._snap_or_create(pts[0])
            seg["to_node"] = self._snap_or_create(pts[-1])

        return segments

    def _snap_or_create(self, pt: QgsPointXY) -> str:
        """snap 到最近节点（容差内），否则创建新 Junction"""
        from wdrip.network import Junction
        # 先精确匹配
        key = self._key(pt.x(), pt.y())
        if key in self._coord_to_node:
            return self._coord_to_node[key]

        # 空间索引最近搜索：nearestNeighbor 返回 QGIS feature id，
        # 通过 _fid_to_nid 反查 node_id，校验距离后返回。
        tol = self.tol * 10  # 端点 snap 容差稍大
        for qgs_fid in self._node_index.nearestNeighbor(pt, 1):
            nid = self._fid_to_nid.get(qgs_fid)
            if nid is None:
                continue
            nx, ny = self._node_coords[nid]
            if ((nx - pt.x()) ** 2 + (ny - pt.y()) ** 2) ** 0.5 < tol:
                return nid

        # 创建新节点（用自增计数器，避免 len(net.nodes) 在节点增删后 ID 重用冲突）
        new_id = f"auto_N{self._node_counter}"
        self._node_counter += 1
        node = Junction(new_id, pt.x(), pt.y())
        self.net.add_node(node)
        self._node_coords[new_id] = (pt.x(), pt.y())
        self._coord_to_node[self._key(pt.x(), pt.y())] = new_id
        return new_id

    # ── 几何辅助 ──

    @staticmethod
    def _extract_points(geom: QgsGeometry) -> List[QgsPointXY]:
        """从交点几何提取点坐标"""
        if geom is None or geom.isEmpty() or geom.isNull():
            return []
        flat = QgsWkbTypes.flatType(geom.wkbType())
        if flat == QgsWkbTypes.Point:
            p = geom.asPoint()
            return [QgsPointXY(p.x(), p.y())] if not p.isEmpty() else []
        if flat == QgsWkbTypes.MultiPoint:
            return [QgsPointXY(pt.x(), pt.y()) for pt in geom.asMultiPoint()]
        if flat == QgsWkbTypes.GeometryCollection:
            pts = []
            for part in geom.asGeometryCollection():
                pts.extend(TopologyBuilder._extract_points(part))
            return pts
        return []

    def _key(self, x: float, y: float) -> Tuple[float, float]:
        """坐标去重 key（仅用于内部去重，不用于拓扑匹配）"""
        digits = 7 if self.tol < 1e-3 else 3
        return (round(x, digits), round(y, digits))

    @staticmethod
    def _safe_attr(feat: QgsFeature, name: str, default=0):
        """安全读取数值字段"""
        idx = feat.fields().lookupField(name)
        if idx < 0:
            return default
        val = feat.attribute(idx)
        if val is None or (hasattr(val, 'isNull') and val.isNull()):
            return default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_attr_str(feat: QgsFeature, name: str, default=""):
        """安全读取字符串字段"""
        idx = feat.fields().lookupField(name)
        if idx < 0:
            return default
        val = feat.attribute(idx)
        if val is None or (hasattr(val, 'isNull') and val.isNull()):
            return default
        return str(val)
