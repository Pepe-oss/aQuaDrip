"""SimulationDialog — 模拟精度选择对话框"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel, QRadioButton,
    QButtonGroup, QCheckBox, QPushButton, QHBoxLayout, QSpinBox,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication


# 精度预设（与 DripSimulation.PRESETS 一致）
# label/desc 为模块级 UI 文案,直接包裹 translate(模块在对话框触发时
# 才 import,translator 已安装;pylupdate 可提取模块级调用)
# 收敛判据统一为相对变化<0.1%,三档差异 = 迭代上限(安全预算)
PRESETS = {
    "fast":     {"max_iter": 15, "tolerance": 1e-10,
                 "label": QApplication.translate("SimulationDialog", "快速（推荐）"),
                 "desc": QApplication.translate("SimulationDialog", "最多 15 次迭代，适合日常设计")},
    "standard": {"max_iter": 20, "tolerance": 1e-10,
                 "label": QApplication.translate("SimulationDialog", "标准"),
                 "desc": QApplication.translate("SimulationDialog", "最多 20 次迭代，平衡精度与速度")},
    "high":     {"max_iter": 25, "tolerance": 1e-10,
                 "label": QApplication.translate("SimulationDialog", "高精度"),
                 "desc": QApplication.translate("SimulationDialog", "最多 25 次迭代，用于校准分析")},
}


class SimulationDialog(QDialog):
    """模拟精度选择对话框"""

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface

        self.setWindowTitle(QApplication.translate("SimulationDialog", "aQuaDrip 模拟设置"))
        self.setMinimumWidth(360)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(QApplication.translate("SimulationDialog", "选择模拟精度：")))

        self._btn_group = QButtonGroup(self)
        self._radios = {}

        for idx, (key, preset) in enumerate(PRESETS.items()):
            # 模板作为字面量交给 translate(查表按完整字面量匹配),
            # 已翻译的 label/迭代数经 format 填入
            radio = QRadioButton(
                QApplication.translate(
                    "SimulationDialog", "{0}（{1} 次迭代）").format(
                        preset['label'], preset['max_iter']))
            radio.setToolTip(preset["desc"])
            if idx == 0:
                radio.setChecked(True)
            self._btn_group.addButton(radio)
            self._radios[radio] = key
            layout.addWidget(radio)

        # ── 自定义:用户指定最多迭代次数("custom:N") ──
        row = QHBoxLayout()
        self._radio_custom = QRadioButton(
            QApplication.translate("SimulationDialog", "自定义（指定最大迭代次数）"))
        self._radio_custom.setToolTip(QApplication.translate(
            "SimulationDialog",
            "迭代求解器的最大迭代轮数；收敛（总流量缺口 < 0.5%）即提前停止，"
            "此值只是安全上限"))
        self._spin_iters = QSpinBox()
        self._spin_iters.setRange(1, 200)
        self._spin_iters.setValue(25)
        self._spin_iters.setSuffix(QApplication.translate("SimulationDialog", " 次"))
        self._radio_custom.toggled.connect(self._on_custom_toggled)
        row.addWidget(self._radio_custom)
        row.addWidget(self._spin_iters)
        row.addStretch()
        self._btn_group.addButton(self._radio_custom)
        layout.addLayout(row)
        self._on_custom_toggled(False)

        self._check_history = QCheckBox(QApplication.translate("SimulationDialog", "模拟完成后自动保存历史记录"))
        self._check_history.setChecked(True)
        layout.addWidget(self._check_history)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton(QApplication.translate("SimulationDialog", "取消"))
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_ok = QPushButton(QApplication.translate("SimulationDialog", "开始模拟"))
        btn_ok.setStyleSheet("font-weight: bold;")
        btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def _on_custom_toggled(self, checked: bool):
        """自定义模式切换:仅选中时允许编辑迭代次数"""
        self._spin_iters.setEnabled(checked)

    def precision_level(self) -> str:
        """返回 'fast' / 'standard' / 'high' / 'custom:N'(N=用户指定迭代上限)"""
        if self._radio_custom.isChecked():
            return f"custom:{self._spin_iters.value()}"
        for radio, key in self._radios.items():
            if radio.isChecked():
                return key
        return "fast"

    def save_history(self) -> bool:
        return self._check_history.isChecked()
