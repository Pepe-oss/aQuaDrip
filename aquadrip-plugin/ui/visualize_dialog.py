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
from qgis.PyQt.QtWidgets import QApplication


class VisualizeDialog(QDialog):
    """模拟历史可视化浮动窗"""

    visualize_requested = pyqtSignal(dict, str)  # (record, mode)

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.history = None
        # 只保存轻量摘要（KB 级）；完整记录在点击"可视化"时
        # 用 history.get(i) 按需读取单个分片。原先 open 时 load()
        # 解析全部记录（1GB 级 JSON）导致对话框卡住几十秒
        self.summaries = []

        self.setWindowTitle(QApplication.translate("VisualizeDialog", "aQuaDrip 模拟历史"))
        self.setMinimumWidth(420)
        self.setMinimumHeight(360)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._build_ui()
        self._load_gpkg_path()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 说明
        hint = QLabel(QApplication.translate("VisualizeDialog", "选择一条记录进行可视化（结果保存为临时图层）"))
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
        mode_layout.addWidget(QLabel(QApplication.translate("VisualizeDialog", "节点着色:")))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(QApplication.translate("VisualizeDialog", "压力（蓝→红）"), "pressure")
        self.mode_combo.addItem(QApplication.translate("VisualizeDialog", "滴头流量（蓝→红）"), "emitter")
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()

        # 轮灌轮次过滤器
        self._shift_label = QLabel(QApplication.translate("VisualizeDialog", "轮次:"))
        self._shift_combo = QComboBox()
        self._shift_combo.currentIndexChanged.connect(self._on_filter_changed)
        mode_layout.addWidget(self._shift_label)
        mode_layout.addWidget(self._shift_combo)
        self._shift_label.hide()
        self._shift_combo.hide()
        layout.addLayout(mode_layout)

        # 按钮
        btn_layout = QHBoxLayout()
        self.btn_visualize = QPushButton(QApplication.translate("VisualizeDialog", "📊 可视化"))
        self.btn_visualize.setStyleSheet("font-weight: bold;")
        self.btn_visualize.clicked.connect(self._on_visualize)
        btn_layout.addWidget(self.btn_visualize)

        self.btn_export = QPushButton(QApplication.translate("VisualizeDialog", "💾 导出节点"))
        self.btn_export.setToolTip(QApplication.translate(
            "VisualizeDialog", "导出选中记录的节点矢量文件（压力 + 滴头流量）"))
        self.btn_export.clicked.connect(self._on_export_nodes)
        btn_layout.addWidget(self.btn_export)

        self.btn_delete = QPushButton(QApplication.translate("VisualizeDialog", "🗑 删除"))
        self.btn_delete.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.btn_delete)

        self.btn_purge = QPushButton(QApplication.translate("VisualizeDialog", "🗑 清空全部"))
        self.btn_purge.setStyleSheet("color: #c0392b;")
        self.btn_purge.clicked.connect(self._on_purge_all)
        btn_layout.addWidget(self.btn_purge)

        self.btn_close = QPushButton(QApplication.translate("VisualizeDialog", "关闭"))
        self.btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        # 空状态提示
        self.empty_label = QLabel(QApplication.translate("VisualizeDialog", "暂无模拟记录\n\n请先运行模拟"))
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: gray; font-size: 14px;")
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

    def _load_gpkg_path(self):
        """从当前项目找 aqd_pipes 图层的 GPKG 路径"""
        from ..tools.layer_utils import find_gpkg_path
        gpkg_path = find_gpkg_path(None, "aqd_pipes")
        if gpkg_path:
            self.history = SimHistory(gpkg_path)
            self._refresh_list()
            return
        # 没找到 GPKG
        self.empty_label.setText(QApplication.translate("VisualizeDialog", "未找到 aQuaDrip 项目\n请先加载或创建项目"))
        self.empty_label.show()
        self.list_widget.hide()

    def _refresh_list(self):
        """刷新历史列表（只读轻量索引，毫秒级）"""
        if not self.history:
            return
        self.summaries = self.history.summaries()
        self.list_widget.clear()

        if not self.summaries:
            self.empty_label.show()
            self.list_widget.hide()
            return

        self.empty_label.hide()
        self.list_widget.show()

        # 收集所有轮灌组用于过滤器
        rotation_ids = set()
        for record in self.summaries:
            rid = record.get("rotation_id")
            if rid:
                rotation_ids.add(rid)

        self._shift_combo.blockSignals(True)
        self._shift_combo.clear()
        self._shift_combo.addItem(QApplication.translate("VisualizeDialog", "全部记录"), "")
        for rid in sorted(rotation_ids):
            self._shift_combo.addItem(QApplication.translate("VisualizeDialog", "轮灌 {0}").format(rid), rid)
        has_rotation = len(rotation_ids) > 0
        self._shift_combo.setVisible(has_rotation)
        self._shift_label.setVisible(has_rotation)
        self._shift_combo.blockSignals(False)

        self._count_label.setText(
            QApplication.translate(
                "VisualizeDialog",
                "共 {0} 条记录（上限 {1}）").format(
                    len(self.summaries), SimHistory.MAX_RECORDS))
        self._update_list_display()

    def _on_filter_changed(self):
        self._update_list_display()

    def _update_list_display(self):
        """根据过滤器更新列表显示"""
        filter_rid = self._shift_combo.currentData() if hasattr(self, '_shift_combo') else ""
        self.list_widget.clear()
        for idx, record in enumerate(self.summaries):
            if filter_rid and record.get("rotation_id") != filter_rid:
                continue
            summary = SimHistory.summary(record)
            item = QListWidgetItem(summary)
            # 存全量索引：启用轮灌过滤后列表行号与 self.summaries
            # 索引不再一一对应，直接用行号会可视化/删除错误的记录
            item.setData(Qt.UserRole, idx)
            self.list_widget.addItem(item)

    def _on_visualize(self):
        """可视化选中的记录（此时才读取完整分片）"""
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "aQuaDrip", QApplication.translate("VisualizeDialog", "请先选择一条记录"))
            return
        record = self.history.get(item.data(Qt.UserRole)) if self.history else None
        if record is None:
            QMessageBox.warning(self, "aQuaDrip", QApplication.translate("VisualizeDialog", "记录文件缺失，无法可视化"))
            return
        mode = self.mode_combo.currentData()
        self.visualize_requested.emit(record, mode)

    def _on_export_nodes(self):
        """导出选中记录的节点矢量文件（压力 + 滴头流量）"""
        item = self.list_widget.currentItem()
        if item is None or not self.history:
            QMessageBox.information(self, "aQuaDrip", QApplication.translate("VisualizeDialog", "请先选择一条记录"))
            return
        record = self.history.get(item.data(Qt.UserRole))
        if record is None:
            QMessageBox.warning(self, "aQuaDrip", QApplication.translate("VisualizeDialog", "记录文件缺失，无法可视化"))
            return

        # 默认文件名：aquadrip_result_<时间戳>.gpkg，存到项目 GPKG 同目录
        import os
        from qgis.PyQt.QtWidgets import QFileDialog
        ts = (record.get("timestamp") or "result").replace(":", "").replace(" ", "_").replace("-", "")
        default_dir = os.path.dirname(self.history.gpkg_path) \
            if getattr(self.history, "gpkg_path", "") else ""
        path, _ = QFileDialog.getSaveFileName(
            self,
            QApplication.translate("VisualizeDialog", "导出节点矢量文件"),
            os.path.join(default_dir, f"aquadrip_result_{ts}.gpkg"),
            "GeoPackage (*.gpkg);;GeoJSON (*.geojson);;Shapefile (*.shp)")
        if not path:
            return

        try:
            from ..tools.visualize import Visualizer
            count = Visualizer(self.iface).export_nodes(record, path)
            self.iface.messageBar().pushMessage(
                "aQuaDrip",
                QApplication.translate(
                    "VisualizeDialog",
                    "已导出 {0} 个节点（压力+滴头流量）→ {1}").format(count, path),
                level=0, duration=6)
        except Exception as e:
            QMessageBox.warning(
                self, "aQuaDrip",
                QApplication.translate("VisualizeDialog", "导出失败: {0}").format(e))

    def _on_delete(self):
        """删除选中的记录"""
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "aQuaDrip", QApplication.translate("VisualizeDialog", "请先选择一条记录"))
            return

        reply = QMessageBox.question(
            self, "aQuaDrip", QApplication.translate("VisualizeDialog", "确定删除该记录？"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        if self.history.delete(item.data(Qt.UserRole)):
            self._refresh_list()
            self.iface.messageBar().pushMessage(
                "aQuaDrip", QApplication.translate("VisualizeDialog", "记录已删除"), level=0, duration=3)

    def _on_purge_all(self):
        """清空全部历史记录"""
        if not self.history or self.history.count == 0:
            QMessageBox.information(
                self, "aQuaDrip",
                QApplication.translate("VisualizeDialog", "没有可删除的记录"))
            return

        reply = QMessageBox.warning(
            self, "aQuaDrip",
            QApplication.translate(
                "VisualizeDialog",
                "确定清空全部 {0} 条历史记录？\n此操作不可撤销！").format(self.history.count),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        deleted = self.history.purge_all()
        self._refresh_list()
        self.iface.messageBar().pushMessage(
            "aQuaDrip",
            QApplication.translate("VisualizeDialog", "已清空 {0} 条记录").format(deleted),
            level=0, duration=3)
