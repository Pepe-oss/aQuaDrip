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
    "direction_type": "滴灌带方向", "row_spacing": "垄中心距 (m)",
    "tapes_per_ridge": "每垄滴灌带数", "tape_spacing": "滴灌带间距 (m)",
    "ridge_count": "垄数", "row_direction": "自定义角度 (°)",
    "emitter_spacing": "滴头间距 (m)",
    # aqd_pipes
    "pipe_type": "管道类型", "status": "状态", "diameter": "管径 (mm)",
    "material": "材质", "roughness": "糙率 C", "minor_loss": "局部损失系数",
    "zone_id": "分区号",
    # aqd_pumps
    "pump_type": "水泵类型", "pump_head": "额定扬程 (m)",
    "pump_flow": "额定流量 (m³/h)", "pump_power": "额定功率 (kW)",
    # aqd_valves
    "valve_type": "阀门类型", "setting": "设定值",
    "zone": "分区",
    # 所有层共用字段
    "from_node": "起点节点", "to_node": "终点节点",
    "flow": "流量 (模拟)", "velocity": "流速 (模拟)",
    "lateral_spacing": "毛管间距 (m)", "zone_id": "分区号",
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
                   "ridge_count", "row_direction", "emitter_spacing",
                   "emitter_model", "emitter_k", "emitter_x"],
    "aqd_pipes": ["pipe_type", "status", "diameter", "material",
                  "roughness", "minor_loss", "emitter_spacing",
                  "emitter_k", "emitter_x", "zone_id", "zone"],
    "aqd_pumps": ["pump_type", "status", "diameter", "pump_head",
                  "pump_flow", "pump_power", "minor_loss", "zone"],
    "aqd_valves": ["valve_type", "status", "diameter", "setting",
                   "minor_loss", "zone"],
    "aqd_nodes": ["node_type", "source_type", "head", "available_flow",
                  "fertilizer_volume", "fertilizer_concentration", "elevation"],
}

MODE_TITLES = {
    "aqd_fields": "农田参数",
    "aqd_pipes": "管道属性",
    "aqd_pumps": "水泵属性",
    "aqd_valves": "阀门属性",
    "aqd_nodes": "节点属性",
}

# 数值字段的合法范围（防止间距等被设为 0/负值导致布局死循环）
# row_spacing 垄间距最小 0.1m（农业实际下限，防止误设 0.01）
POSITIVE_FIELDS = {"tape_spacing", "emitter_spacing",
                   "lateral_spacing"}  # 必须 > 0（范围 0.01~999999）
SPACING_FIELDS = {"row_spacing"}  # 垄间距范围 0.1~100 m
NONNEG_FIELDS = {"diameter", "roughness", "head", "available_flow",
                 "pump_head", "pump_flow", "pump_power", "minor_loss",
                 "elevation", "fertilizer_volume",
                 "fertilizer_concentration"}  # >= 0
ANGLE_FIELDS = {"row_direction"}  # 0~360
RANGE_0_1 = {"emitter_x"}  # 流态指数 0~1
INT_RANGES = {  # int 字段范围
    "tapes_per_ridge": (1, 100), "ridge_count": (1, 10000), "zone_id": (0, 9999),
}


