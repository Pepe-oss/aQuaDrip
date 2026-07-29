"""SyncManager — QGIS 图层与 wdrip-core DripNetwork 双向同步

核心方法:
  sync_qgis_to_network()  — QGIS → DripNetwork
  sync_from_network()     — DripNetwork → QGIS
"""

import math
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsGeometry, QgsPointXY, QgsFeature,
    QgsSpatialIndex,
)

if TYPE_CHECKING:
    from wdrip.network import DripNetwork, SimulationResult


class SyncManager:
    """QGIS ↔ DripNetwork 同步管理器"""

    def __init__(self, iface, gpkg_path: str):
        self.iface = iface
        self.gpkg_path = gpkg_path
        self.project = QgsProject.instance()

    # ── 从 QGIS 读取 → 构建 DripNetwork ──

    def sync_qgis_to_network(self) -> 'DripNetwork':
        """从 QGIS 图层读取数据，构建 DripNetwork"""
        from wdrip.network import (
            DripNetwork, FieldInfo,
            SourceNode, Junction,
            Pipe, Pump, Valve, ValveType,
        )

        net = DripNetwork(name="aQuaDrip 项目")

        # 1. 读取农田
        field_layer = self._get_layer("aqd_fields")
        if field_layer and field_layer.featureCount() > 0:
            feat = next(field_layer.getFeatures())
            net.field_info = FieldInfo(
                area=float(feat.attribute("area") or 0),
                crop_type=str(feat.attribute("crop_type") or ""),
                planting_pattern=str(feat.attribute("planting_pattern") or "uniform"),
                row_spacings=[float(feat.attribute("row_spacing") or 0.5)],
                ridge_count=int(feat.attribute("ridge_count") or 0) or None,
                row_direction=float(feat.attribute("row_direction") or 0),
                emitter_spacing=float(feat.attribute("emitter_spacing") or 0.3),
                geometry=feat.geometry(),
            )

        # 2. 读取节点
        node_layer = self._get_layer("aqd_nodes")
        node_positions = {}  # {(x, y): id} 用于管道端点匹配
        if node_layer:
            for feat in node_layer.getFeatures():
                geom = feat.geometry()
                if not geom:
                    continue
                pt = geom.asPoint()
                nid = str(feat.attribute("id") or f"N{feat.id()}")
                node_type = str(feat.attribute("node_type") or "junction")
                elev = float(feat.attribute("elevation") or 0)

                if node_type == "source":
                    src_type = str(feat.attribute("source_type") or "well")
                    node = SourceNode(nid, pt.x(), pt.y(), elevation=elev,
                                      source_type=src_type,
                                      head=float(feat.attribute("head") or 0),
                                      available_flow=float(feat.attribute("available_flow") or 0))
                else:
                    node = Junction(nid, pt.x(), pt.y(), elevation=elev)

                net.add_node(node)
                node_positions[(round(pt.x(), 3), round(pt.y(), 3))] = nid

        # 3. 从三个管道图层读取
        pipe_layers = {
            "lateral": self._get_layer("aqd_laterals"),
            "submain": self._get_layer("aqd_submains"),
            "mainline": self._get_layer("aqd_maines"),
        }
        for pipe_type, pipe_layer in pipe_layers.items():
            if not pipe_layer:
                continue
            for feat in pipe_layer.getFeatures():
                geom = feat.geometry()
                if not geom or geom.isEmpty():
                    continue
                line = geom.asPolyline()
                if len(line) < 2:
                    continue

                lid = str(feat.attribute("id") or f"L{feat.id()}")

                # 从几何端点推导 from_node / to_node
                start_pt = line[0]
                end_pt = line[-1]
                from_node = self._match_node(node_positions, start_pt)
                to_node = self._match_node(node_positions, end_pt)

                # 如果端点无匹配节点，自动创建 Junction
                if not from_node:
                    from_node = f"auto_N{len(net.nodes)}"
                    net.add_node(Junction(from_node, start_pt.x(), start_pt.y()))
                if not to_node:
                    to_node = f"auto_N{len(net.nodes)}"
                    net.add_node(Junction(to_node, end_pt.x(), end_pt.y()))

                # 字段读取
                diameter = float(feat.attribute("diameter") or 0) / 1000
                length = geom.length()
                roughness = float(feat.attribute("roughness") or 130)

                if pipe_type == "mainline" and str(feat.attribute("device") or "none") == "pump":
                    link = Pump(lid, from_node, to_node,
                                rated_head=float(feat.attribute("pump_head") or 0),
                                rated_flow=float(feat.attribute("pump_flow") or 0),
                                rated_power=float(feat.attribute("pump_power") or 0))
                elif pipe_type == "mainline" and str(feat.attribute("device") or "none") == "valve":
                    vtype_str = str(feat.attribute("valve_type") or "gate").upper()
                    vtype = getattr(ValveType, vtype_str, ValveType.GATE)
                    link = Valve(lid, from_node, to_node,
                                 valve_type=vtype,
                                 setting=float(feat.attribute("valve_type_setting") or 0))
                else:
                    link = Pipe(lid, from_node, to_node,
                                pipe_type=pipe_type,
                                diameter=diameter, length=length,
                                roughness=roughness)

                net.add_link(link)

        return net

    def _match_node(self, node_positions: dict, pt: QgsPointXY,
                     tolerance: float = 1.0) -> Optional[str]:
        """从节点位置字典中匹配最近的节点"""
        key = (round(pt.x(), 3), round(pt.y(), 3))
        if key in node_positions:
            return node_positions[key]
        # 容差匹配
        best = None
        best_dist = tolerance
        for (nx, ny), nid in node_positions.items():
            dist = math.sqrt((nx - pt.x())**2 + (ny - pt.y())**2)
            if dist < best_dist:
                best_dist = dist
                best = nid
        return best

    # ── 将 DripNetwork 写回 QGIS ──

    def sync_from_network(self, network: 'DripNetwork',
                          result: 'SimulationResult' = None):
        """将 DripNetwork 及模拟结果写回 QGIS 图层"""
        pipe_layers = {
            "lateral": self._get_layer("aqd_laterals"),
            "submain": self._get_layer("aqd_submains"),
            "mainline": self._get_layer("aqd_maines"),
        }
        node_layer = self._get_layer("aqd_nodes")

        # 写入管道结果（流量、流速）
        for pipe_type, pipe_layer in pipe_layers.items():
            if not pipe_layer or not result:
                continue
            pipe_layer.startEditing()
            for feat in pipe_layer.getFeatures():
                lid = str(feat.attribute("id") or "")
                if lid in result.link_flow:
                    flow_arr = result.link_flow[lid]
                    if len(flow_arr) > 0:
                        feat.setAttribute("flow", float(flow_arr[-1]))
                if lid in result.link_velocity:
                    vel_arr = result.link_velocity[lid]
                    if len(vel_arr) > 0:
                        feat.setAttribute("velocity", float(vel_arr[-1]))
                pipe_layer.updateFeature(feat)
            pipe_layer.commitChanges()

        # 写入节点结果（压力）
        if node_layer and result:
            node_layer.startEditing()
            for feat in node_layer.getFeatures():
                nid = str(feat.attribute("id") or "")
                if nid in result.node_pressure:
                    p_arr = result.node_pressure[nid]
                    if len(p_arr) > 0:
                        feat.setAttribute("pressure", float(p_arr[-1]))
                node_layer.updateFeature(feat)
            node_layer.commitChanges()

    # ── 辅助 ──

    def _get_layer(self, key: str) -> Optional[QgsVectorLayer]:
        """从 GPKG 获取图层"""
        if not self.gpkg_path:
            return None
        uri = f"{self.gpkg_path}|layername={key}"
        layer = QgsVectorLayer(uri, key, "ogr")
        return layer if layer.isValid() else None

    def log(self, msg: str):
        """输出日志"""
        self.iface.messageBar().pushMessage("aQuaDrip", msg, level=0, duration=3)
