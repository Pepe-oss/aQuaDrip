"""RotationDialog — 轮灌配置对话框

- 选择田块
- 选择模式（定时间 / 定量）
- 编辑各分区轮灌参数
- 运行轮灌模拟
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QComboBox, QRadioButton, QButtonGroup, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QProgressBar, QDoubleSpinBox, QSpinBox,
    QHeaderView,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal


class RotationDialog(QDialog):
    """轮灌配置对话框"""

    # 信号：请求异步运行基准模拟（定量模式用）
    baseline_requested = pyqtSignal()
    # 信号：请求异步运行轮灌
    rotation_requested = pyqtSignal(dict)  # config dict

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self._scheduler = None
        self._field_data = []
        self._zones_data = []
        self._running = False

        self.setWindowTitle("aQuaDrip 轮灌管理")
        self.setMinimumWidth(520)
        self.setMinimumHeight(420)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ── 田块选择 ──
        field_layout = QHBoxLayout()
        field_layout.addWidget(QLabel("田块:"))
        self._combo_field = QComboBox()
        self._combo_field.setMinimumWidth(200)
        self._combo_field.currentIndexChanged.connect(self._on_field_changed)
        field_layout.addWidget(self._combo_field)
        field_layout.addStretch()
        layout.addLayout(field_layout)

        # ── 模式选择 ──
        mode_group = QGroupBox("轮灌模式")
        mode_layout = QHBoxLayout(mode_group)
        self._mode_group = QButtonGroup(self)
        self._radio_time = QRadioButton("定时间")
        self._radio_volume = QRadioButton("定量")
        self._mode_group.addButton(self._radio_time, 0)
        self._mode_group.addButton(self._radio_volume, 1)
        self._radio_time.setChecked(True)
        self._radio_time.toggled.connect(self._on_mode_changed)
        self._radio_volume.toggled.connect(self._on_mode_changed)
        mode_layout.addWidget(self._radio_time)
        mode_layout.addWidget(self._radio_volume)

        # 定量输入
        self._spin_volume = QDoubleSpinBox()
        self._spin_volume.setRange(1, 500)
        self._spin_volume.setValue(10)
        self._spin_volume.setSuffix(" mm")
        self._spin_volume.setVisible(False)
        mode_layout.addWidget(self._spin_volume)
        mode_layout.addStretch()
        layout.addWidget(mode_group)

        # ── 分区表格 ──
        table_label = QLabel("分区轮灌配置:")
        layout.addWidget(table_label)
        self._zone_table = QTableWidget(0, 5)
        self._zone_table.setHorizontalHeaderLabels(
            ["分区", "阀门", "顺序", "时长(min)", "开始-结束"])
        self._zone_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._zone_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for col in range(2, 5):
            self._zone_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeToContents)
        # 时长列可编辑
        self._zone_table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._zone_table, stretch=1)

        # ── 时间轴预览 ──
        self._timeline_label = QLabel("")
        self._timeline_label.setStyleSheet(
            "background: #f0f0f0; padding: 4px; border-radius: 3px; "
            "font-family: Menlo; font-size: 11px;")
        layout.addWidget(self._timeline_label)

        # ── 进度条 ──
        self._progress = QProgressBar()
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        # ── 按钮 ──
        btn_layout = QHBoxLayout()
        self._btn_run = QPushButton("▶ 运行轮灌模拟")
        self._btn_run.setStyleSheet("font-weight: bold;")
        self._btn_run.clicked.connect(self._on_run)
        self._btn_run.setEnabled(False)
        btn_layout.addWidget(self._btn_run)

        self._btn_stop = QPushButton("⏹ 停止")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)
        btn_layout.addWidget(self._btn_stop)

        btn_layout.addStretch()
        self._btn_close = QPushButton("关闭")
        self._btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_close)
        layout.addLayout(btn_layout)

    def reject(self):
        self._running = False
        super().reject()

    # ── 数据加载 ──

    def set_field_data(self, features: list, selected_id: int = -1):
        """加载田块列表（QgsFeature 列表）

        Args:
            features: QgsFeature 列表
            selected_id: 预选田块的 feature ID（-1 表示选第一个）
        """
        self._field_data = features
        self._combo_field.blockSignals(True)
        self._combo_field.clear()
        target_idx = 0
        for i, feat in enumerate(features):
            name = str(feat.attribute("name") or f"田块_{feat.id()}")
            self._combo_field.addItem(name, feat.id())
            if feat.id() == selected_id:
                target_idx = i
        self._combo_field.blockSignals(False)
        if features:
            self._combo_field.setCurrentIndex(target_idx)
            self._on_field_changed(target_idx)

    def _on_field_changed(self, idx: int):
        """切换田块时加载该田块的分区数据"""
        if idx < 0 or idx >= len(self._field_data):
            return
        feat = self._field_data[idx]
        # 创建调度器并收集数据
        from ..tools.rotation_scheduler import RotationScheduler
        self._scheduler = RotationScheduler(self.iface)
        data = self._scheduler.collect_field_data(feat)

        # 设置模式
        mode = data.get("mode", "time")
        self._radio_time.blockSignals(True)
        self._radio_volume.blockSignals(True)
        if mode == "volume":
            self._radio_volume.setChecked(True)
        else:
            self._radio_time.setChecked(True)
        self._radio_time.blockSignals(False)
        self._radio_volume.blockSignals(False)

        self._zones_data = data.get("zones", [])
        self._spin_volume.setVisible(mode == "volume")
        self._populate_zone_table()
        self._update_timeline()

    def _on_mode_changed(self, checked: bool):
        if not checked:
            return
        self._spin_volume.setVisible(self._radio_volume.isChecked())

    # ── 分区表格 ──

    def _populate_zone_table(self):
        """填充分区表格"""
        self._zone_table.blockSignals(True)
        self._zone_table.setRowCount(0)
        for z in self._zones_data:
            row = self._zone_table.rowCount()
            self._zone_table.insertRow(row)

            # 分区名
            item = QTableWidgetItem(z["zone"])
            item.setFlags(Qt.ItemIsEnabled)
            self._zone_table.setItem(row, 0, item)

            # 阀门列表
            item = QTableWidgetItem(", ".join(z.get("valves", [])))
            item.setFlags(Qt.ItemIsEnabled)
            self._zone_table.setItem(row, 1, item)

            # 顺序（可编辑 spin）
            order_str = str(z.get("order", row + 1))
            item = QTableWidgetItem(order_str)
            self._zone_table.setItem(row, 2, item)

            # 时长(min)（可编辑）
            dur = z.get("duration_min", 60)
            item = QTableWidgetItem(f"{dur:.0f}")
            self._zone_table.setItem(row, 3, item)

            # 开始-结束（自动计算，只读）
            item = QTableWidgetItem("—")
            item.setFlags(Qt.ItemIsEnabled)
            self._zone_table.setItem(row, 4, item)

        self._zone_table.blockSignals(False)
        self._btn_run.setEnabled(len(self._zones_data) > 0)

    def _on_item_changed(self, item: QTableWidgetItem):
        """表格编辑后更新时间轴"""
        col = item.column()
        if col in (2, 3):  # 顺序列或时长列改变
            self._update_durations_from_table()
            self._update_timeline()

    def _update_durations_from_table(self):
        """从表格中读取时长更新 zones_data"""
        for row in range(self._zone_table.rowCount()):
            if row >= len(self._zones_data):
                continue
            # 读顺序
            order_item = self._zone_table.item(row, 2)
            if order_item:
                try:
                    self._zones_data[row]["order"] = int(order_item.text().strip())
                except ValueError:
                    pass
            # 读时长
            dur_item = self._zone_table.item(row, 3)
            if dur_item:
                try:
                    self._zones_data[row]["duration_min"] = float(dur_item.text().strip())
                except ValueError:
                    pass

    def _update_timeline(self):
        """更新时间轴预览"""
        self._update_durations_from_table()
        if not self._zones_data:
            self._timeline_label.setText("")
            return

        sorted_zones = sorted(self._zones_data, key=lambda z: z.get("order", 99))
        total_min = sum(z.get("duration_min", 0) for z in sorted_zones)
        if total_min <= 0:
            self._timeline_label.setText("")
            return

        total_h = total_min / 60.0
        max_width = 60  # 字符宽度
        parts = [f"总时长: {total_h:.1f}h  |  "]
        current_min = 0.0
        for z in sorted_zones:
            dur = z.get("duration_min", 0)
            width = max(3, int(dur / total_min * max_width))
            bar = "█" * width
            start_h = current_min / 60.0
            end_h = (current_min + dur) / 60.0
            parts.append(f"{bar} {z['zone']}({start_h:.1f}-{end_h:.1f}h) ")
            current_min += dur

            # 更新表格中的开始-结束列
            for row in range(self._zone_table.rowCount()):
                zone_item = self._zone_table.item(row, 0)
                if zone_item and zone_item.text() == z["zone"]:
                    ts_item = QTableWidgetItem(f"{start_h:.1f}-{end_h:.1f}h")
                    ts_item.setFlags(Qt.ItemIsEnabled)
                    self._zone_table.setItem(row, 4, ts_item)

        self._timeline_label.setText("".join(parts))

    # ── 运行 ──

    def _on_run(self):
        """开始轮灌模拟"""
        if not self._scheduler or not self._zones_data:
            return
        self._update_durations_from_table()

        self._running = True
        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_close.setEnabled(False)
        self._progress.setValue(0)

        if self._radio_volume.isChecked():
            # 定量模式：先跑基准模拟获取流量
            self._progress.setFormat("基准模拟中...")
            self.baseline_requested.emit()
        else:
            # 定时间模式：直接构建调度
            self._start_rotation()

    def _on_stop(self):
        """停止轮灌"""
        self._running = False
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_close.setEnabled(True)

    # ── 由插件端调用的回调 ──

    def get_config(self) -> dict:
        """获取当前轮灌配置"""
        self._update_durations_from_table()
        sorted_zones = sorted(self._zones_data, key=lambda z: z.get("order", 99))
        return {
            "mode": "volume" if self._radio_volume.isChecked() else "time",
            "volume_mm": self._spin_volume.value(),
            "zones": sorted_zones,
            "field_idx": self._combo_field.currentIndex(),
        }

    def on_baseline_done(self, flow_rates: dict):
        """基准模拟完成回调（定量模式）"""
        if not self._running:
            return
        if not flow_rates:
            self._progress.setFormat("基准模拟失败：无法获取分区流量")
            self._on_stop()
            return

        # 计算各分区时长
        vol_mm = self._spin_volume.value()
        for z in self._zones_data:
            q_lph = flow_rates.get(z["zone"], 100.0)
            if q_lph <= 0:
                q_lph = 100.0
            area_m2 = self._scheduler.get_field_area_m2() if self._scheduler else 666.67
            volume_m3 = vol_mm / 1000.0 * area_m2
            dur_h = volume_m3 / (q_lph / 1000.0)
            dur_min = max(1, dur_h * 60.0)
            z["duration_min"] = round(dur_min, 1)

        self._populate_zone_table()
        self._update_timeline()
        self._start_rotation()

    def _start_rotation(self):
        """启动轮灌模拟"""
        config = self.get_config()
        self.rotation_requested.emit(config)

    def on_rotation_progress(self, pct: int, msg: str):
        """轮灌进度回调"""
        self._progress.setValue(pct)
        self._progress.setFormat(msg)

    def on_rotation_done(self, results: list):
        """轮灌完成回调"""
        self._running = False
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_close.setEnabled(True)
        self._progress.setValue(100)
        success = sum(1 for r in results if "error" not in r or not r.get("error"))
        self._progress.setFormat(f"完成 ({success}/{len(results)} 轮次)")
