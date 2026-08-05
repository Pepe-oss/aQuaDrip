"""aQuaDrip 主面板 — 日志区 + 校准 tab

- 日志 tab: 操作日志（保留原有功能）
- 校准 tab: 观测点表格 + 实测值编辑 + 校准按钮
"""

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QTabWidget, QTableWidget, QTableWidgetItem, QPushButton,
    QLabel, QHeaderView,
)
from qgis.PyQt.QtCore import Qt


class AQuaDripDockWidget(QDockWidget):
    """aQuaDrip 主面板（日志 + 校准）"""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("aQuaDrip")
        self.setObjectName("aQuaDripDockWidget")
        self.setMinimumWidth(320)
        self.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)

        # Tab 容器
        self._tabs = QTabWidget()
        self.setWidget(self._tabs)

        # ── Tab 1: 日志 ──
        self._log_tab = QWidget()
        log_layout = QVBoxLayout(self._log_tab)
        log_layout.setContentsMargins(4, 4, 4, 4)
        log_layout.setSpacing(4)

        hint = QLabel("功能入口在顶部 aQuaDrip 工具栏")
        hint.setStyleSheet("color: gray;")
        log_layout.addWidget(hint)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("操作日志...")
        from qgis.PyQt.QtGui import QFont
        self.log.setFont(QFont("Menlo", 9))
        log_layout.addWidget(self.log, stretch=1)

        self._tabs.addTab(self._log_tab, "日志")

        # ── Tab 2: 校准 ──
        self._calib_tab = QWidget()
        calib_layout = QVBoxLayout(self._calib_tab)
        calib_layout.setContentsMargins(4, 4, 4, 4)
        calib_layout.setSpacing(4)

        # 观测点表格（7列：观测点 | 实测P | 模拟P | ΔP | 实测Q | 模拟Q | ΔQ）
        self._obs_table = QTableWidget(0, 7)
        self._obs_table.setHorizontalHeaderLabels(
            ["观测点", "实测P(m)", "模拟P(m)", "ΔP(m)",
             "实测Q(L/h)", "模拟Q(L/h)", "ΔQ(L/h)"])
        self._obs_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        for col in range(1, 7):
            self._obs_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeToContents)
        self._obs_table.setEditTriggers(
            QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        self._obs_table.cellChanged.connect(self._on_obs_cell_changed)
        self._obs_table.currentCellChanged.connect(self._on_row_selected)
        calib_layout.addWidget(self._obs_table)

        # 统计行
        self._calib_stats = QLabel("点击「刷新模拟值」获取模拟压力...")
        self._calib_stats.setStyleSheet("color: gray; font-size: 11px;")
        calib_layout.addWidget(self._calib_stats)

        # 按钮
        btn_layout = QHBoxLayout()
        self._btn_refresh = QPushButton("🔄 刷新模拟值")
        self._btn_refresh.setToolTip("运行模拟并将结果回填到观测点")
        btn_layout.addWidget(self._btn_refresh)

        self._btn_calibrate = QPushButton("🎯 开始校准")
        self._btn_calibrate.setToolTip("根据实测-模拟误差调整管道粗糙系数")
        self._btn_calibrate.setStyleSheet("font-weight: bold;")
        btn_layout.addWidget(self._btn_calibrate)
        calib_layout.addLayout(btn_layout)

        self._tabs.addTab(self._calib_tab, "校准")

        # 校准迭代计数器
        self._calib_iteration = 0

        # ── Tab 3: 轮灌 ──
        self._rotation_tab = QWidget()
        rot_layout = QVBoxLayout(self._rotation_tab)
        rot_layout.setContentsMargins(4, 4, 4, 4)
        rot_layout.setSpacing(4)

        # 轮灌结果表（分区、阀门、灌溉量、均P、最大P、CU%、DU%、时长）
        self._rot_table = QTableWidget(0, 8)
        self._rot_table.setHorizontalHeaderLabels(
            ["分区", "阀门", "灌溉量", "均P(m)", "最大P(m)", "CU%", "DU%", "时长(min)"])
        self._rot_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._rot_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for col in range(2, 8):
            self._rot_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeToContents)
        rot_layout.addWidget(self._rot_table)

        self._rot_stats = QLabel("点击「轮灌管理」工具栏按钮配置并运行轮灌")
        self._rot_stats.setStyleSheet("color: gray; font-size: 11px;")
        rot_layout.addWidget(self._rot_stats)

        rot_btn = QHBoxLayout()
        rot_btn.addStretch()
        self._btn_rot_visualize = QPushButton("📊 可视化轮次")
        self._btn_rot_visualize.setEnabled(False)
        rot_btn.addWidget(self._btn_rot_visualize)
        rot_layout.addLayout(rot_btn)

        self._tabs.addTab(self._rotation_tab, "轮灌")

        self._rotation_results = []  # 缓存最新轮灌结果

    # ── 日志 ──

    def log_message(self, msg: str):
        """追加日志"""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {msg}")
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ── 校准 tab ──

    def refresh_obs_points(self, sim_result=None):
        """从 aqd_obs_points 图层加载观测点，可选填入模拟值。

        Args:
            sim_result: SimulationResult 或 None
        """
        layer = self._find_obs_layer()
        if layer is None:
            return

        # 从 sim_history 加载 node_coords / link_geometry / link_flow
        nc_data, lg_data, lf_data = self._load_latest_network_coords()

        self._obs_table.setRowCount(0)
        self._obs_table.blockSignals(True)
        try:
            for feat in layer.getFeatures():
                row = self._obs_table.rowCount()
                self._obs_table.insertRow(row)

                name = str(feat.attribute("name") or f"obs_{feat.id()}")
                otype = str(feat.attribute("type") or "junction")
                label = f"{name} [{otype}]"
                self._obs_table.setItem(row, 0, QTableWidgetItem(label))
                self._obs_table.item(row, 0).setFlags(Qt.ItemIsEnabled)

                # ── 压力 ──
                measured_p = feat.attribute("measured_pressure")
                measured_p = float(measured_p) if measured_p else None
                sim_p = self._find_nearest_pressure(feat, sim_result, nc_data) if sim_result else None
                self._set_editable_cell(row, 1, measured_p)
                self._set_readonly_cell(row, 2, sim_p)
                self._set_error_cell(row, 3, sim_p, measured_p)

                # ── 流量 ──
                measured_q = feat.attribute("measured_flow")
                measured_q = float(measured_q) if measured_q else None
                sim_q = self._find_nearest_flow(feat, lg_data, lf_data) if lf_data else None
                self._set_editable_cell(row, 4, measured_q)
                self._set_readonly_cell(row, 5, sim_q)
                self._set_error_cell(row, 6, sim_q, measured_q)

        finally:
            self._obs_table.blockSignals(False)

        # 回写 simulated_pressure 到图层
        if sim_result is not None:
            self._write_sim_to_obs_layer(layer, sim_result, nc_data, lg_data)

        self._update_stats()

    def reset_calibration(self):
        """重置校准迭代计数和按钮状态"""
        self._calib_iteration = 0
        self._calib_stats.setText("校准已重置")
        self._btn_calibrate.setEnabled(True)
        self._btn_refresh.setEnabled(True)

    def set_calibrating(self, calibrating: bool):
        """设置校准中状态（禁用按钮防重复点击）"""
        self._btn_calibrate.setEnabled(not calibrating)
        self._btn_refresh.setEnabled(not calibrating)

    def add_calib_iteration(self, rmse: float):
        """记录一次校准迭代"""
        self._calib_iteration += 1
        self._calib_stats.setText(
            f"校准迭代 {self._calib_iteration} 次  "
            f"RMSE = {rmse:.2f} m")

    def get_measured_values(self) -> dict:
        """从表格读取用户输入的实测值。

        Returns:
            {obs_label: (pressure_or_None, flow_or_None)}
        """
        result = {}
        for row in range(self._obs_table.rowCount()):
            label = self._obs_table.item(row, 0)
            if label is None:
                continue
            p_item = self._obs_table.item(row, 1)
            q_item = self._obs_table.item(row, 4)
            p_val = None
            q_val = None
            try:
                p_val = float(p_item.text().strip()) if p_item and p_item.text().strip() else None
            except (ValueError, AttributeError):
                pass
            try:
                q_val = float(q_item.text().strip()) if q_item and q_item.text().strip() else None
            except (ValueError, AttributeError):
                pass
            if p_val is not None or q_val is not None:
                # 去掉 "[type]" 后缀，用纯名称做 key
                key = label.text().split(" [")[0] if " [" in label.text() else label.text()
                result[key] = (p_val, q_val)
        return result

    # ── 表格单元格辅助 ──

    def _set_editable_cell(self, row: int, col: int, value):
        """设置可编辑单元格（实测值）"""
        if value is not None:
            item = QTableWidgetItem(f"{value:.2f}")
        else:
            item = QTableWidgetItem("")
        self._obs_table.setItem(row, col, item)

    def _set_readonly_cell(self, row: int, col: int, value):
        """设置只读单元格（模拟值）"""
        if value is not None:
            item = QTableWidgetItem(f"{value:.2f}")
        else:
            item = QTableWidgetItem("—")
        item.setFlags(Qt.ItemIsEnabled)
        self._obs_table.setItem(row, col, item)

    def _set_error_cell(self, row: int, col: int, sim_val, meas_val):
        """设置误差单元格（ΔP 或 ΔQ）"""
        if meas_val is not None and sim_val is not None:
            err = sim_val - meas_val
            item = QTableWidgetItem(f"{err:+.2f}")
            if abs(err) < (0.5 if col == 3 else 5.0):
                item.setForeground(Qt.green)
            else:
                item.setForeground(Qt.red)
            item.setFlags(Qt.ItemIsEnabled)
            self._obs_table.setItem(row, col, item)
        else:
            item = QTableWidgetItem("—")
            item.setFlags(Qt.ItemIsEnabled)
            self._obs_table.setItem(row, col, item)

    # ── 内部 ──

    def _on_row_selected(self, row: int, col: int, prev_row: int, prev_col: int):
        """选中某行时在地图上高亮对应观测点"""
        if row < 0:
            return
        label_item = self._obs_table.item(row, 0)
        if label_item is None:
            return
        label = label_item.text()
        obs_name = label.split(" [")[0] if " [" in label else label

        layer = self._find_obs_layer()
        if layer is None:
            return
        for feat in layer.getFeatures():
            name = str(feat.attribute("name") or f"obs_{feat.id()}")
            if name == obs_name:
                self.iface.mapCanvas().flashFeatureIds(layer, [feat.id()], flashes=2)
                return

    def _on_obs_cell_changed(self, row: int, col: int):
        """表格编辑 → 写回 aqd_obs_points 图层。col 1=压力, col 4=流量"""
        if col not in (1, 4):
            return
        label_item = self._obs_table.item(row, 0)
        val_item = self._obs_table.item(row, col)
        if label_item is None or val_item is None:
            return
        layer = self._find_obs_layer()
        if layer is None:
            return

        label = label_item.text()
        obs_name = label.split(" [")[0] if " [" in label else label
        try:
            new_val = float(val_item.text().strip())
        except ValueError:
            return

        field = "measured_pressure" if col == 1 else "measured_flow"
        need_edit = not layer.isEditable()
        if need_edit:
            layer.startEditing()
        try:
            for feat in layer.getFeatures():
                name = str(feat.attribute("name") or f"obs_{feat.id()}")
                if name == obs_name:
                    feat.setAttribute(field, new_val)
                    layer.updateFeature(feat)
                    break
            if need_edit:
                layer.commitChanges()
        except Exception:
            if need_edit:
                layer.rollBack()
            raise

        # 更新误差列
        err_col = 3 if col == 1 else 6
        sim_item = self._obs_table.item(row, 2 if col == 1 else 5)
        if sim_item is not None:
            try:
                sim_v = float(sim_item.text()) if sim_item.text() != "—" else None
            except ValueError:
                sim_v = None
            self._set_error_cell(row, err_col, sim_v, new_val)
        self._update_stats()

    def _update_error_column(self, row: int):
        """计算并更新指定行的误差列"""
        sim_item = self._obs_table.item(row, 2)
        meas_item = self._obs_table.item(row, 1)
        if sim_item is None or meas_item is None:
            return
        try:
            sim_v = float(sim_item.text().strip() if sim_item.text() != "—" else "0")
            meas_v = float(meas_item.text().strip())
        except ValueError:
            return
        err = sim_v - meas_v
        err_item = QTableWidgetItem(f"{err:+.2f}")
        if abs(err) < 0.5:
            err_item.setForeground(Qt.green)
        else:
            err_item.setForeground(Qt.red)
        err_item.setFlags(Qt.ItemIsEnabled)
        self._obs_table.setItem(row, 3, err_item)
        self._update_stats()

    def _update_stats(self):
        """更新统计标签"""
        errors = []
        for row in range(self._obs_table.rowCount()):
            err_item = self._obs_table.item(row, 3)
            if err_item and err_item.text() not in ("—", ""):
                try:
                    errors.append(float(err_item.text()))
                except ValueError:
                    pass
        if errors:
            rmse = (sum(e * e for e in errors) / len(errors)) ** 0.5
            mae = sum(abs(e) for e in errors) / len(errors)
            self._calib_stats.setText(
                f"RMSE = {rmse:.2f} m  (MAE = {mae:.2f} m)  "
                f"n = {len(errors)}")
        else:
            self._calib_stats.setText("点击「刷新模拟值」获取模拟压力...")

    @staticmethod
    def _load_latest_network_coords():
        """从 simhistory 加载最新记录的 node_coords, link_geometry, link_flow"""
        from qgis.core import QgsProject, QgsVectorLayer
        gpkg_path = None
        for _lid, layer in QgsProject.instance().mapLayers().items():
            if not isinstance(layer, QgsVectorLayer):
                continue
            s = layer.source() if hasattr(layer, "source") else ""
            if "aqd_fields" in s or layer.name() == "aqd_fields":
                gpkg_path = s.split("|")[0]
                break
        if not gpkg_path:
            return {}, {}, {}
        from ..tools.sim_history import SimHistory
        h = SimHistory(gpkg_path)
        records = h.load()
        if not records:
            return {}, {}, {}
        r = records[0]
        return (r.get("node_coords", {}),
                r.get("link_geometry", {}),
                r.get("link_flow", {}))

    @staticmethod
    def _find_nearest_flow(feat, lg_data, lf_data):
        """找到观测点最近管段的流量 (L/h)。

        用 link_geometry 做点到折线最近匹配。
        """
        if not lg_data or not lf_data:
            return None
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            return None
        pt = geom.asPoint()

        best_d, best_f = float('inf'), None
        for lid, pts in lg_data.items():
            if not pts or len(pts) < 2:
                continue
            for i in range(len(pts) - 1):
                ax, ay = pts[i][0], pts[i][1]
                bx, by = pts[i+1][0], pts[i+1][1]
                dx, dy = bx - ax, by - ay
                l2 = dx*dx + dy*dy
                if l2 < 1e-20:
                    d = ((pt.x()-ax)**2 + (pt.y()-ay)**2) ** 0.5
                else:
                    t = max(0, min(1, ((pt.x()-ax)*dx + (pt.y()-ay)*dy) / l2))
                    px, py = ax + t*dx, ay + t*dy
                    d = ((pt.x()-px)**2 + (pt.y()-py)**2) ** 0.5
                if d < best_d:
                    best_d = d
                    f = lf_data.get(lid)
                    if f is not None:
                        best_f = abs(float(f)) if isinstance(f, (int, float)) else None
        return best_f

    def _write_sim_to_obs_layer(self, layer, sim_result, nc_data, lg_data):
        """回填 simulated_pressure + simulated_flow 到 aqd_obs_points"""
        if layer is None:
            return
        # 加载 link_flow
        _, _, lf_data = self._load_latest_network_coords()
        need_edit = not layer.isEditable()
        if need_edit:
            layer.startEditing()
        try:
            for feat in layer.getFeatures():
                sp = self._find_nearest_pressure(feat, sim_result, nc_data)
                sq = self._find_nearest_flow(feat, lg_data, lf_data)
                if sp is not None:
                    feat.setAttribute("simulated_pressure", float(sp))
                if sq is not None:
                    feat.setAttribute("simulated_flow", float(sq))
                if sp is not None or sq is not None:
                    layer.updateFeature(feat)
            if need_edit:
                layer.commitChanges()
        except Exception:
            if need_edit:
                layer.rollBack()

    @staticmethod
    def _find_nearest_pressure(feat, sim_result, nc_data=None, lg_data=None):
        """找到观测点最近**滴头**的模拟压力。

        优先匹配 E_* (滴头) 和 auto_N (毛管端点)，其次 N* (节点)。
        滴头沿毛管等距分布（~0.3m），密度远大于连接点，匹配精度更高。
        """
        if sim_result is None:
            return None
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            return None
        pt = geom.asPoint()
        node_pressure = getattr(sim_result, "node_pressure", {})

        if not nc_data:
            return None

        # 分两组搜索：滴头/毛管端点优先，连接点兜底
        def _best_match(nodes):
            best_d, best_p = float('inf'), None
            for nid in nodes:
                c = nc_data.get(nid)
                if c is None or len(c) < 2:
                    continue
                d = (pt.x() - c[0]) ** 2 + (pt.y() - c[1]) ** 2
                if d < best_d:
                    best_d = d
                    p_arr = node_pressure.get(nid)
                    if p_arr is not None and len(p_arr) > 0:
                        best_p = float(p_arr[0])
            return best_p

        # 1. 优先：E_* 滴头节点（间距 0.3m，匹配精度最高）
        emitters = [k for k in nc_data if k.startswith("E_")]
        best_p = _best_match(emitters)
        if best_p is not None:
            return best_p

        # 2. 次选：auto_N 毛管端点
        auto_n = [k for k in nc_data if k.startswith("auto_N")]
        best_p = _best_match(auto_n)
        if best_p is not None:
            return best_p

        # 3. 兜底：所有节点（含 N* 连接点）
        return _best_match(nc_data.keys())

    def _find_obs_layer(self):
        """查找 aqd_obs_points 图层"""
        from qgis.core import QgsProject, QgsVectorLayer
        for _lid, layer in QgsProject.instance().mapLayers().items():
            if not isinstance(layer, QgsVectorLayer):
                continue
            src = layer.source() if hasattr(layer, "source") else ""
            if "aqd_obs_points" in src or layer.name() == "aqd_obs_points":
                return layer
        return None

    # ── 轮灌 tab ──

    def show_rotation_results(self, results: list, rotation_id: str = ""):
        """在轮灌 tab 中展示模拟结果

        Args:
            results: [{zone, valves, irrigation_mm, cu, du, avg_pressure_m, duration_min, ...}, ...]
        """
        self._rotation_results = results
        self._rot_table.setRowCount(0)
        self._rot_table.blockSignals(True)
        try:
            for r in results:
                row = self._rot_table.rowCount()
                self._rot_table.insertRow(row)
                zone = r.get("zone", "?")
                valves_str = ", ".join(r.get("valves", []))
                mm_val = r.get("irrigation_mm", 0)
                avg_p = r.get("avg_pressure_m", 0)
                max_p = r.get("max_pressure_m", 0)
                cu = r.get("cu", 0)
                du = r.get("du", 0)
                dur = r.get("duration_min", 0)
                error = r.get("error")

                if error:
                    for col, val in enumerate(
                        [zone, valves_str, f"{mm_val:.0f}mm", error, "—", "—", "—", "—"]):
                        item = QTableWidgetItem(val)
                        item.setFlags(Qt.ItemIsEnabled)
                        self._rot_table.setItem(row, col, item)
                else:
                    for col, val in enumerate(
                        [zone, valves_str, f"{mm_val:.0f}mm",
                         f"{avg_p:.2f}", f"{max_p:.2f}",
                         f"{cu:.1f}", f"{du:.1f}", f"{dur:.0f}"]):
                        item = QTableWidgetItem(val)
                        item.setFlags(Qt.ItemIsEnabled)
                        self._rot_table.setItem(row, col, item)
        finally:
            self._rot_table.blockSignals(False)

        success_count = sum(1 for r in results if "error" not in r or not r.get("error"))
        self._rot_stats.setText(
            f"轮灌 {rotation_id}  共 {len(results)} 分区  "
            f"成功 {success_count} 个")
        self._btn_rot_visualize.setEnabled(success_count > 0)

    def clear_rotation(self):
        """清空轮灌结果"""
        self._rotation_results = []
        self._rot_table.setRowCount(0)
        self._rot_stats.setText("点击「轮灌管理」工具栏按钮配置并运行轮灌")
        self._btn_rot_visualize.setEnabled(False)
