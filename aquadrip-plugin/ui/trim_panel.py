"""TrimPanel — 管道切割参数面板"""

from qgis.PyQt.QtWidgets import (
    QFrame, QVBoxLayout, QLabel, QCheckBox,
    QDoubleSpinBox, QPushButton, QHBoxLayout, QSizePolicy,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal


class TrimPanel(QFrame):
    """管道切割参数面板"""

    apply_clicked = pyqtSignal(dict)  # {pipe_types: [str], cut_length: float}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._build_ui()

    def setVisible(self, visible: bool):
        """显示/隐藏时调整尺寸策略，防止空白占位"""
        super().setVisible(visible)
        if visible:
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        else:
            self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.updateGeometry()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("📐 管道切割")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        # 管道类型选择
        layout.addWidget(QLabel("管道类型:"))
        self.chk_lateral = QCheckBox("毛管 (lateral)")
        self.chk_lateral.setChecked(True)
        self.chk_submain = QCheckBox("支管 (submain)")
        self.chk_mainline = QCheckBox("干管 (mainline)")
        layout.addWidget(self.chk_lateral)
        layout.addWidget(self.chk_submain)
        layout.addWidget(self.chk_mainline)

        # 切割长度
        layout.addWidget(QLabel("\n切割长度 (m):"))
        self.spin_length = QDoubleSpinBox()
        self.spin_length.setRange(0, 100)
        self.spin_length.setSingleStep(0.1)
        self.spin_length.setValue(0)
        self.spin_length.setDecimals(2)
        self.spin_length.setSuffix(" m")
        layout.addWidget(self.spin_length)

        hint = QLabel("0 = 仅分割为两段\n>0 = 以点击点为中心切除指定长度")
        hint.setStyleSheet("color: gray; font-size: 10px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 应用按钮
        self.btn_apply = QPushButton("✂️ 切割")
        self.btn_apply.clicked.connect(self._on_apply)
        layout.addWidget(self.btn_apply)

        layout.addStretch()

        # 初始隐藏
        self.setVisible(False)

    def _on_apply(self):
        """发射切割参数"""
        types = []
        if self.chk_lateral.isChecked():
            types.append("lateral")
        if self.chk_submain.isChecked():
            types.append("submain")
        if self.chk_mainline.isChecked():
            types.append("mainline")
        params = {
            "pipe_types": types,
            "cut_length": self.spin_length.value(),
        }
        self.apply_clicked.emit(params)

    def reset(self):
        self.chk_lateral.setChecked(True)
        self.chk_submain.setChecked(False)
        self.chk_mainline.setChecked(False)
        self.spin_length.setValue(0)
