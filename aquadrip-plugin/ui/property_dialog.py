"""PropertyDialog — 统一属性编辑浮动窗

按选中要素所在图层（aqd_fields / aqd_pipes / aqd_nodes）动态生成表单，
用于"创建后修改内部参数"。字段定义与下拉选项复用 layer_setup.FIELD_DEFS。

农田模式（aqd_fields）下附带"保存并生成毛管"按钮（迁移自原 FieldPropertiesPanel）。
"""

from typing import Optional

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QDoubleSpinBox, QSpinBox, QPushButton, QDialogButtonBox,
    QMessageBox, QLabel,
)
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.core import QgsVectorLayer, QgsFeature

from ..tools.layer_setup import FIELD_DEFS


# 字段中文名
FIELD_LABELS = {
    # aqd_fields
    "name": "名称", "crop_type": "作物类型", "planting_pattern": "耕作模式",
    "direction_type": "滴灌带方向", "row_spacing": "垄间距 (m)",
    "tapes_per_ridge": "每垄滴灌带数", "tape_spacing": "滴灌带间距 (m)",
    "ridge_count": "垄数", "row_direction": "自定义角度 (°)",
    "emitter_spacing": "滴头间距 (m)",
    # aqd_pipes
    "pipe_type": "管道类型", "device": "设备", "valve_type": "阀门类型",
    "status": "状态", "diameter": "管径 (mm)", "material": "材质",
    "roughness": "糙率 C", "pump_head": "泵扬程 (m)", "pump_flow": "泵流量 (m³/h)",
    "pump_power": "泵功率 (kW)", "minor_loss": "局部损失系数",
    "lateral_spacing": "毛管间距 (m)", "zone_id": "分区号",
    "from_node": "起点节点", "to_node": "终点节点",
    "flow": "流量 (模拟)", "velocity": "流速 (模拟)",
    # aqd_nodes
    "node_type": "节点类型", "source_type": "水源类型", "head": "水头 (m)",
    "available_flow": "可用流量 (m³/s)", "fertilizer_volume": "施肥罐容积 (L)",
    "fertilizer_concentration": "肥液浓度 (%)", "elevation": "高程 (m)",
    "pressure": "压力 (模拟)",
}

# 各图层模式下可编辑字段（有序）
MODE_FIELDS = {
    "aqd_fields": ["name", "crop_type", "planting_pattern", "direction_type",
                   "row_spacing", "tapes_per_ridge", "tape_spacing",
                   "ridge_count", "row_direction", "emitter_spacing"],
    "aqd_pipes": ["pipe_type", "device", "valve_type", "status", "diameter",
                  "material", "roughness", "pump_head", "pump_flow",
                  "pump_power", "minor_loss", "emitter_spacing", "zone_id"],
    "aqd_nodes": ["node_type", "source_type", "head", "available_flow",
                  "fertilizer_volume", "fertilizer_concentration", "elevation"],
}

MODE_TITLES = {
    "aqd_fields": "农田参数",
    "aqd_pipes": "管道/设备属性",
    "aqd_nodes": "节点属性",
}

# 数值字段的合法范围（防止间距等被设为 0/负值导致布局死循环）
POSITIVE_FIELDS = {"row_spacing", "tape_spacing", "emitter_spacing",
                   "lateral_spacing"}  # 必须 > 0
NONNEG_FIELDS = {"diameter", "roughness", "head", "available_flow",
                 "pump_head", "pump_flow", "pump_power", "minor_loss",
                 "elevation", "fertilizer_volume",
                 "fertilizer_concentration"}  # >= 0
ANGLE_FIELDS = {"row_direction"}  # 0~360
INT_RANGES = {  # int 字段范围
    "tapes_per_ridge": (1, 100), "ridge_count": (1, 10000), "zone_id": (0, 9999),
}


