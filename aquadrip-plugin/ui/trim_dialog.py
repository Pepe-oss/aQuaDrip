"""TrimDialog — 管道切割参数浮动对话框"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QCheckBox,
    QDoubleSpinBox, QPushButton, QHBoxLayout,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal


class TrimDialog(QDialog):
    """浮动切割参数对话框"""

    apply_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管道切割")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setFixedWidth(240)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("📐 管道切割参数")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        layout.addWidget(QLabel("管道类型:"))
        self.chk_lateral = QCheckBox("毛管 (lateral)")
        self.chk_lateral.setChecked(True)
        self.chk_submain = QCheckBox("支管 (submain)")
        self.chk_mainline = QCheckBox("干管 (mainline)")
        layout.addWidget(self.chk_lateral)
        layout.addWidget(self.chk_submain)
        layout.addWidget(self.chk_mainline)

        layout.addWidget(QLabel("切割长度 (m):"))
        self.spin_length = QDoubleSpinBox()
        self.spin_length.setRange(0, 100)
        self.spin_length.setSingleStep(0.1)
        self.spin_length.setValue(0)
        self.spin_length.setSuffix(" m")
        layout.addWidget(self.spin_length)

        hint = QLabel("0 = 仅分割\n>0 = 切除指定长度")
        hint.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(hint)

        btn = QPushButton("✂️ 开始切割")
        btn.setStyleSheet("padding: 6px;")
        btn.clicked.connect(self._on_apply)
        layout.addWidget(btn)

        layout.addStretch()

    def _on_apply(self):
        types = []
        if self.chk_lateral.isChecked():
            types.append("lateral")
        if self.chk_submain.isChecked():
            types.append("submain")
        if self.chk_mainline.isChecked():
            types.append("mainline")
        self.apply_clicked.emit({
            "pipe_types": types,
            "cut_length": self.spin_length.value(),
        })
