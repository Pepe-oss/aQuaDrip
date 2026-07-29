"""aQuaDrip 主面板 — 日志 + 农田参数编辑"""

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QTextEdit, QSplitter,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont

from .field_properties import FieldPropertiesPanel


class AQuaDripDockWidget(QDockWidget):
    """aQuaDrip 主面板"""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("aQuaDrip")
        self.setObjectName("aQuaDripDockWidget")
        self.setMinimumWidth(280)
        self.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)

        # 主组件
        main = QWidget()
        self.setWidget(main)
        layout = QVBoxLayout(main)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 农艺参数面板（上半部分）
        self.field_panel = FieldPropertiesPanel(iface)
        layout.addWidget(self.field_panel, stretch=3)

        # 日志（下半部分）
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
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
