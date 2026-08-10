"""DirectionFixer — 根据水源位置自动矫正阀门/水泵方向

算法:
  1. 从 GPKG 读取管道/阀门/水泵 → 构建无向图
  2. BFS 从水源节点计算每个节点的"距源距离"
  3. 对每个阀门/水泵：
     - 若 from_node 距源距离 > to_node 距源距离 → 方向错误 → 交换 from/to
  4. 写回 GPKG 图层
"""

from collections import deque
from typing import Dict, Optional

from qgis.core import QgsProject, QgsVectorLayer


class DirectionFixer:
    """阀门/水泵方向自动矫正"""

    def __init__(self, iface):
        self.iface = iface

    def fix(self) -> dict:
        """执行方向矫正

        Returns:
            {"valves_fixed": int, "pumps_fixed": int}
        """
        # 1. 构建无向图（忽略阀门/水泵方向）
        graph: Dict[str, list] = {}
        sources = []
        valve_map: Dict[str, tuple] = {}  # fid -> (from_node, to_node)
        pump_map: Dict[str, tuple] = {}   # fid -> (from_node, to_node)

        pipe_layer = self._find_layer("aqd_pipes")
        valve_layer = self._find_layer("aqd_valves")
        pump_layer = self._find_layer("aqd_pumps")
        node_layer = self._find_layer("aqd_nodes")

        if node_layer:
            for feat in node_layer.getFeatures():
                ntype = str(feat.attribute("node_type") or "")
                if ntype == "source" or feat.attribute("source_type"):
                    sources.append(f"N{feat.id()}")

        if not sources:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "未找到水源节点，无法矫正方向")
            return {"valves_fixed": 0, "pumps_fixed": 0}

        # 管道 → 无向边
        if pipe_layer:
            for feat in pipe_layer.getFeatures():
                fn = str(feat.attribute("from_node") or "")
                tn = str(feat.attribute("to_node") or "")
                if not fn or not tn:
                    continue
                graph.setdefault(fn, []).append(tn)
                graph.setdefault(tn, []).append(fn)

        # 阀门 → 也加入无向图（用于距离传播），记录当前方向
        if valve_layer:
            for feat in valve_layer.getFeatures():
                fn = str(feat.attribute("from_node") or "")
                tn = str(feat.attribute("to_node") or "")
                if not fn or not tn:
                    continue
                valve_map[feat.id()] = (fn, tn)
                graph.setdefault(fn, []).append(tn)
                graph.setdefault(tn, []).append(fn)

        # 水泵 → 同理
        if pump_layer:
            for feat in pump_layer.getFeatures():
                fn = str(feat.attribute("from_node") or "")
                tn = str(feat.attribute("to_node") or "")
                if not fn or not tn:
                    continue
                pump_map[feat.id()] = (fn, tn)
                graph.setdefault(fn, []).append(tn)
                graph.setdefault(tn, []).append(fn)

        # 2. BFS 计算距源距离
        dist: Dict[str, int] = {}
        queue = deque()
        for src in sources:
            dist[src] = 0
            queue.append(src)

        while queue:
            node = queue.popleft()
            d = dist[node]
            for neighbor in graph.get(node, []):
                if neighbor not in dist:
                    dist[neighbor] = d + 1
                    queue.append(neighbor)

        # 3. 检查并矫正方向
        valves_fixed = self._fix_layer(valve_layer, valve_map, dist)
        pumps_fixed = self._fix_layer(pump_layer, pump_map, dist)

        msg_parts = []
        if valves_fixed:
            msg_parts.append(f"{valves_fixed} 个阀门方向已矫正")
        if pumps_fixed:
            msg_parts.append(f"{pumps_fixed} 个水泵方向已矫正")
        if not msg_parts:
            msg_parts.append("所有方向正确，无需矫正")

        self.iface.messageBar().pushMessage(
            "aQuaDrip", "，".join(msg_parts), level=0, duration=5)

        return {"valves_fixed": valves_fixed, "pumps_fixed": pumps_fixed}

    def _fix_layer(self, layer, direction_map: dict,
                   dist: dict) -> int:
        """矫正一个图层中要素的方向

        Returns:
            被矫正的要素数量
        """
        if layer is None or not direction_map:
            return 0

        fixed = 0
        need_edit = not layer.isEditable()
        if need_edit:
            layer.startEditing()
        try:
            for feat in layer.getFeatures():
                fid = feat.id()
                if fid not in direction_map:
                    continue
                fn, tn = direction_map[fid]
                dfn = dist.get(fn)
                dtn = dist.get(tn)
                if dfn is None or dtn is None:
                    continue
                # from_node 比 to_node 更远离水源 → 方向反了
                if dfn > dtn:
                    feat.setAttribute("from_node", tn)
                    feat.setAttribute("to_node", fn)
                    layer.updateFeature(feat)
                    fixed += 1
            if need_edit:
                layer.commitChanges()
        except Exception:
            if need_edit:
                layer.rollBack()
            raise

        if layer:
            layer.triggerRepaint()
        return fixed

    def _find_layer(self, key: str) -> Optional[QgsVectorLayer]:
        from .layer_utils import find_layer
        return find_layer(QgsProject.instance(), key)
