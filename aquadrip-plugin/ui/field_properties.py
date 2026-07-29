"""FieldPropertiesPanel — 农艺参数编辑表单

当用户在 aqd_fields 图层选中要素时，在此面板中显示和编辑农艺参数。
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QDoubleSpinBox, QSpinBox, QPushButton, QLabel, QFrame,
    QHBoxLayout, QMessageBox,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.core import QgsProject, QgsVectorLayer


# 耕作模式的选项列表
CROP_TYPES = ["玉米", "小麦", "水稻", "蔬菜", "果树", "其他"]
PATTERNS = [
    ("等行距", "uniform"),
    ("宽窄行", "wide_narrow"),
    ("按垄数", "ridge_count"),
    ("自定义", "custom"),
]


class FieldPropertiesPanel(QFrame):
    """农田属性编辑面板"""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setFrameShape(QFrame.StyledPanel)
        self._current_feat_id = None
        self._current_layer = None
        self._build_ui()
        self._connect_signals()
        self.setEnabled(False)  # 初始禁用

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 标题
        title = QLabel("📋 农田参数")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        layout.addWidget(line)

        # 表单
        form = QFormLayout()
        form.setSpacing(6)

        self.edt_name = QLineEdit()
        self.edt_name.setPlaceholderText("可选")
        form.addRow("名称:", self.edt_name)

        self.cmb_crop = QComboBox()
        self.cmb_crop.addItems(CROP_TYPES)
        form.addRow("作物类型:", self.cmb_crop)

        self.cmb_pattern = QComboBox()
        for label, value in PATTERNS:
            self.cmb_pattern.addItem(label, value)
        self.cmb_pattern.currentIndexChanged.connect(self._on_pattern_changed)
        form.addRow("耕作模式:", self.cmb_pattern)

        self.spin_spacing = QDoubleSpinBox()
        self.spin_spacing.setRange(0.1, 5.0)
        self.spin_spacing.setSingleStep(0.1)
        self.spin_spacing.setValue(0.5)
        self.spin_spacing.setDecimals(2)
        form.addRow("行距 (m):", self.spin_spacing)

        self.spin_ridge = QSpinBox()
        self.spin_ridge.setRange(1, 1000)
        self.spin_ridge.setValue(40)
        form.addRow("垄数:", self.spin_ridge)

        self.spin_direction = QDoubleSpinBox()
        self.spin_direction.setRange(0, 360)
        self.spin_direction.setSuffix("°")
        form.addRow("种植方向:", self.spin_direction)

        self.spin_emitter = QDoubleSpinBox()
        self.spin_emitter.setRange(0.1, 5.0)
        self.spin_emitter.setSingleStep(0.05)
        self.spin_emitter.setValue(0.3)
        self.spin_emitter.setDecimals(2)
        form.addRow("滴头间距 (m):", self.spin_emitter)

        layout.addLayout(form)

        # 保存按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_save = QPushButton("💾 保存参数")
        self.btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

        layout.addStretch()

        # 空状态提示
        self.lbl_hint = QLabel("\n\n请选中一个农田地块\n然后在右侧编辑参数")
        self.lbl_hint.setAlignment(Qt.AlignCenter)
        self.lbl_hint.setStyleSheet("color: gray;")

    def _connect_signals(self):
        """连接 QGIS 选择变化信号"""
        project = QgsProject.instance()
        project.layersAdded.connect(self._on_layers_changed)

    def _on_layers_changed(self):
        """图层结构变化时重新连接信号"""
        # 连接当前 aqd_fields 图层的选中变化信号
        layer = self._find_field_layer()
        if layer:
            try:
                layer.selectionChanged.disconnect()
            except TypeError:
                pass
            layer.selectionChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self):
        """选中要素变化时加载属性"""
        if not self.isVisible():
            return
        layer = self._find_field_layer()
        if not layer:
            self._clear()
            return

        selected = layer.selectedFeatures()
        if len(selected) != 1:
            self._clear()
            if len(selected) > 1:
                self.lbl_hint.setText("请只选中一个地块")
            return

        self._load_feature(layer, selected[0])

    def _load_feature(self, layer: QgsVectorLayer, feat):
        """加载要素属性到表单"""
        self._current_layer = layer
        self._current_feat_id = feat.id()

        self.edt_name.setText(str(feat.attribute("name") or ""))
        self._set_combo_by_data(self.cmb_crop, feat.attribute("crop_type"))
        self._set_combo_by_data(self.cmb_pattern, feat.attribute("planting_pattern"))
        self.spin_spacing.setValue(float(feat.attribute("row_spacing") or 0.5))
        self.spin_ridge.setValue(int(feat.attribute("ridge_count") or 40))
        self.spin_direction.setValue(float(feat.attribute("row_direction") or 0))
        self.spin_emitter.setValue(float(feat.attribute("emitter_spacing") or 0.3))

        self.lbl_hint.hide()
        self.setEnabled(True)

    def _on_save(self):
        """保存属性到图层"""
        if not self._current_layer or self._current_feat_id is None:
            return

        layer = self._current_layer
        feat = next(layer.getFeatures(self._current_feat_id), None)
        if not feat:
            return

        layer.startEditing()
        feat.setAttribute("name", self.edt_name.text())
        feat.setAttribute("crop_type", self.cmb_crop.currentData() or self.cmb_crop.currentText())
        feat.setAttribute("planting_pattern", self.cmb_pattern.currentData())
        feat.setAttribute("row_spacing", self.spin_spacing.value())
        feat.setAttribute("ridge_count", self.spin_ridge.value())
        feat.setAttribute("row_direction", self.spin_direction.value())
        feat.setAttribute("emitter_spacing", self.spin_emitter.value())
        layer.updateFeature(feat)
        layer.commitChanges()

        self.iface.messageBar().pushMessage(
            "aQuaDrip", "农田参数已保存", level=0, duration=3)

    def _clear(self):
        """清空表单"""
        self._current_feat_id = None
        self._current_layer = None
        self.edt_name.clear()
        self.cmb_crop.setCurrentIndex(0)
        self.cmb_pattern.setCurrentIndex(0)
        self.spin_spacing.setValue(0.5)
        self.spin_ridge.setValue(40)
        self.spin_direction.setValue(0)
        self.spin_emitter.setValue(0.3)
        self.setEnabled(False)
        self.lbl_hint.show()

    # ── 辅助 ──

    def _find_field_layer(self) -> QgsVectorLayer:
        """查找 aqd_fields 图层"""
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.name() == "aqd_fields":
                if layer.isValid():
                    return layer
        return None

    def _on_pattern_changed(self, idx: int):
        """耕作模式切换时调整可用字段"""
        data = self.cmb_pattern.itemData(idx)
        self.spin_ridge.setEnabled(data == "ridge_count")
        self.spin_spacing.setEnabled(data == "uniform")

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, value):
        """按 data 值设置下拉框选中项"""
        if value is None:
            combo.setCurrentIndex(0)
            return
        for i in range(combo.count()):
            if str(combo.itemData(i) or "") == str(value):
                combo.setCurrentIndex(i)
                return
        combo.setCurrentIndex(0)