class PropertyDialog(QDialog):
    """统一属性编辑浮动窗

    Args:
        iface: QgisInterface
        layer: 要素所在图层（aqd_fields / aqd_pipes / aqd_nodes）
        feats: 待编辑的要素列表（单选时长度为 1，多选时批量应用）
        show_generate: 农田模式下是否显示"保存并生成毛管"按钮
    """

    def __init__(self, iface, layer: QgsVectorLayer,
                 feats,  # List[QgsFeature] — 单选或多选
                 show_generate: bool = False, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.layer = layer

        # 统一处理：确保是列表
        if not isinstance(feats, list):
            feats = [feats]
        self._feats = feats
        self.feat = feats[0]  # 表单填充第一要素的值

        self.mode = self._mode_of_layer(layer)
        if self.mode is None:
            raise ValueError(f"不支持的图层: {layer.name()}")

        self._widgets = {}   # {field_name: widget}
        self._rows = {}      # {field_name: (label_widget, field_widget)}
        self._edge_tool = None

        title = MODE_TITLES[self.mode]
        if len(self._feats) > 1:
            title += f"（{len(self._feats)} 个要素）"
        self.setWindowTitle(title)
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
            # 滴头型号下拉：从内置滴头库动态构建
            if fname == "emitter_model":
                widget = self._make_emitter_model_combo()
            else:
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

    def _make_emitter_model_combo(self) -> QComboBox:
        """从内置滴头库构建型号下拉（含"自定义"选项）"""
        from wdrip.network.emitter import BUILTIN_EMITTERS
        w = QComboBox()
        w.addItem("自定义", "")
        for key, spec in BUILTIN_EMITTERS.items():
            label = f"{spec.manufacturer} {spec.name}"
            w.addItem(label, key)
        return w

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
            if fname in SPACING_FIELDS:
                w.setRange(0.1, 100)
            elif fname in POSITIVE_FIELDS:
                w.setRange(0.01, 999999)
            elif fname in NONNEG_FIELDS:
                w.setRange(0, 999999)
            elif fname in ANGLE_FIELDS:
                w.setRange(0, 360)
            elif fname in RANGE_0_1:
                w.setRange(0, 1)
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
            for feat in self._feats:
                for fname, w in self._widgets.items():
                    if isinstance(w, QComboBox):
                        feat.setAttribute(fname, w.currentData())
                    elif isinstance(w, QDoubleSpinBox):
                        feat.setAttribute(fname, float(w.value()))
                    elif isinstance(w, QSpinBox):
                        feat.setAttribute(fname, int(w.value()))
                    else:
                        feat.setAttribute(fname, w.text())
                self.layer.updateFeature(feat)
            if need_edit:
                self.layer.commitChanges()
        except Exception:
            if need_edit:
                self.layer.rollBack()
            raise

    def _on_save(self):
        try:
            self._save()
            n = len(self._feats)
            msg = f"{n} 个要素属性已保存" if n > 1 else "属性已保存"
            self.iface.messageBar().pushMessage(
                "aQuaDrip", msg, level=0, duration=3)
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
            model = self._widgets.get("emitter_model")
            if model:
                model.currentIndexChanged.connect(self._on_emitter_model_changed)
                self._on_emitter_model_changed(model.currentIndex())
        elif self.mode == "aqd_pipes":
            ptype = self._widgets.get("pipe_type")
            if ptype:
                ptype.currentIndexChanged.connect(self._on_pipe_type_changed)
                self._on_pipe_type_changed(ptype.currentIndex())
        elif self.mode == "aqd_valves":
            vtype = self._widgets.get("valve_type")
            if vtype:
                vtype.currentIndexChanged.connect(self._on_valve_type_changed)
                self._on_valve_type_changed(vtype.currentIndex())
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

    # aqd_valves 联动
    @staticmethod
    def _on_valve_type_changed(idx):
        """阀门类型变更时不需要显示/隐藏字段，所有字段始终可见"""
        pass

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

    # 滴头型号 → 自动填充 k/x
    def _on_emitter_model_changed(self, idx):
        w = self._widgets.get("emitter_model")
        if not w:
            return
        model_key = w.itemData(idx)
        if model_key:
            # 从内置库读取参数
            from wdrip.network.emitter import BUILTIN_EMITTERS
            spec = BUILTIN_EMITTERS.get(model_key)
            if spec:
                kw = self._widgets.get("emitter_k")
                xw = self._widgets.get("emitter_x")
                if kw:
                    kw.setValue(spec.k)
                    kw.setEnabled(False)
                if xw:
                    xw.setValue(spec.x)
                    xw.setEnabled(False)
                return
        # "自定义" 或未找到型号 → k/x 可编辑
        for f in ("emitter_k", "emitter_x"):
            w2 = self._widgets.get(f)
            if w2:
                w2.setEnabled(True)

    # pipe_type 联动（毛管才显示滴头参数）
    def _on_pipe_type_changed(self, idx):
        w = self._widgets.get("pipe_type")
        if not w:
            return
        is_lateral = (w.itemData(idx) == "lateral")
        for f in ("emitter_spacing", "emitter_k", "emitter_x"):
            self._set_row_visible(f, is_lateral)

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

            # 防御：commitChanges 后重新获取要素，避免 QGIS 内部
            # 使特征对象过期导致 geometry/attribute 读取失败
            fid = self.feat.id()
            fresh_feat = None
            for f in self.layer.getFeatures():
                if f.id() == fid:
                    fresh_feat = f
                    break
            feat = fresh_feat if fresh_feat is not None else self.feat

            # 校验关键参数
            geom = feat.geometry()
            if not geom or geom.isEmpty():
                raise ValueError("农田几何为空，请重新绘制地块")
            rs = feat.attribute("row_spacing") or 0
            ts = feat.attribute("tape_spacing") or 0
            if float(rs) <= 0 or float(ts) <= 0:
                raise ValueError(f"间距参数无效: row_spacing={rs}, tape_spacing={ts}")

            from ..tools.lateral_generator import LateralGenerator
            n = LateralGenerator(self.iface).generate(feat)
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
        for key in ("aqd_fields", "aqd_pipes", "aqd_pumps", "aqd_valves", "aqd_nodes"):
            if name == key or key in src:
                return key
        return None
