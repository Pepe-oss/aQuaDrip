"""SimulationDialog — 模拟精度选择对话框"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel, QRadioButton,
    QButtonGroup, QCheckBox, QPushButton, QHBoxLayout,
)
from qgis.PyQt.QtCore import Qt


# 精度预设（与 DripSimulation.presets 一致）
PRESETS = {
    "fast":     {"max_iter": 5,  "tolerance": 1e-6, "label": "快速（推荐）",  "desc": "5 次迭代，适合日常设计"},
    "standard": {"max_iter": 8,  "tolerance": 1e-7, "label": "标准",         "desc": "8 次迭代，平衡精度与速度"},
    "high":     {"max_iter": 15, "tolerance": 1e-8, "label": "高精度",       "desc": "15 次迭代，用于校准分析"},
}


class SimulationDialog(QDialog):
    """模拟精度选择对话框"""

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface

        self.setWindowTitle("aQuaDrip 模拟设置")
        self.setMinimumWidth(360)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("选择模拟精度："))

        self._btn_group = QButtonGroup(self)
        self._radios = {}

        for idx, (key, preset) in enumerate(PRESETS.items()):
            radio = QRadioButton(
                f"{preset['label']}  "
                f"({preset['max_iter']} 次迭代)")
            radio.setToolTip(preset["desc"])
            if idx == 0:
                radio.setChecked(True)
            self._btn_group.addButton(radio)
            self._radios[radio] = key
            layout.addWidget(radio)

        self._check_history = QCheckBox("模拟完成后自动保存历史记录")
        self._check_history.setChecked(True)
        layout.addWidget(self._check_history)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_ok = QPushButton("开始模拟")
        btn_ok.setStyleSheet("font-weight: bold;")
        btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def precision_level(self) -> str:
        """返回 'fast' / 'standard' / 'high'"""
        for radio, key in self._radios.items():
            if radio.isChecked():
                return key
        return "fast"

    def save_history(self) -> bool:
        return self._check_history.isChecked()
