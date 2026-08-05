"""RotationScheduler — 轮灌调度引擎（纯定量灌溉 + 单分区子网模拟）

核心流程:
  1. 读取 aqd_fields 田块 → 获取各分区阀门列表
  2. 构建完整 DripNetwork
  3. 逐分区：构建子网（仅该分区 + 公共管道）→ 模拟 → 记录 CU/DU
  4. 预留 multi_zone 接口用于多分区协同优化

Phase 2 预留: optimize_multi_zone() 返回最优分区组合
"""

import uuid
from typing import Callable, Dict, List, Optional

from qgis.core import QgsProject, QgsVectorLayer, QgsFeature
from qgis.PyQt.QtCore import QObject, pyqtSignal


class RotationScheduler:
    """轮灌调度器"""

    def __init__(self, iface):
        self.iface = iface
        self._field_feat: Optional[QgsFeature] = None
        self._valve_layer: Optional[QgsVectorLayer] = None
        self._pipe_layer: Optional[QgsVectorLayer] = None
        self._field_layer: Optional[QgsVectorLayer] = None
        self._gpkg_path: str = ""
        self._rotation_id: str = ""

    # ── 数据收集 ──

    def collect_field_data(self, field_feat: QgsFeature) -> dict:
        """收集田块及其分区轮灌数据

        Returns:
            {"zones": [{zone, valves, order, irrigation_mm}, ...]}
        """
        self._field_feat = field_feat
        self._find_layers()
        if self._valve_layer is None:
            return {"zones": []}

        # 从管道建 node→zone 映射
        node_zone: Dict[str, str] = {}
        if self._pipe_layer:
            for feat in self._pipe_layer.getFeatures():
                pz = str(feat.attribute("zone") or "").strip()
                if not pz or pz == "0":
                    continue
                fn = str(feat.attribute("from_node") or "")
                tn = str(feat.attribute("to_node") or "")
                if fn:
                    node_zone[fn] = pz
                if tn:
                    node_zone[tn] = pz

        # 收集阀门 → 按有效分区分组
        zones: Dict[str, dict] = {}
        for feat in self._valve_layer.getFeatures():
            vid = f"V{feat.id()}"
            fn = str(feat.attribute("from_node") or "")
            tn = str(feat.attribute("to_node") or "")
            effective_zone = node_zone.get(tn) or node_zone.get(fn) or ""
            if not effective_zone or effective_zone == "0":
                continue

            order = self._safe_int(feat, "rotation_order", 0)
            dur = self._safe_float(feat, "rotation_duration_min", 60.0)

            if effective_zone not in zones:
                zones[effective_zone] = {
                    "zone": effective_zone, "valves": [vid],
                    "order": order, "irrigation_mm": 10.0,
                    "duration_min": dur,
                }
            else:
                zones[effective_zone]["valves"].append(vid)
                if dur > zones[effective_zone]["duration_min"]:
                    zones[effective_zone]["duration_min"] = dur
                if order > 0 and (zones[effective_zone]["order"] <= 0 or
                                  order < zones[effective_zone]["order"]):
                    zones[effective_zone]["order"] = order

        for zname, zdata in zones.items():
            if zdata["order"] <= 0:
                try:
                    parts = zname.split("-")
                    zdata["order"] = int(parts[-1]) * 10 + len(parts)
                except ValueError:
                    zdata["order"] = 99

        sorted_zones = sorted(zones.values(), key=lambda z: z["order"])
        return {"zones": sorted_zones}

    # ── 轮灌模拟 ──

    def run_rotation(self, zones_data: List[dict],
                     progress_callback=None) -> List[dict]:
        """逐分区构建子网并模拟（纯内存操作，线程安全）

        Args:
            zones_data: [{zone, valves, irrigation_mm, order}, ...]
            progress_callback: (pct: int, msg: str)

        Returns:
            [{zone, valves, cu, du, avg_p_m, duration_min, flow_lph}, ...]
        """
        from .sync_manager import SyncManager

        sync = SyncManager(self.iface)
        full_net = sync.sync_qgis_to_network()
        if not full_net.links:
            return []

        total = len(zones_data)
        all_results = []
        self._rotation_id = uuid.uuid4().hex[:8]

        for idx, z in enumerate(zones_data):
            zone_name = z["zone"]
            valve_ids = set(z["valves"])
            irrigation_mm = z.get("irrigation_mm", 10.0)

            if progress_callback:
                pct = int(idx / max(total, 1) * 100)
                progress_callback(pct, f"分区 {zone_name} ({idx+1}/{total})")

            # 构建子网：保留公共管道 + 该分区管道
            sub = self._build_zone_subnet(full_net, zone_name)

            # 设置阀门状态
            from wdrip.network.links import ValveStatus
            for lid, link in sub.links.items():
                if hasattr(link, "valve_type"):
                    link.status = ValveStatus.OPEN if lid in valve_ids else ValveStatus.CLOSED

            try:
                from wdrip.simulation import DripSimulation
                sim = DripSimulation(sub, precision="fast")
                result = sim.run()

                if result.success:
                    from wdrip.analysis import UniformityAnalyzer
                    flows = [float(arr[0]) for arr in result.emitter_flow.values()
                             if len(arr) > 0]
                    cu = UniformityAnalyzer.cu(flows) if flows else 0.0
                    du = UniformityAnalyzer.du(flows) if flows else 0.0

                    pressures = [float(arr[0]) for arr in result.node_pressure.values()
                                 if len(arr) > 0]
                    avg_p = sum(pressures) / len(pressures) if pressures else 0.0
                    max_p = max(pressures) if pressures else 0.0

                    # 计算分区总流量 (L/h)
                    total_flow_lph = 0.0
                    for lid, arr in result.link_flow.items():
                        if len(arr) > 0:
                            total_flow_lph += abs(float(arr[0])) * 3600 * 1000

                    # 计算所需灌溉时长
                    area_m2 = self.get_field_area_m2()
                    vol_m3 = irrigation_mm / 1000.0 * area_m2
                    zone_flow_lph = sum(flows) if flows else 100.0
                    dur_h = vol_m3 / max(zone_flow_lph / 1000.0, 0.001)
                    dur_min = max(1, round(dur_h * 60, 1))

                    shift_result = {
                        "zone": zone_name,
                        "valves": list(valve_ids),
                        "irrigation_mm": irrigation_mm,
                        "cu": round(cu, 1),
                        "du": round(du, 1),
                        "avg_pressure_m": round(avg_p, 2),
                        "max_pressure_m": round(max_p, 2),
                        "emitter_count": len(flows),
                        "min_flow_lph": round(min(flows), 2) if flows else 0,
                        "max_flow_lph": round(max(flows), 2) if flows else 0,
                        "total_flow_lph": round(zone_flow_lph, 1),
                        "duration_min": dur_min,
                    }
                    all_results.append(shift_result)

                    self._save_result(sub, result, cu, du, zone_name, idx)
                else:
                    all_results.append({
                        "zone": zone_name,
                        "valves": list(valve_ids),
                        "irrigation_mm": irrigation_mm,
                        "error": result.message,
                    })
            except Exception as e:
                import traceback
                all_results.append({
                    "zone": zone_name,
                    "valves": list(valve_ids),
                    "irrigation_mm": irrigation_mm,
                    "error": f"{e}\n{traceback.format_exc()}",
                })

        if progress_callback:
            progress_callback(100, f"完成 ({total} 分区)")

        return all_results

    def _build_zone_subnet(self, net, zone: str):
        """构建单分区子网：保留公共管道 + 该分区管道 + 仅该分区阀门

        通过从 GPKG 读取的 link→zone 映射判断每条链路所属分区。
        """
        link_zone = self._get_link_zone_map()

        def keep_link(link) -> bool:
            lz = link_zone.get(link.id, "")
            is_valve = hasattr(link, "valve_type")

            if is_valve:
                # 阀门：zone="0"（公共区），但只有连接了目标分区管道的才保留
                if lz != "0":
                    return False  # 非公共区阀门直接排除
                fn, tn = link.from_node, link.to_node
                for lid, lz2 in link_zone.items():
                    if lid == link.id:
                        continue
                    if lz2 == zone:
                        other = net.links.get(lid)
                        if other and (other.from_node in (fn, tn)
                                      or other.to_node in (fn, tn)):
                            return True
                return False  # 阀门未连接到目标分区 → 排除
            else:
                # 管道/水泵：保留公共区 + 目标分区
                return lz in ("", "0", zone)

        return net.sub_network(keep_link)

    def _get_link_zone_map(self) -> Dict[str, str]:
        """从 GPKG 管道/阀门图层读取 link_id → zone 映射"""
        result = {}
        for layer_key, prefix in [("aqd_pipes", "L"), ("aqd_valves", "V")]:
            layer = self._find_layer_by_key(layer_key)
            if layer is None:
                continue
            for feat in layer.getFeatures():
                z = str(feat.attribute("zone") or "").strip()
                lid = f"{prefix}{feat.id()}"
                result[lid] = z
        return result

    def _find_layer_by_key(self, key: str) -> Optional[QgsVectorLayer]:
        from qgis.core import QgsProject, QgsVectorLayer
        for _lid, layer in QgsProject.instance().mapLayers().items():
            if not isinstance(layer, QgsVectorLayer):
                continue
            src = layer.source() if hasattr(layer, "source") else ""
            if key in src or layer.name() == key:
                return layer
        return None

    # ── Phase 2 预留接口 ──

    def optimize_multi_zone(self, zones_data: List[dict]) -> List[List[str]]:
        """多分区协同优化（占位）

        未来实现：根据各分区流量、压力需求，找出可同时灌溉的分区组合，
        使 CU/DU 保持在水力允许范围内。

        Returns:
            [[zone1, zone2], [zone3], ...] 每组可同时运行
        """
        return [[z["zone"]] for z in zones_data]

    # ── 历史保存 ──

    def _save_result(self, net, result, cu: float, du: float,
                     zone_name: str, shift_idx: int):
        try:
            if not self._gpkg_path:
                self._find_gpkg_path()
            if not self._gpkg_path:
                return
            from .sim_history import SimHistory
            history = SimHistory(self._gpkg_path)

            node_pressure = {nid: float(arr[0])
                             for nid, arr in result.node_pressure.items() if len(arr) > 0}
            link_flow = {lid: float(arr[0])
                         for lid, arr in result.link_flow.items() if len(arr) > 0}
            link_velocity = {lid: float(arr[0])
                             for lid, arr in result.link_velocity.items() if len(arr) > 0}
            emitter_flow = {eid: float(arr[0])
                            for eid, arr in result.emitter_flow.items() if len(arr) > 0}
            node_coords = {nid: [node.x, node.y] for nid, node in net.nodes.items()}
            link_endpoints = {lid: [link.from_node, link.to_node]
                              for lid, link in net.links.items()}
            link_geometry = getattr(net, "link_geometry", None) or {}

            history.add(
                cu=cu, du=du,
                node_pressure=node_pressure, link_flow=link_flow,
                link_velocity=link_velocity, emitter_flow=emitter_flow,
                node_coords=node_coords,
                message=f"轮灌 R{self._rotation_id} 分区{zone_name}",
                link_endpoints=link_endpoints, link_geometry=link_geometry,
                rotation_id=self._rotation_id, shift_index=shift_idx,
            )
        except Exception:
            import traceback
            traceback.print_exc()

    # ── 辅助 ──

    def get_field_area_m2(self) -> float:
        if self._field_feat is None:
            return 0
        geom = self._field_feat.geometry()
        if geom is None:
            return 0
        from qgis.core import QgsDistanceArea
        da = QgsDistanceArea()
        da.setEllipsoid("WGS84")
        return da.measureArea(geom)

    def get_field_features(self) -> List[QgsFeature]:
        self._find_layers()
        if self._field_layer is None:
            return []
        return list(self._field_layer.getFeatures())

    def _find_layers(self):
        from qgis.core import QgsProject, QgsVectorLayer
        for _lid, layer in QgsProject.instance().mapLayers().items():
            if not isinstance(layer, QgsVectorLayer):
                continue
            src = layer.source() if hasattr(layer, "source") else ""
            name = layer.name()
            if "aqd_valves" in src or name == "aqd_valves":
                self._valve_layer = layer
            elif "aqd_pipes" in src or name == "aqd_pipes":
                self._pipe_layer = layer
            elif "aqd_fields" in src or name == "aqd_fields":
                self._field_layer = layer
                if "|" in src:
                    self._gpkg_path = src.split("|")[0]

    def _find_gpkg_path(self):
        from qgis.core import QgsProject, QgsVectorLayer
        for _lid, layer in QgsProject.instance().mapLayers().items():
            if not isinstance(layer, QgsVectorLayer):
                continue
            src = layer.source() if hasattr(layer, "source") else ""
            if "aqd_fields" in src or layer.name() == "aqd_fields":
                self._gpkg_path = src.split("|")[0]
                return

    @property
    def rotation_id(self) -> str:
        return self._rotation_id

    @staticmethod
    def _safe_str(feat, field, default=""):
        try:
            val = feat.attribute(field)
            return str(val).strip() if val is not None else default
        except (KeyError, ValueError):
            return default

    @staticmethod
    def _safe_float(feat, field, default=0.0):
        try:
            val = feat.attribute(field)
            return float(val) if val is not None else default
        except (KeyError, ValueError, TypeError):
            return default

    @staticmethod
    def _safe_int(feat, field, default=0):
        try:
            val = feat.attribute(field)
            return int(val) if val is not None else default
        except (KeyError, ValueError, TypeError):
            return default


class RotationWorker(QObject):
    """后台轮灌 Worker"""
    progress_changed = pyqtSignal(int, str)
    finished = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, scheduler: RotationScheduler, zones_data: list, parent=None):
        super().__init__(parent)
        self._scheduler = scheduler
        self._zones = zones_data

    def run(self):
        try:
            results = self._scheduler.run_rotation(
                self._zones,
                progress_callback=lambda p, m: self.progress_changed.emit(p, m))
            self.finished.emit(results)
        except Exception as e:
            import traceback
            self.error_occurred.emit(f"{e}\n{traceback.format_exc()}")
