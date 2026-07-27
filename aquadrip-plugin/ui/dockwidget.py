"""aQuaDrip 主面板 DockWidget

项目树 + 操作面板 + 日志输出
"""

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QTextEdit,
    QPushButton, QSplitter, QLabel, QFrame,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont, QIcon


class AQuaDripDockWidget(QDockWidget):
    """aQuaDrip 主面板"""

    # 信号
    item_selected = pyqtSignal(str, str)  # (item_type, item_id)
    button_clicked = pyqtSignal(str)       # button_name

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle(self.tr("aQuaDrip 滴灌设计"))
        self.setObjectName("aQuaDripDockWidget")
        self.setMinimumWidth(300)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        """构建界面"""
        main_widget = QWidget()
        self.setWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ===== 项目树 =====
        tree_label = QLabel(self.tr("📁 项目"))
        tree_label.setStyleSheet("font-weight: bold; padding: 2px;")
        layout.addWidget(tree_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setAnimated(True)
        self.tree.setMinimumHeight(150)
        layout.addWidget(self.tree, stretch=3)

        # 初始占位
        self._build_project_tree()

        # ===== 分隔线 =====
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # ===== 操作按钮 =====
        btn_label = QLabel(self.tr("⚡ 操作"))
        btn_label.setStyleSheet("font-weight: bold; padding: 2px;")
        layout.addWidget(btn_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        self.btn_gen = QPushButton(self.tr("生成管网"))
        self.btn_config = QPushButton(self.tr("参数配置"))
        self.btn_run = QPushButton(self.tr("运行模拟"))
        self.btn_result = QPushButton(self.tr("结果分析"))

        for btn in [self.btn_gen, self.btn_config, self.btn_run, self.btn_result]:
            btn.setMinimumHeight(32)
            btn_layout.addWidget(btn)

        layout.addLayout(btn_layout)

        # ===== 日志 =====
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line2)

        log_label = QLabel(self.tr("📋 日志"))
        log_label.setStyleSheet("font-weight: bold; padding: 2px;")
        layout.addWidget(log_label)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        self.log.setPlaceholderText(self.tr("操作日志将显示在这里..."))
        font = QFont("Menlo", 9)
        self.log.setFont(font)
        layout.addWidget(self.log, stretch=1)

    def _build_project_tree(self):
        """构建初始项目树"""
        self.tree.clear()

        root = QTreeWidgetItem(self.tree, [self.tr("未命名项目")])
        root.setExpanded(True)

        # 子节点（占位）
        for text, icon in [
            (self.tr("📍 农田"), ""),
            (self.tr("🔧 设备"), ""),
            (self.tr("📊 模拟结果"), ""),
        ]:
            item = QTreeWidgetItem(root, [text])
            item.setForeground(0, Qt.gray)

    def _connect_signals(self):
        """连接信号"""
        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        self.btn_gen.clicked.connect(lambda: self.button_clicked.emit("generate_network"))
        self.btn_config.clicked.connect(lambda: self.button_clicked.emit("configure"))
        self.btn_run.clicked.connect(lambda: self.button_clicked.emit("run_simulation"))
        self.btn_result.clicked.connect(lambda: self.button_clicked.emit("show_results"))

    def _on_tree_item_clicked(self, item, column):
        """树节点点击"""
        parent_text = ""
        if item.parent():
            parent_text = item.parent().text(0)
        self.item_selected.emit(parent_text, item.text(0))

    # ---- 公开方法 ----

    def log_message(self, message: str):
        """追加日志"""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {message}")
        # 自动滚动到底部
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def update_project_tree(self, network_name: str, stats: dict = None):
        """更新项目树"""
        self.tree.clear()
        root = QTreeWidgetItem(self.tree, [network_name or self.tr("未命名项目")])
        root.setExpanded(True)

        # 农田
        field_item = QTreeWidgetItem(root, [self.tr("📍 农田")])
        if stats and stats.get("area"):
            QTreeWidgetItem(field_item, [self.tr(f"面积: {stats['area']:.0f} m²")])

        # 管网
        net_item = QTreeWidgetItem(root, [self.tr("🔗 管网")])
        if stats:
            for key, label in [("mainline", "干管"), ("submain", "支管"), ("lateral", "毛管")]:
                val = stats.get(key, 0)
                if val:
                    QTreeWidgetItem(net_item, [self.tr(f"{label}: {val:.0f} m")])

        # 设备
        eq_item = QTreeWidgetItem(root, [self.tr("🔧 设备")])
        if stats and stats.get("pumps"):
            QTreeWidgetItem(eq_item, [self.tr(f"水泵: {stats['pumps']}")])
        if stats and stats.get("valves"):
            QTreeWidgetItem(eq_item, [self.tr(f"阀门: {stats['valves']}")])

        # 结果
        res_item = QTreeWidgetItem(root, [self.tr("📊 模拟结果")])
        if stats and stats.get("cu"):
            color = "🟢" if stats["cu"] >= 85 else "🟡" if stats["cu"] >= 75 else "🔴"
            QTreeWidgetItem(res_item, [self.tr(f"{color} CU: {stats['cu']:.1f}%")])
        if stats and stats.get("flow"):
            QTreeWidgetItem(res_item, [self.tr(f"总流量: {stats['flow']:.2f} m³/h")])

        root.setExpanded(True)
        net_item.setExpanded(True)

    def set_buttons_enabled(self, gen=True, config=True, run=True, result=True):
        """设置按钮启用状态"""
        self.btn_gen.setEnabled(gen)
        self.btn_config.setEnabled(config)
        self.btn_run.setEnabled(run)
        self.btn_result.setEnabled(result)
