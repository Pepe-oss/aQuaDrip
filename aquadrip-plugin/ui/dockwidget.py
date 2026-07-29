"""aQuaDrip 主面板 — 操作日志区

功能入口已全部移至工具栏（生成图层/毛管生成/切割管道/生成交叉节点/
编辑属性/运行模拟）。本面板当前只保留日志显示，后期将用于展示和
修改选中设备的参数。
"""

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QTextEdit, QLabel,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont


class AQuaDripDockWidget(QDockWidget):
    """aQuaDrip 主面板（日志区）"""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("aQuaDrip")
        self.setObjectName("aQuaDripDockWidget")
        self.setMinimumWidth(280)
        self.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)

        main = QWidget()
        self.setWidget(main)
        layout = QVBoxLayout(main)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        hint = QLabel("功能入口在顶部 aQuaDrip 工具栏")
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        # 日志区
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("操作日志...")
        font = QFont("Menlo", 9)
        self.log.setFont(font)
        layout.addWidget(self.log, stretch=1)

    def log_message(self, msg: str):
        """追加日志"""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {msg}")
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
