# -*- coding: utf-8 -*-
"""ZoneGroupDialog — 分区划分模式选择对话框

三种分区模式（现实中一个管理分区常由多个阀门同时控制）:
  1. 单阀细分  每个阀门一个分区（粒度最细的底图，可反复重跑重置）
  2. 按流量自动编组  沿干管顺序贪心装箱，每组阀门需求流量之和
     ≤ 目标组流量（水源流量大于单阀区需求时多阀同开凑满）
  3. 合并选中的阀门  地图上选中 ≥2 个阀门后统一为同一分区

同标签的多阀在轮灌调度中即为一个轮灌组（同开同关）。
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QDoubleSpinBox,
    QPushButton, QLabel, QHBoxLayout,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication


class ZoneGroupDialog(QDialog):
    """分区划分模式对话框"""

    apply_requested = pyqtSignal(str, dict)  # (mode, params)

    MODE_SINGLE = "single"
    MODE_FLOW = "flow"
    MODE_MERGE = "merge"

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.setWindowTitle(QApplication.translate("ZoneGroupDialog", "aQuaDrip 分区划分"))
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)

        # 模式选择
        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(
            QApplication.translate("ZoneGroupDialog", "单阀细分（每阀一个分区）"),
            self.MODE_SINGLE)
        self.mode_combo.addItem(
            QApplication.translate("ZoneGroupDialog", "按流量自动编组（多阀一区）"),
            self.MODE_FLOW)
        self.mode_combo.addItem(
            QApplication.translate("ZoneGroupDialog", "合并选中的阀门为同一分区"),
            self.MODE_MERGE)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        form.addRow(QApplication.translate("ZoneGroupDialog", "分区模式:"), self.mode_combo)

        # 目标组流量（仅编组模式）
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(1.0, 1e8)
        self.target_spin.setDecimals(0)
        self.target_spin.setSuffix(" L/h")
        self._default_target_from_source()
        form.addRow(QApplication.translate("ZoneGroupDialog", "目标组流量:"), self.target_spin)
        layout.addLayout(form)

        # 模式说明（随模式切换）
        self.hint = QLabel("")
        self.hint.setStyleSheet("color: gray; font-size: 11px;")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        # 按钮
        btn_layout = QHBoxLayout()
        self.btn_apply = QPushButton(QApplication.translate("ZoneGroupDialog", "▶ 应用"))
        self.btn_apply.setStyleSheet("font-weight: bold;")
        self.btn_apply.clicked.connect(self._on_apply)
        btn_layout.addWidget(self.btn_apply)
        self.btn_close = QPushButton(QApplication.translate("ZoneGroupDialog", "关闭"))
        self.btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        self._on_mode_changed()

    def _default_target_from_source(self):
        """目标组流量默认取水源可供流量（m³/s → L/h），无则保持 0 提示输入"""
        try:
            from ..tools.layer_utils import find_layer
            from qgis.core import QgsProject
            layer = find_layer(QgsProject.instance(), "aqd_nodes")
            if layer is None:
                return
            for feat in layer.getFeatures():
                if str(feat.attribute("node_type") or "") == "source":
                    q = float(feat.attribute("available_flow") or 0)
                    if q > 0:
                        self.target_spin.setValue(round(q * 3_600_000, 0))
                    return
        except Exception:
            pass

    def _on_mode_changed(self):
        mode = self.mode_combo.currentData()
        self.target_spin.setEnabled(mode == self.MODE_FLOW)
        hints = {
            self.MODE_SINGLE: QApplication.translate(
                "ZoneGroupDialog",
                "每个阀门独立成一个分区（层级编号）。可反复重跑重置手动合并/编组结果。"),
            self.MODE_FLOW: QApplication.translate(
                "ZoneGroupDialog",
                "按阀门需求流量（最新模拟优先，否则按毛管几何估算）沿干管顺序装箱，"
                "每组流量之和不超过目标值；同组阀门轮灌时同开。"),
            self.MODE_MERGE: QApplication.translate(
                "ZoneGroupDialog",
                "先在地图上选中 ≥2 个阀门（按住 Shift 多选），再点应用——"
                "它们及其下游管道统一为同一分区，轮灌时同开。"),
        }
        self.hint.setText(hints.get(mode, ""))

    def _on_apply(self):
        mode = self.mode_combo.currentData()
        params = {}
        if mode == self.MODE_FLOW:
            params["target_flow_lph"] = self.target_spin.value()
        self.apply_requested.emit(mode, params)
