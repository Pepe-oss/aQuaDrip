"""FieldPropertiesPanel — 农艺参数编辑表单（新设计）

耕作模式统一为"垄模式"：
  垄间距 + 每垄滴灌带数 + 滴灌带间距
  等行距 = 垄间距0.3, 每垄1条
  宽窄行 = 垄间距0.6, 每垄3条间距0.3
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QDoubleSpinBox, QSpinBox, QPushButton, QLabel, QFrame,
    QHBoxLayout, QMessageBox,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeatureRequest, QgsGeometry,
)


CROP_TYPES = ["玉米", "小麦", "水稻", "蔬菜", "果树", "其他"]
PATTERN_TYPES = [
    ("垄模式", "ridge"),
    ("按垄数", "ridge_count"),
]
DIRECTION_TYPES = [
    ("与田块长边平行", "long_edge"),
    ("与田块短边平行", "short_edge"),
    ("自定义角度", "custom"),
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
        self.setEnabled(False)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("📋 农田参数")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        layout.addWidget(line)

        form = QFormLayout()
        form.setSpacing(6)

        self.edt_name = QLineEdit()
        self.edt_name.setPlaceholderText("可选")
        form.addRow("名称:", self.edt_name)

        self.cmb_crop = QComboBox()
        self.cmb_crop.addItems(CROP_TYPES)
        form.addRow("作物类型:", self.cmb_crop)

        # 耕作模式
        self.cmb_pattern = QComboBox()
        for label, value in PATTERN_TYPES:
            self.cmb_pattern.addItem(label, value)
        self.cmb_pattern.currentIndexChanged.connect(self._on_pattern_changed)
        form.addRow("耕作模式:", self.cmb_pattern)

        # 垄参数（所有模式共有）
        self.spin_row_spacing = QDoubleSpinBox()
        self.spin_row_spacing.setRange(0.1, 5.0)
        self.spin_row_spacing.setSingleStep(0.05)
        self.spin_row_spacing.setValue(0.6)
        self.spin_row_spacing.setDecimals(2)
        self.spin_row_spacing.setSuffix(" m")
        form.addRow("垄间距:", self.spin_row_spacing)

        self.spin_tapes = QSpinBox()
        self.spin_tapes.setRange(1, 10)
        self.spin_tapes.setValue(1)
        form.addRow("每垄滴灌带数:", self.spin_tapes)

        self.spin_tape_spacing = QDoubleSpinBox()
        self.spin_tape_spacing.setRange(0.1, 2.0)
        self.spin_tape_spacing.setSingleStep(0.05)
        self.spin_tape_spacing.setValue(0.3)
        self.spin_tape_spacing.setDecimals(2)
        self.spin_tape_spacing.setSuffix(" m")
        form.addRow("滴灌带间距:", self.spin_tape_spacing)

        # 垄数（仅按垄数模式）
        self.spin_ridge_count = QSpinBox()
        self.spin_ridge_count.setRange(1, 10000)
        self.spin_ridge_count.setValue(40)
        form.addRow("垄数:", self.spin_ridge_count)

        # 滴灌带方向
        self.cmb_direction = QComboBox()
        for label, value in DIRECTION_TYPES:
            self.cmb_direction.addItem(label, value)
        self.cmb_direction.currentIndexChanged.connect(self._on_direction_changed)
        form.addRow("滴灌带方向:", self.cmb_direction)

        self.spin_angle = QDoubleSpinBox()
        self.spin_angle.setRange(0, 360)
        self.spin_angle.setValue(0)
        self.spin_angle.setSuffix("°")
        self.spin_angle.setEnabled(False)
        form.addRow("角度:", self.spin_angle)

        self.spin_emitter = QDoubleSpinBox()
        self.spin_emitter.setRange(0.05, 2.0)
        self.spin_emitter.setSingleStep(0.05)
        self.spin_emitter.setValue(0.3)
        self.spin_emitter.setDecimals(2)
        self.spin_emitter.setSuffix(" m")
        form.addRow("滴头间距:", self.spin_emitter)

        layout.addLayout(form)

        # 保存按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_save = QPushButton("💾 保存参数")
        self.btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

        layout.addStretch()

        self.lbl_hint = QLabel("\n\n请选中一个农田地块\n然后在右侧编辑参数")
        self.lbl_hint.setAlignment(Qt.AlignCenter)
        self.lbl_hint.setStyleSheet("color: gray;")
        layout.addWidget(self.lbl_hint)

    def _connect_signals(self):
        project = QgsProject.instance()
        project.layersAdded.connect(self._on_layers_changed)
        self._on_layers_changed()

    def _on_layers_changed(self):
        layer = self._find_field_layer()
        if layer:
            try:
                layer.selectionChanged.disconnect(self._on_selection_changed)
            except TypeError:
                pass
            layer.selectionChanged.connect(self._on_selection_changed)
            if layer.selectedFeatureCount() > 0:
                self._on_selection_changed()

    def _on_selection_changed(self):
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

    def _load_feature(self, layer, feat):
        self._current_layer = layer
        self._current_feat_id = feat.id()

        self.edt_name.setText(str(feat.attribute("name") or ""))
        self._set_combo_val(self.cmb_crop, feat.attribute("crop_type"))
        self._set_combo_val(self.cmb_pattern, feat.attribute("planting_pattern"))
        self._set_combo_val(self.cmb_direction, feat.attribute("direction_type"))
        self.spin_row_spacing.setValue(float(feat.attribute("row_spacing") or 0.6))
        self.spin_tapes.setValue(int(feat.attribute("tapes_per_ridge") or 1))
        self.spin_tape_spacing.setValue(float(feat.attribute("tape_spacing") or 0.3))
        self.spin_ridge_count.setValue(int(feat.attribute("ridge_count") or 40))
        self.spin_angle.setValue(float(feat.attribute("row_direction") or 0))
        self.spin_emitter.setValue(float(feat.attribute("emitter_spacing") or 0.3))

        self._update_ui()
        self.lbl_hint.hide()
        self.setEnabled(True)

    def _on_save(self):
        if not self._current_layer or self._current_feat_id is None:
            return

        layer = self._current_layer
        request = QgsFeatureRequest().setFilterFid(self._current_feat_id)
        feat = next(layer.getFeatures(request), None)
        if not feat:
            return

        layer.startEditing()
        feat.setAttribute("name", self.edt_name.text())
        feat.setAttribute("crop_type", self.cmb_crop.currentData() or self.cmb_crop.currentText())
        feat.setAttribute("planting_pattern", self.cmb_pattern.currentData())
        feat.setAttribute("direction_type", self.cmb_direction.currentData())
        feat.setAttribute("row_spacing", self.spin_row_spacing.value())
        feat.setAttribute("tapes_per_ridge", self.spin_tapes.value())
        feat.setAttribute("tape_spacing", self.spin_tape_spacing.value())
        feat.setAttribute("ridge_count", self.spin_ridge_count.value())
        feat.setAttribute("row_direction", self.spin_angle.value())
        feat.setAttribute("emitter_spacing", self.spin_emitter.value())
        layer.updateFeature(feat)
        layer.commitChanges()

        self.iface.messageBar().pushMessage(
            "aQuaDrip", "农田参数已保存", level=0, duration=3)

    def _on_pattern_changed(self, idx):
        """耕作模式切换"""
        data = self.cmb_pattern.itemData(idx)
        is_ridge_count = (data == "ridge_count")
        self.spin_ridge_count.setVisible(is_ridge_count)
        self.findChild(QFormLayout).labelForField(self.spin_ridge_count).setVisible(is_ridge_count)  # 不太对，等下用其他方式
        self._update_ui()

    def _on_direction_changed(self, idx):
        data = self.cmb_direction.itemData(idx)
        self.spin_angle.setEnabled(data == "custom")

    def _update_ui(self):
        """更新 UI 状态"""
        pattern = self.cmb_pattern.currentData()
        self.spin_ridge_count.setEnabled(pattern == "ridge_count")

    # ── 查找 ──

    def _find_field_layer(self):
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue
            name = layer.name()
            source = layer.source()
            if name == "aqd_fields" or "aqd_fields" in source:
                return layer
        return None

    def _clear(self):
        self._current_feat_id = None
        self._current_layer = None
        self.edt_name.clear()
        self.setEnabled(False)
        self.lbl_hint.show()

    @staticmethod
    def _set_combo_val(combo, value):
        if value is None:
            combo.setCurrentIndex(0)
            return
        for i in range(combo.count()):
            if str(combo.itemData(i) or "") == str(value):
                combo.setCurrentIndex(i)
                return
        combo.setCurrentIndex(0)
