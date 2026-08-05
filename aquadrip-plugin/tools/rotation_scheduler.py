"""RotationScheduler — 轮灌调度引擎

核心流程:
  1. 读取 aqd_fields 田块 → 获取轮灌模式 (time/volume)
  2. 读取 aqd_valves 阀门 → 获取各分区阀门列表 + 顺序 + 时长
  3. 生成 IrrigationSchedule (ShiftGroup 列表)
  4. 逐轮次运行稳态模拟 (各轮次阀门状态不同)
  5. 汇总结果并保存到 sim_history
"""

import datetime
import uuid
from typing import Dict, List, Optional, Tuple

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
        self._mode: str = "time"  # "time" or "volume"
        self._shift_groups: List[dict] = []  # [{name, valve_ids, open_start, open_end}, ...]

    # ── 数据收集 ──

    def collect_field_data(self, field_feat: QgsFeature) -> dict:
        """收集田块及其分区轮灌数据

        Returns:
            {"mode": "time"/"volume", "zones": [{zone, valves, order, duration_min}, ...]}
        """
        self._field_feat = field_feat
        self._find_layers()
        if self._field_layer is None or self._valve_layer is None:
            return {"mode": "time", "zones": []}

        self._mode = self._safe_str(field_feat, "rotation_mode", "time")
        if self._mode not in ("time", "volume"):
            self._mode = "time"

        # 收集所有阀门 → 按 zone + order 排序
        zones: Dict[str, dict] = {}
        for feat in self._valve_layer.getFeatures():
            zone = str(feat.attribute("zone") or "").strip()
            if not zone:
                continue
            order = self._safe_int(feat, "rotation_order", 0)
            if order <= 0:
                continue
            duration = self._safe_float(feat, "rotation_duration_min", 60.0)
            vid = f"V{feat.id()}"

            if zone not in zones:
                zones[zone] = {"zone": zone, "valves": [], "order": order,
                               "duration_min": duration}
            else:
                zones[zone]["valves"].append(vid)
                # 取最大时长作为分区时长（同一分区多个阀门同时开）
                if duration > zones[zone]["duration_min"]:
                    zones[zone]["duration_min"] = duration

        # 对于还没记录阀门的 zone，补充
        for zone_name, zdata in zones.items():
            if not zdata["valves"]:
                for feat in self._valve_layer.getFeatures():
                    if str(feat.attribute("zone") or "").strip() == zone_name:
                        zdata["valves"].append(f"V{feat.id()}")

        sorted_zones = sorted(zones.values(), key=lambda z: z["order"])
        return {"mode": self._mode, "zones": sorted_zones}

    def get_field_area_m2(self) -> float:
        """获取田块面积 (m²)"""
        if self._field_feat is None:
            return 0
        geom = self._field_feat.geometry()
        if geom is None:
            return 0
        from qgis.core import QgsDistanceArea
        da = QgsDistanceArea()
        da.setEllipsoid("WGS84")
        return da.measureArea(geom)

    # ── 调度构建 ──

    def build_time_schedule(self, zones_data: List[dict]) -> List[dict]:
        """根据定时间模式构建轮次组

        Args:
            zones_data: [{zone, valves, order, duration_min}, ...]

        Returns:
            [{name, valve_ids, open_start_h, open_end_h, duration_min}, ...]
        """
        groups = []
        current_start = 0.0
        for z in zones_data:
            dur_h = z["duration_min"] / 60.0
            end = current_start + dur_h
            groups.append({
                "name": f"Zone_{z['zone']}",
                "valve_ids": list(z["valves"]),
                "open_start_h": current_start,
                "open_end_h": end,
                "duration_min": z["duration_min"],
            })
            current_start = end
        self._shift_groups = groups
        return groups

    def build_volume_schedule(self, zones_data: List[dict],
                              irrigation_mm: float,
                              flow_rates: Dict[str, float]) -> List[dict]:
        """根据定量模式构建轮次组

        Args:
            zones_data: [{zone, valves, order}, ...]
            irrigation_mm: 每分区灌水量 (mm)
            flow_rates: {zone: flow_L_per_h} 各分区流量 (L/h)

        Returns:
            [{name, valve_ids, open_start_h, open_end_h, duration_min}, ...]
        """
        groups = []
        current_start = 0.0
        for z in zones_data:
            q_lph = flow_rates.get(z["zone"], 100.0)  # L/h
            if q_lph <= 0:
                q_lph = 100.0
            # 亩 → m²: 1 亩 ≈ 666.67 m²
            area_m2 = self.get_field_area_m2()
            # 灌水量 mm → m³: 1mm × 面积(m²) = 面积/1000 m³
            volume_m3 = irrigation_mm / 1000.0 * area_m2
            # 所需时长 (h)
            dur_h = volume_m3 / (q_lph / 1000.0)  # q_lph/1000 = m³/h
            dur_min = dur_h * 60.0
            end = current_start + dur_h
            groups.append({
                "name": f"Zone_{z['zone']}",
                "valve_ids": list(z["valves"]),
                "open_start_h": current_start,
                "open_end_h": end,
                "duration_min": dur_min,
            })
            current_start = end
        self._shift_groups = groups
        return groups

    # ── 基准模拟（定量模式）──

    def run_baseline_simulation(self, callback=None) -> Dict[str, float]:
        """运行一次全开模拟，获取各分区流量 (L/h)

        Returns:
            {zone_label: flow_L_per_h}
        """
        from .sync_manager import SyncManager
        from wdrip.simulation import DripSimulation

        sync = SyncManager(self.iface)
        net = sync.sync_qgis_to_network()

        if callback:
            callback(10, "基准模拟: 构建模型...")

        sim = DripSimulation(net, precision="fast")
        result = sim.run()

        if not result.success:
            if callback:
                callback(0, f"基准模拟失败: {result.message}")
            return {}

        if callback:
            callback(80, "基准模拟: 计算分区流量...")

        # 汇总各分区流量：找到各分区阀门下游管道的流量
        zone_flows: Dict[str, float] = {}
        flow_data = result.link_flow

        # 找每个分区的阀门对应的管道流量
        for feat in self._valve_layer.getFeatures():
            zone = str(feat.attribute("zone") or "").strip()
            if not zone:
                continue
            vid = f"V{feat.id()}"
            # 阀门在 WNTR 中映射为 link，取其流量
            fl = flow_data.get(vid)
            if fl and len(fl) > 0:
                q_m3s = abs(float(fl[0]))
                q_lph = q_m3s * 3600 * 1000  # m³/s → L/h
                zone_flows[zone] = zone_flows.get(zone, 0) + q_lph

        if callback:
            callback(100, "基准模拟完成")

        return zone_flows

    # ── 多轮次模拟 ──

    def run_rotation(self, shift_groups: List[dict],
                     progress_callback=None,
                     result_callback=None) -> List[dict]:
        """逐轮次运行模拟

        Args:
            shift_groups: 轮次组列表
            progress_callback: (pct: int, msg: str) 进度回调
            result_callback: (shift_idx, result, cu, du) 结果回调

        Returns:
            [{shift_idx, zone, valves, duration_min, avg_pressure, cu, du, flows}, ...]
        """
        from .sync_manager import SyncManager

        total = len(shift_groups)
        all_results = []
        self._rotation_id = uuid.uuid4().hex[:8]

        for idx, group in enumerate(shift_groups):
            if progress_callback:
                pct = int((idx / total) * 100)
                progress_callback(pct, f"轮次 {idx+1}/{total}: {group['name']}")

            # 1. 读取当前阀门状态
            sync = SyncManager(self.iface)
            self._find_layers()

            # 2. 设置阀门状态：本轮阀门 OPEN，其余 CLOSED
            opened = set(group["valve_ids"])
            original_statuses = self._set_valve_statuses(opened)

            try:
                # 3. 构建网络
                net = sync.sync_qgis_to_network()

                # 4. 运行模拟
                from wdrip.simulation import DripSimulation
                sim = DripSimulation(net, precision="fast")
                result = sim.run(
                    progress_callback=lambda p, m: (
                        progress_callback(int(p * (idx+1)/total), m)
                        if progress_callback else None
                    )
                )

                if result.success:
                    sync.sync_from_network(net, result)

                    from wdrip.analysis import UniformityAnalyzer
                    flows = [float(arr[0]) for arr in result.emitter_flow.values()
                             if len(arr) > 0]
                    cu = UniformityAnalyzer.cu(flows) if flows else 0.0
                    du = UniformityAnalyzer.du(flows) if flows else 0.0

                    avg_p = 0.0
                    pressures = [float(arr[0]) for arr in result.node_pressure.values()
                                 if len(arr) > 0]
                    if pressures:
                        avg_p = sum(pressures) / len(pressures)

                    shift_result = {
                        "shift_idx": idx,
                        "rotation_id": self._rotation_id,
                        "zone": group["name"],
                        "valves": group["valve_ids"],
                        "duration_min": group["duration_min"],
                        "avg_pressure_m": round(avg_p, 2),
                        "cu": round(cu, 1),
                        "du": round(du, 1),
                        "emitter_count": len(flows),
                        "min_flow_lph": round(min(flows), 2) if flows else 0,
                        "max_flow_lph": round(max(flows), 2) if flows else 0,
                    }
                    all_results.append(shift_result)

                    # 保存到历史
                    self._save_shift_history(net, result, cu, du, idx)

                    if result_callback:
                        result_callback(idx, result, cu, du)
                else:
                    shift_result = {
                        "shift_idx": idx,
                        "rotation_id": self._rotation_id,
                        "zone": group["name"],
                        "valves": group["valve_ids"],
                        "duration_min": group["duration_min"],
                        "error": result.message,
                    }
                    all_results.append(shift_result)

            finally:
                # 5. 恢复原始阀门状态
                self._restore_valve_statuses(original_statuses)

        if progress_callback:
            progress_callback(100, f"轮灌完成 ({total} 轮次)")

        return all_results

    # ── 阀门状态管理 ──

    def _set_valve_statuses(self, open_ids: set) -> Dict[int, str]:
        """设置阀门状态，返回原始状态用于恢复"""
        self._find_layers()
        original = {}
        if self._valve_layer is None:
            return original
        need_edit = not self._valve_layer.isEditable()
        if need_edit:
            self._valve_layer.startEditing()
        try:
            for feat in self._valve_layer.getFeatures():
                fid = feat.id()
                vid = f"V{fid}"
                old_status = str(feat.attribute("status") or "open")
                original[fid] = old_status
                new_status = "open" if vid in open_ids else "closed"
                if old_status != new_status:
                    feat.setAttribute("status", new_status)
                    self._valve_layer.updateFeature(feat)
            if need_edit:
                self._valve_layer.commitChanges()
        except Exception:
            if need_edit:
                self._valve_layer.rollBack()
            raise
        return original

    def _restore_valve_statuses(self, original: Dict[int, str]):
        """恢复阀门原始状态"""
        if not original:
            return
        self._find_layers()
        if self._valve_layer is None:
            return
        need_edit = not self._valve_layer.isEditable()
        if need_edit:
            self._valve_layer.startEditing()
        try:
            for feat in self._valve_layer.getFeatures():
                fid = feat.id()
                if fid in original:
                    feat.setAttribute("status", original[fid])
                    self._valve_layer.updateFeature(feat)
            if need_edit:
                self._valve_layer.commitChanges()
        except Exception:
            if need_edit:
                self._valve_layer.rollBack()

    # ── 历史保存 ──

    def _save_shift_history(self, net, result, cu: float, du: float, shift_idx: int):
        """保存单轮次模拟结果到历史"""
        try:
            if not self._gpkg_path:
                self._find_gpkg_path()
            if not self._gpkg_path:
                return

            from .sim_history import SimHistory
            history = SimHistory(self._gpkg_path)

            node_pressure = {nid: float(arr[0])
                             for nid, arr in result.node_pressure.items()
                             if len(arr) > 0}
            link_flow = {lid: float(arr[0])
                         for lid, arr in result.link_flow.items()
                         if len(arr) > 0}
            link_velocity = {lid: float(arr[0])
                             for lid, arr in result.link_velocity.items()
                             if len(arr) > 0}
            emitter_flow = {eid: float(arr[0])
                            for eid, arr in result.emitter_flow.items()
                            if len(arr) > 0}
            node_coords = {nid: [node.x, node.y]
                           for nid, node in net.nodes.items()}
            link_endpoints = {lid: [link.from_node, link.to_node]
                              for lid, link in net.links.items()}
            link_geometry = getattr(net, "link_geometry", None) or {}

            history.add(
                cu=cu, du=du,
                node_pressure=node_pressure,
                link_flow=link_flow,
                link_velocity=link_velocity,
                emitter_flow=emitter_flow,
                node_coords=node_coords,
                message=f"轮灌 R{self._rotation_id} 轮次{shift_idx+1}",
                link_endpoints=link_endpoints,
                link_geometry=link_geometry,
                rotation_id=self._rotation_id,
                shift_index=shift_idx,
            )
        except Exception:
            import traceback
            traceback.print_exc()

    # ── 图层查找 ──

    def _find_layers(self):
        """查找相关 QGIS 图层"""
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
        """查找 GPKG 路径"""
        from qgis.core import QgsProject, QgsVectorLayer
        for _lid, layer in QgsProject.instance().mapLayers().items():
            if not isinstance(layer, QgsVectorLayer):
                continue
            src = layer.source() if hasattr(layer, "source") else ""
            if "aqd_fields" in src or layer.name() == "aqd_fields":
                self._gpkg_path = src.split("|")[0]
                return

    def get_field_features(self) -> List[QgsFeature]:
        """获取所有田块要素列表"""
        self._find_layers()
        if self._field_layer is None:
            return []
        return list(self._field_layer.getFeatures())

    @property
    def rotation_id(self) -> str:
        return self._rotation_id

    @staticmethod
    def _safe_str(feat, field: str, default: str = "") -> str:
        """安全读取字符串字段（字段可能不存在于旧版 GPKG）"""
        try:
            val = feat.attribute(field)
            return str(val).strip() if val is not None else default
        except (KeyError, ValueError):
            return default

    @staticmethod
    def _safe_float(feat, field: str, default: float = 0.0) -> float:
        """安全读取浮点字段"""
        try:
            val = feat.attribute(field)
            return float(val) if val is not None else default
        except (KeyError, ValueError, TypeError):
            return default

    @staticmethod
    def _safe_int(feat, field: str, default: int = 0) -> int:
        """安全读取整数字段"""
        try:
            val = feat.attribute(field)
            return int(val) if val is not None else default
        except (KeyError, ValueError, TypeError):
            return default


class RotationWorker(QObject):
    """后台轮灌 Worker（必须在 QThread 中运行）"""

    progress_changed = pyqtSignal(int, str)
    finished = pyqtSignal(list)       # results list
    error_occurred = pyqtSignal(str)

    def __init__(self, scheduler: RotationScheduler, shift_groups: list, parent=None):
        super().__init__(parent)
        self._scheduler = scheduler
        self._groups = shift_groups

    def run(self):
        """后台运行轮灌（由 QThread.started 触发）"""
        try:
            results = self._scheduler.run_rotation(
                self._groups,
                progress_callback=lambda p, m: self.progress_changed.emit(p, m))
            self.finished.emit(results)
        except Exception as e:
            import traceback
            self.error_occurred.emit(f"{e}\n{traceback.format_exc()}")
