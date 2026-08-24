"""RotationDialog — 轮灌配置对话框（纯定量灌溉）"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QComboBox, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QProgressBar,
    QHeaderView, QTextEdit,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication


class RotationDialog(QDialog):
    """轮灌配置对话框"""

    rotation_requested = pyqtSignal(dict)

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self._scheduler = None
        self._field_data = []
        self._zones_data = []
        self._running = False

        self.setWindowTitle(QApplication.translate("RotationDialog", "aQuaDrip 轮灌管理"))
        self.setMinimumWidth(520)
        self.setMinimumHeight(400)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ── 田块选择 ──
        field_layout = QHBoxLayout()
        field_layout.addWidget(QLabel(QApplication.translate("RotationDialog", "田块:")))
        self._combo_field = QComboBox()
        self._combo_field.setMinimumWidth(200)
        self._combo_field.currentIndexChanged.connect(self._on_field_changed)
        field_layout.addWidget(self._combo_field)
        field_layout.addStretch()
        layout.addLayout(field_layout)

        # ── 分区表格：分区 | 阀门 | 灌溉量(mm) | 顺序 ──
        label = QLabel(QApplication.translate("RotationDialog", "分区灌溉量配置（双击灌溉量编辑）:"))
        layout.addWidget(label)

        table_layout = QHBoxLayout()
        self._zone_table = QTableWidget(0, 4)
        self._zone_table.setHorizontalHeaderLabels(
            [QApplication.translate("RotationDialog", "分区"), QApplication.translate("RotationDialog", "阀门"), QApplication.translate("RotationDialog", "灌溉量(mm)"), QApplication.translate("RotationDialog", "顺序")])
        self._zone_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self._zone_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self._zone_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents)
        self._zone_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents)
        self._zone_table.itemChanged.connect(self._on_item_changed)
        self._zone_table.setEditTriggers(QTableWidget.DoubleClicked)
        table_layout.addWidget(self._zone_table)

        # 上下移动按钮
        btn_col = QVBoxLayout()
        self._btn_up = QPushButton("▲")
        self._btn_up.setFixedWidth(32)
        self._btn_up.setToolTip(QApplication.translate("RotationDialog", "上移"))
        self._btn_up.clicked.connect(self._on_move_up)
        self._btn_up.setEnabled(False)
        btn_col.addWidget(self._btn_up)
        self._btn_down = QPushButton("▼")
        self._btn_down.setFixedWidth(32)
        self._btn_down.setToolTip(QApplication.translate("RotationDialog", "下移"))
        self._btn_down.clicked.connect(self._on_move_down)
        self._btn_down.setEnabled(False)
        btn_col.addWidget(self._btn_down)
        btn_col.addStretch()
        table_layout.addLayout(btn_col)
        layout.addLayout(table_layout, stretch=1)

        # ── 结果 ──
        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setMaximumHeight(120)
        self._result_text.setPlaceholderText(QApplication.translate("RotationDialog", "运行结果将显示在此..."))
        layout.addWidget(self._result_text)

        # ── 进度 ──
        self._progress = QProgressBar()
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        # ── 按钮 ──
        btn_layout = QHBoxLayout()
        self._btn_run = QPushButton(QApplication.translate("RotationDialog", "▶ 运行轮灌模拟"))
        self._btn_run.setStyleSheet("font-weight: bold;")
        self._btn_run.clicked.connect(self._on_run)
        self._btn_run.setEnabled(False)
        btn_layout.addWidget(self._btn_run)

        self._btn_stop = QPushButton(QApplication.translate("RotationDialog", "⏹ 停止"))
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)
        btn_layout.addWidget(self._btn_stop)

        btn_layout.addStretch()
        self._btn_close = QPushButton(QApplication.translate("RotationDialog", "关闭"))
        self._btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_close)
        layout.addLayout(btn_layout)

    def reject(self):
        self._running = False
        super().reject()

    # ── 数据加载 ──

    def set_field_data(self, features: list, selected_id: int = -1):
        self._field_data = features
        self._combo_field.blockSignals(True)
        self._combo_field.clear()
        target_idx = 0
        for i, feat in enumerate(features):
            name = str(feat.attribute("name") or QApplication.translate("RotationDialog", "田块_{0}").format(feat.id()))
            self._combo_field.addItem(name, feat.id())
            if feat.id() == selected_id:
                target_idx = i
        self._combo_field.blockSignals(False)
        if features:
            self._combo_field.setCurrentIndex(target_idx)
            self._on_field_changed(target_idx)

    def _on_field_changed(self, idx: int):
        if idx < 0 or idx >= len(self._field_data):
            return
        feat = self._field_data[idx]
        from ..tools.rotation_scheduler import RotationScheduler
        self._scheduler = RotationScheduler(self.iface)
        data = self._scheduler.collect_field_data(feat)
        self._zones_data = data.get("zones", [])
        self._populate_table()

    # ── 表格 ──

    def _populate_table(self):
        self._zone_table.blockSignals(True)
        self._zone_table.setRowCount(0)

        # 按 order 排序
        sorted_zones = sorted(self._zones_data, key=lambda z: z.get("order", 99))
        for i, z in enumerate(sorted_zones):
            # 自动编号顺序
            z["order"] = i + 1

            row = self._zone_table.rowCount()
            self._zone_table.insertRow(row)

            item = QTableWidgetItem(z["zone"])
            item.setFlags(Qt.ItemIsEnabled)
            self._zone_table.setItem(row, 0, item)

            item = QTableWidgetItem(", ".join(z.get("valves", [])))
            item.setFlags(Qt.ItemIsEnabled)
            self._zone_table.setItem(row, 1, item)

            item = QTableWidgetItem(f"{z.get('irrigation_mm', 10.0):.1f}")
            self._zone_table.setItem(row, 2, item)

            item = QTableWidgetItem(str(z["order"]))
            item.setFlags(Qt.ItemIsEnabled)  # 顺序只读，通过按钮调整
            self._zone_table.setItem(row, 3, item)

        self._zone_table.blockSignals(False)
        has_zones = len(self._zones_data) > 0
        self._btn_run.setEnabled(has_zones)
        self._btn_up.setEnabled(has_zones and len(self._zones_data) > 1)
        self._btn_down.setEnabled(has_zones and len(self._zones_data) > 1)

    def _on_item_changed(self, item: QTableWidgetItem):
        col = item.column()
        row = item.row()
        if row >= len(self._zones_data):
            return
        if col == 2:  # 灌溉量
            try:
                self._zones_data[row]["irrigation_mm"] = float(item.text().strip())
            except ValueError:
                pass

    def _on_move_up(self):
        """当前行上移"""
        row = self._zone_table.currentRow()
        if row <= 0 or row >= len(self._zones_data):
            return
        self._zones_data[row], self._zones_data[row - 1] = \
            self._zones_data[row - 1], self._zones_data[row]
        self._zone_table.selectRow(row - 1)
        self._renumber_and_refresh()

    def _on_move_down(self):
        """当前行下移"""
        row = self._zone_table.currentRow()
        if row < 0 or row >= len(self._zones_data) - 1:
            return
        self._zones_data[row], self._zones_data[row + 1] = \
            self._zones_data[row + 1], self._zones_data[row]
        self._zone_table.selectRow(row + 1)
        self._renumber_and_refresh()

    def _renumber_and_refresh(self):
        """重新编号并刷新表格"""
        for i, z in enumerate(self._zones_data):
            z["order"] = i + 1
        self._populate_table()

    def _sync_from_table(self):
        """从表格读取灌溉量到 zones_data"""
        for row in range(min(self._zone_table.rowCount(), len(self._zones_data))):
            item = self._zone_table.item(row, 2)
            if item:
                try:
                    self._zones_data[row]["irrigation_mm"] = float(item.text().strip())
                except ValueError:
                    pass
            item = self._zone_table.item(row, 3)
            if item:
                try:
                    self._zones_data[row]["order"] = int(item.text().strip())
                except ValueError:
                    pass

    # ── 运行 ──

    def _on_run(self):
        if not self._zones_data:
            return
        # 从表格同步灌溉量
        self._sync_from_table()
        self._running = True
        self._result_text.clear()
        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_close.setEnabled(False)
        self._btn_up.setEnabled(False)
        self._btn_down.setEnabled(False)
        self._progress.setValue(0)
        config = {"zones": self._zones_data,
                  "field_idx": self._combo_field.currentIndex()}
        self.rotation_requested.emit(config)

    def _on_stop(self):
        self._running = False
        self._done_state()

    def _done_state(self):
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_close.setEnabled(True)
        has_zones = len(self._zones_data) > 1
        self._btn_up.setEnabled(has_zones)
        self._btn_down.setEnabled(has_zones)

    def on_progress(self, pct: int, msg: str):
        self._progress.setValue(pct)
        self._progress.setFormat(msg)

    def on_done(self, results: list):
        self._running = False
        self._done_state()
        ok = sum(1 for r in results if "error" not in r)
        self._progress.setValue(100)

        # 在对话框中展示结果
        lines = []
        for r in results:
            if r.get("error"):
                lines.append(QApplication.translate("RotationDialog", "❌ 分区 {0}: {1}").format(r['zone'], r['error'][:80]))
            else:
                lines.append(
                    QApplication.translate("RotationDialog", "✅ 分区 {0}  灌{1:.0f}mm  CU={2:.1f}% DU={3:.1f}%  均压{4:.2f}m  最大{5:.2f}m  需{6:.0f}min").format(r['zone'], r['irrigation_mm'], r['cu'], r['du'], r['avg_pressure_m'], r['max_pressure_m'], r['duration_min'])
                )
        self._result_text.setPlainText("\n".join(lines))
        self._progress.setFormat(QApplication.translate("RotationDialog", "完成 ({0}/{1} 分区)").format(ok, len(results)))
