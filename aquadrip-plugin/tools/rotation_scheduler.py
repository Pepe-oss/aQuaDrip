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
from qgis.PyQt.QtWidgets import QApplication


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
        # 后台线程收集、待主线程写盘的历史记录 payload
        self._pending_history: List[dict] = []

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

        # 收集阀门 → 按有效分区分组
        # 阀门的 zone 字段由 ZoneDivider 写入，直接编码它控制的子分区编号
        # （如 "1"、"1-1"、"2"），无需通过管道 from_node/to_node 间接查找
        zones: Dict[str, dict] = {}
        for feat in self._valve_layer.getFeatures():
            vid = f"V{feat.id()}"
            effective_zone = str(feat.attribute("zone") or "").strip()
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

    def prepare_snapshot(self) -> dict:
        """在主线程预取后台轮灌所需的全部 QGIS 数据（线程安全边界）

        QGIS 图层只允许在主线程访问/编辑（sync_qgis_to_network 会回写
        from_node/to_node）。后台线程运行 run_rotation 前，必须先在主线程
        调用本方法，把结果经 full_net / link_zone / field_area_m2 注入。

        Returns:
            {"full_net": DripNetwork, "link_zone": {lid: zone},
             "field_area_m2": float}
        """
        from .sync_manager import SyncManager

        full_net = SyncManager(self.iface).sync_qgis_to_network()
        return {
            "full_net": full_net,
            "link_zone": self._get_link_zone_map(),
            "field_area_m2": self.get_field_area_m2(),
        }

    def run_rotation(self, zones_data: List[dict],
                     progress_callback=None,
                     full_net=None,
                     link_zone: Optional[Dict[str, str]] = None,
                     field_area_m2: Optional[float] = None) -> List[dict]:
        """逐分区构建子网并模拟

        注入 full_net / link_zone / field_area_m2 后本方法为纯内存操作，
        可在后台线程安全运行；任一参数缺省时将回退自行读取 QGIS 图层，
        此时只允许在主线程调用（参见 prepare_snapshot）。

        Args:
            zones_data: [{zone, valves, irrigation_mm, order}, ...]
            progress_callback: (pct: int, msg: str)
            full_net: 主线程构建的完整 DripNetwork
            link_zone: 主线程读取的 link_id → zone 映射
            field_area_m2: 主线程计算的田块面积 (m²)

        Returns:
            [{zone, valves, cu, du, avg_p_m, duration_min, flow_lph}, ...]
        """
        if full_net is None:
            from .sync_manager import SyncManager
            sync = SyncManager(self.iface)
            full_net = sync.sync_qgis_to_network()
        if not full_net.links:
            return []
        if link_zone is None:
            link_zone = self._get_link_zone_map()
        if field_area_m2 is None:
            field_area_m2 = self.get_field_area_m2()

        total = len(zones_data)
        all_results = []
        self._rotation_id = uuid.uuid4().hex[:8]

        for idx, z in enumerate(zones_data):
            zone_name = z["zone"]
            valve_ids = set(z["valves"])
            irrigation_mm = z.get("irrigation_mm", 10.0)

            if progress_callback:
                pct = int(idx / max(total, 1) * 100)
                progress_callback(pct, QApplication.translate("RotationScheduler", "分区 {0} ({1}/{2})").format(zone_name, idx+1, total))

            # 构建子网：保留公共管道 + 该分区管道
            sub = self._build_zone_subnet(full_net, zone_name, link_zone)

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
                    vol_m3 = irrigation_mm / 1000.0 * field_area_m2
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

                    self._pending_history.append(
                        self._make_history_payload(sub, result, cu, du,
                                                   zone_name, idx))
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
            progress_callback(100, QApplication.translate("RotationScheduler", "完成 ({0} 分区)").format(total))

        return all_results

    def _build_zone_subnet(self, net, zone: str,
                           link_zone: Optional[Dict[str, str]] = None):
        """构建单分区子网：保留公共管道 + 该分区管道 + 仅该分区阀门

        通过 link→zone 映射判断每条链路所属分区
        （主线程经 _get_link_zone_map 预取后注入，后台线程不再访问图层）。
        """
        if link_zone is None:
            link_zone = self._get_link_zone_map()

        def get_link_zone(lid: str) -> str:
            """查 link 的 zone，分段管道继承原始管道的 zone

            拓扑构建和毛管展开会产生两种分段后缀：
              _p:  交叉切断分段（如 L3_p2 → 原始 L3）
              _seg: 毛管展开分段（如 L4_seg003 → 原始 L4）
            """
            lz = link_zone.get(lid, "")
            if lz:
                return lz
            # 回退：逐级去掉后缀查基础 ID
            for sep in ("_p", "_seg"):
                if sep in lid:
                    base_id = lid.rsplit(sep, 1)[0]
                    lz = link_zone.get(base_id, "")
                    if lz:
                        return lz
            return ""

        def keep_link(link) -> bool:
            lz = get_link_zone(link.id)
            is_valve = hasattr(link, "valve_type")

            if is_valve:
                # 阀门的 zone 直接编码它控制的子分区编号（由 ZoneDivider 写入）
                # 保留：控制目标分区的阀门 + 公共区阀门（zone="0"）
                return lz == zone or lz == "0"
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
        from .layer_utils import find_layer
        return find_layer(None, key)

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

    def _make_history_payload(self, net, result, cu: float, du: float,
                              zone_name: str, shift_idx: int) -> dict:
        """收集单分区结果的 simhistory 参数（纯内存，线程安全）

        实际写盘由主线程的 flush_pending_history 完成，避免后台线程
        与主线程并发"读-改-写"同一 .simhistory JSON。
        """
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

        return dict(
            cu=cu, du=du,
            node_pressure=node_pressure, link_flow=link_flow,
            link_velocity=link_velocity, emitter_flow=emitter_flow,
            node_coords=node_coords,
            message=QApplication.translate("RotationScheduler", "轮灌 R{0} 分区{1}").format(self._rotation_id, zone_name),
            link_endpoints=link_endpoints, link_geometry=link_geometry,
            rotation_id=self._rotation_id, shift_index=shift_idx,
        )

    def flush_pending_history(self) -> int:
        """将后台线程收集的历史记录写入 .simhistory（须在主线程调用）"""
        payloads = self._pending_history
        self._pending_history = []
        if not payloads:
            return 0
        if not self._gpkg_path:
            self._find_gpkg_path()
        if not self._gpkg_path:
            return 0
        from .sim_history import SimHistory
        history = SimHistory(self._gpkg_path)
        written = 0
        for payload in payloads:
            try:
                history.add(**payload)
                written += 1
            except Exception:
                import traceback
                traceback.print_exc()
        return written

    # ── 辅助 ──

    def get_field_area_m2(self) -> float:
        if self._field_feat is None:
            return 0
        geom = self._field_feat.geometry()
        if geom is None:
            return 0
        from qgis.core import QgsDistanceArea, QgsProject
        da = QgsDistanceArea()
        # 必须设置源 CRS：投影坐标系（米）下若按经纬度解释，
        # 面积会差好几个数量级，轮灌时长随之完全错误
        crs = self._field_layer.crs() if self._field_layer else None
        if crs is not None and crs.isValid():
            da.setSourceCrs(crs, QgsProject.instance().transformContext())
        da.setEllipsoid("WGS84")
        return da.measureArea(geom)

    def get_field_features(self) -> List[QgsFeature]:
        self._find_layers()
        if self._field_layer is None:
            return []
        return list(self._field_layer.getFeatures())

    def _find_layers(self):
        from .layer_utils import find_layers, find_gpkg_path
        found = find_layers(None, "aqd_valves", "aqd_pipes", "aqd_fields")
        self._valve_layer = found.get("aqd_valves")
        self._pipe_layer = found.get("aqd_pipes")
        self._field_layer = found.get("aqd_fields")
        gpkg = find_gpkg_path(None, "aqd_fields")
        if gpkg:
            self._gpkg_path = gpkg

    def _find_gpkg_path(self):
        from .layer_utils import find_gpkg_path
        gpkg = find_gpkg_path(None, "aqd_fields")
        if gpkg:
            self._gpkg_path = gpkg

    @property
    def rotation_id(self) -> str:
        return self._rotation_id

    @staticmethod
    def _safe_str(feat, field, default=""):
        from .layer_utils import safe_str
        return safe_str(feat, field, default)

    @staticmethod
    def _safe_float(feat, field, default=0.0):
        from .layer_utils import safe_float
        return safe_float(feat, field, default)

    @staticmethod
    def _safe_int(feat, field, default=0):
        from .layer_utils import safe_int
        return safe_int(feat, field, default)


class RotationWorker(QObject):
    """后台轮灌 Worker

    仅做纯内存计算：所有 QGIS 图层访问（网络同步 / zone 映射 / 面积）
    已由主线程经 prepare_snapshot 预取并注入；simhistory 写盘也推迟到
    主线程 flush_pending_history，避免跨线程编辑图层与并发写文件。
    """
    progress_changed = pyqtSignal(int, str)
    finished = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, scheduler: RotationScheduler, zones_data: list,
                 full_net=None, link_zone: Optional[Dict[str, str]] = None,
                 field_area_m2: Optional[float] = None, parent=None):
        super().__init__(parent)
        self._scheduler = scheduler
        self._zones = zones_data
        self._full_net = full_net
        self._link_zone = link_zone
        self._field_area_m2 = field_area_m2

    def run(self):
        try:
            results = self._scheduler.run_rotation(
                self._zones,
                progress_callback=lambda p, m: self.progress_changed.emit(p, m),
                full_net=self._full_net,
                link_zone=self._link_zone,
                field_area_m2=self._field_area_m2)
            self.finished.emit(results)
        except Exception as e:
            import traceback
            self.error_occurred.emit(f"{e}\n{traceback.format_exc()}")
