"""VisualizeDialog — 模拟历史记录列表与可视化浮动窗

显示历史记录列表，用户选择某条记录后点击"可视化"，
生成 results 图层在地图上展示。
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QComboBox, QMessageBox,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal

from ..tools.sim_history import SimHistory


class VisualizeDialog(QDialog):
    """模拟历史可视化浮动窗"""

    visualize_requested = pyqtSignal(dict, str)  # (record, mode)

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.history = None
        self.records = []

        self.setWindowTitle("aQuaDrip 模拟历史")
        self.setMinimumWidth(420)
        self.setMinimumHeight(360)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._build_ui()
        self._load_gpkg_path()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 说明
        hint = QLabel("选择一条记录进行可视化（结果保存为临时图层）")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        # 记录计数
        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self._count_label)

        # 历史列表
        self.list_widget = QListWidget()
        self.list_widget.doubleClicked.connect(self._on_visualize)
        layout.addWidget(self.list_widget)

        # 着色模式选择
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("节点着色:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("压力（蓝→红）", "pressure")
        self.mode_combo.addItem("滴头流量（蓝→红）", "emitter")
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()

        # 轮灌轮次过滤器
        self._shift_label = QLabel("轮次:")
        self._shift_combo = QComboBox()
        self._shift_combo.currentIndexChanged.connect(self._on_filter_changed)
        mode_layout.addWidget(self._shift_label)
        mode_layout.addWidget(self._shift_combo)
        self._shift_label.hide()
        self._shift_combo.hide()
        layout.addLayout(mode_layout)

        # 按钮
        btn_layout = QHBoxLayout()
        self.btn_visualize = QPushButton("📊 可视化")
        self.btn_visualize.setStyleSheet("font-weight: bold;")
        self.btn_visualize.clicked.connect(self._on_visualize)
        btn_layout.addWidget(self.btn_visualize)

        self.btn_delete = QPushButton("🗑 删除")
        self.btn_delete.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.btn_delete)

        self.btn_purge = QPushButton("🗑 清空全部")
        self.btn_purge.setStyleSheet("color: #c0392b;")
        self.btn_purge.clicked.connect(self._on_purge_all)
        btn_layout.addWidget(self.btn_purge)

        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        # 空状态提示
        self.empty_label = QLabel("暂无模拟记录\n\n请先运行模拟")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: gray; font-size: 14px;")
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

    def _load_gpkg_path(self):
        """从当前项目找 aqd_pipes 图层的 GPKG 路径"""
        from qgis.core import QgsProject, QgsVectorLayer
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            s = layer.source() if hasattr(layer, "source") else ""
            if "aqd_pipes" in s or layer.name() == "aqd_pipes":
                # source 格式: /path/to/aquadrip.gpkg|layername=aqd_pipes
                gpkg_path = s.split("|")[0]
                if gpkg_path.endswith(".gpkg"):
                    self.history = SimHistory(gpkg_path)
                    self._refresh_list()
                    return
        # 没找到 GPKG
        self.empty_label.setText("未找到 aQuaDrip 项目\n请先加载或创建项目")
        self.empty_label.show()
        self.list_widget.hide()

    def _refresh_list(self):
        """刷新历史列表"""
        if not self.history:
            return
        self.records = self.history.load()
        self.list_widget.clear()

        if not self.records:
            self.empty_label.show()
            self.list_widget.hide()
            return

        self.empty_label.hide()
        self.list_widget.show()

        # 收集所有轮灌组用于过滤器
        rotation_ids = set()
        for record in self.records:
            rid = record.get("rotation_id")
            if rid:
                rotation_ids.add(rid)

        self._shift_combo.blockSignals(True)
        self._shift_combo.clear()
        self._shift_combo.addItem("全部记录", "")
        for rid in sorted(rotation_ids):
            self._shift_combo.addItem(f"轮灌 {rid}", rid)
        has_rotation = len(rotation_ids) > 0
        self._shift_combo.setVisible(has_rotation)
        self._shift_label.setVisible(has_rotation)
        self._shift_combo.blockSignals(False)

        self._count_label.setText(f"共 {len(self.records)} 条记录"
                                  f"（上限 {SimHistory.MAX_RECORDS}）")
        self._update_list_display()

    def _on_filter_changed(self):
        self._update_list_display()

    def _update_list_display(self):
        """根据过滤器更新列表显示"""
        filter_rid = self._shift_combo.currentData() if hasattr(self, '_shift_combo') else ""
        self.list_widget.clear()
        for record in self.records:
            if filter_rid and record.get("rotation_id") != filter_rid:
                continue
            summary = SimHistory.summary(record)
            item = QListWidgetItem(summary)
            self.list_widget.addItem(item)

    def _on_visualize(self):
        """可视化选中的记录"""
        row = self.list_widget.currentRow()
        if row < 0:
            QMessageBox.information(self, "aQuaDrip", "请先选择一条记录")
            return
        record = self.records[row]
        mode = self.mode_combo.currentData()
        self.visualize_requested.emit(record, mode)

    def _on_delete(self):
        """删除选中的记录"""
        row = self.list_widget.currentRow()
        if row < 0:
            QMessageBox.information(self, "aQuaDrip", "请先选择一条记录")
            return

        reply = QMessageBox.question(
            self, "aQuaDrip", "确定删除该记录？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        if self.history.delete(row):
            self._refresh_list()
            self.iface.messageBar().pushMessage(
                "aQuaDrip", "记录已删除", level=0, duration=3)

    def _on_purge_all(self):
        """清空全部历史记录"""
        if not self.history or self.history.count == 0:
            QMessageBox.information(self, "aQuaDrip", "没有可删除的记录")
            return

        reply = QMessageBox.warning(
            self, "aQuaDrip",
            f"确定清空全部 {self.history.count} 条历史记录？\n此操作不可撤销！",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        deleted = self.history.purge_all()
        self._refresh_list()
        self.iface.messageBar().pushMessage(
            "aQuaDrip", f"已清空 {deleted} 条记录", level=0, duration=3)