class PropertyDialog(QDialog):
    """统一属性编辑浮动窗

    Args:
        iface: QgisInterface
        layer: 要素所在图层（aqd_fields / aqd_pipes / aqd_nodes）
        feat: 待编辑的要素
        show_generate: 农田模式下是否显示"保存并生成毛管"按钮
    """

    def __init__(self, iface, layer: QgsVectorLayer, feat: QgsFeature,
                 show_generate: bool = False, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.layer = layer
        self.feat = feat
        self.mode = self._mode_of_layer(layer)
        if self.mode is None:
            raise ValueError(f"不支持的图层: {layer.name()}")

        self._widgets = {}   # {field_name: widget}
        self._rows = {}      # {field_name: (label_widget, field_widget)}
        self._edge_tool = None

        self.setWindowTitle(MODE_TITLES[self.mode])
        self.setMinimumWidth(340)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._build_ui(show_generate)
        self._load_values()
        self._apply_linkages()

    # ── UI 构建 ──

    def _build_ui(self, show_generate: bool):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(6)

        value_maps = FIELD_DEFS[self.mode].get("value_maps", {})
        for fname in MODE_FIELDS[self.mode]:
            widget = self._make_widget(fname, value_maps.get(fname))
            label = QLabel(FIELD_LABELS.get(fname, fname))
            form.addRow(label, widget)
            self._widgets[fname] = widget
            self._rows[fname] = (label, widget)

        layout.addLayout(form)

        # 方向"选择边"按钮（农田模式 pick_edge）
        if self.mode == "aqd_fields":
            self.btn_pick_edge = QPushButton("在地图上选择边…")
            self.btn_pick_edge.clicked.connect(self._on_pick_edge)
            layout.addWidget(self.btn_pick_edge)

        # 生成毛管按钮
        if show_generate and self.mode == "aqd_fields":
            self.btn_gen = QPushButton("🌱 保存并生成毛管")
            self.btn_gen.setStyleSheet("font-weight: bold;")
            self.btn_gen.clicked.connect(self._on_generate)
            layout.addWidget(self.btn_gen)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _make_widget(self, fname: str, vmap: Optional[dict]):
        """按字段类型/下拉选项创建控件"""
        if vmap:
            w = QComboBox()
            for label, val in vmap.items():
                w.addItem(label, val)
            # "选择边"是 UI 临时态（非存储值），value_map 里没有，需手动补
            if fname == "direction_type":
                w.addItem("选择边…", "pick_edge")
            return w

        qfield = self.layer.fields().field(fname)
        if qfield.type() == QVariant.Double:
            w = QDoubleSpinBox()
            if fname in POSITIVE_FIELDS:
                w.setRange(0.01, 999999)
            elif fname in NONNEG_FIELDS:
                w.setRange(0, 999999)
            elif fname in ANGLE_FIELDS:
                w.setRange(0, 360)
            else:
                w.setRange(-999999, 999999)
            w.setDecimals(3)
            return w
        if qfield.type() in (QVariant.Int, QVariant.LongLong):
            w = QSpinBox()
            lo, hi = INT_RANGES.get(fname, (-999999, 999999))
            w.setRange(lo, hi)
            return w
        return QLineEdit()

    # ── 值加载 / 保存 ──

    def _load_values(self):
        for fname, w in self._widgets.items():
            val = self._safe_attr(fname)
            if isinstance(w, QComboBox):
                idx = w.findData(str(val) if val is not None else "")
                w.setCurrentIndex(idx if idx >= 0 else 0)
            elif isinstance(w, (QDoubleSpinBox, QSpinBox)):
                try:
                    w.setValue(float(val) if val is not None else 0)
                except (TypeError, ValueError):
                    w.setValue(0)
            else:
                w.setText("" if val is None else str(val))

    def _save(self):
        need_edit = not self.layer.isEditable()
        if need_edit:
            self.layer.startEditing()
        try:
            for fname, w in self._widgets.items():
                if isinstance(w, QComboBox):
                    self.feat.setAttribute(fname, w.currentData())
                elif isinstance(w, QDoubleSpinBox):
                    self.feat.setAttribute(fname, float(w.value()))
                elif isinstance(w, QSpinBox):
                    self.feat.setAttribute(fname, int(w.value()))
                else:
                    self.feat.setAttribute(fname, w.text())
            self.layer.updateFeature(self.feat)
            if need_edit:
                self.layer.commitChanges()
        except Exception:
            if need_edit:
                self.layer.rollBack()
            raise

    def _on_save(self):
        try:
            self._save()
            self.iface.messageBar().pushMessage(
                "aQuaDrip", "属性已保存", level=0, duration=3)
        except Exception as e:
            QMessageBox.critical(self, "aQuaDrip", f"保存失败: {e}")

    def _safe_attr(self, fname):
        idx = self.feat.fields().lookupField(fname)
        if idx < 0:
            return None
        return self.feat.attribute(idx)

    # ── 联动规则 ──

    def _apply_linkages(self):
        if self.mode == "aqd_fields":
            tapes = self._widgets.get("tapes_per_ridge")
            if tapes:
                tapes.valueChanged.connect(self._on_tapes_changed)
                self._on_tapes_changed(tapes.value())
            direction = self._widgets.get("direction_type")
            if direction:
                direction.currentIndexChanged.connect(self._on_dir_changed)
                self._on_dir_changed(direction.currentIndex())
            pattern = self._widgets.get("planting_pattern")
            if pattern:
                pattern.currentIndexChanged.connect(self._on_pattern_changed)
                self._on_pattern_changed(pattern.currentIndex())
        elif self.mode == "aqd_pipes":
            device = self._widgets.get("device")
            if device:
                device.currentIndexChanged.connect(self._on_device_changed)
                self._on_device_changed(device.currentIndex())
        elif self.mode == "aqd_nodes":
            ntype = self._widgets.get("node_type")
            if ntype:
                ntype.currentIndexChanged.connect(self._on_ntype_changed)
                self._on_ntype_changed(ntype.currentIndex())

    def _set_row_visible(self, fname, visible):
        row = self._rows.get(fname)
        if row:
            row[0].setVisible(visible)
            row[1].setVisible(visible)

    # aqd_fields 联动
    def _on_tapes_changed(self, value):
        w = self._widgets.get("row_spacing")
        if w:
            w.setEnabled(int(value) > 1)

    def _on_dir_changed(self, idx):
        w = self._widgets.get("direction_type")
        if not w:
            return
        data = w.itemData(idx)
        angle = self._widgets.get("row_direction")
        if angle:
            angle.setEnabled(data == "custom")
        if hasattr(self, "btn_pick_edge"):
            self.btn_pick_edge.setVisible(data == "pick_edge")

    def _on_pattern_changed(self, idx):
        w = self._widgets.get("planting_pattern")
        if not w:
            return
        is_rc = (w.itemData(idx) == "ridge_count")
        self._set_row_visible("ridge_count", is_rc)

    # aqd_pipes 联动
    def _on_device_changed(self, idx):
        w = self._widgets.get("device")
        if not w:
            return
        data = w.itemData(idx)
        for f in ("pump_head", "pump_flow", "pump_power"):
            self._set_row_visible(f, data == "pump")
        self._set_row_visible("valve_type", data == "valve")

    # aqd_nodes 联动
    def _on_ntype_changed(self, idx):
        w = self._widgets.get("node_type")
        if not w:
            return
        data = w.itemData(idx)
        for f in ("source_type", "head", "available_flow"):
            self._set_row_visible(f, data == "source")
        for f in ("fertilizer_volume", "fertilizer_concentration"):
            self._set_row_visible(f, data == "fertilizer")

    # ── 边选择（农田方向）──

    def _on_pick_edge(self):
        from ..tools.edge_select_tool import EdgeSelectTool
        self._edge_tool = EdgeSelectTool(self.iface)
        self._edge_tool.angle_selected.connect(self._on_edge_selected)
        self.iface.mapCanvas().setMapTool(self._edge_tool)

    def _on_edge_selected(self, angle: float):
        dir_w = self._widgets.get("direction_type")
        angle_w = self._widgets.get("row_direction")
        if dir_w:
            idx = dir_w.findData("custom")
            if idx >= 0:
                dir_w.setCurrentIndex(idx)
        if angle_w:
            angle_w.setValue(round(angle, 1))
        if self._edge_tool:
            self.iface.mapCanvas().unsetMapTool(self._edge_tool)
            self._edge_tool = None

    # ── 生成毛管 ──

    def _on_generate(self):
        try:
            self._save()  # 先保存参数
            from ..tools.lateral_generator import LateralGenerator
            n = LateralGenerator(self.iface).generate(self.feat)
            QMessageBox.information(self, "aQuaDrip", f"已生成 {n} 条毛管")
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "aQuaDrip", f"生成失败:\n{e}")

    # ── 工具 ──

    @staticmethod
    def _mode_of_layer(layer: QgsVectorLayer) -> Optional[str]:
        name = layer.name() or ""
        src = layer.source() or ""
        for key in ("aqd_fields", "aqd_pipes", "aqd_nodes"):
            if name == key or key in src:
                return key
        return None
