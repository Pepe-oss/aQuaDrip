"""LayerSetupAction — 一键创建标准图层的基类

创建 5 个核心图层（农田地块/毛管/支管/干管/观测点），
配置字段约束和域值。所有图层存储在同一个 .gpkg 文件中。
"""

import os
from qgis.core import (
    QgsVectorLayer, QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsField, QgsProject, QgsEditorWidgetSetup, QgsDefaultValue,
    QgsFieldConstraints, QgsLayerTreeGroup,
    QgsSnappingConfig,
)
from qgis.PyQt.QtCore import QVariant, QMetaType
from typing import Optional

# ---- 图层字段定义 ----

def _text_field(name: str, length: int = 255) -> QgsField:
    """创建文本字段"""
    return QgsField(name, QMetaType.QString)

def _double_field(name: str, precision: int = 2) -> QgsField:
    """创建双精度字段"""
    return QgsField(name, QMetaType.Double)

def _int_field(name: str) -> QgsField:
    """创建整数字段"""
    return QgsField(name, QMetaType.Int)


FIELD_DEFS = {
    "aqd_fields": {
        "name": "农田地块",
        "geom": "Polygon",
        "fields": [
            _text_field("name"),
            _text_field("crop_type", 50),
            _text_field("planting_pattern", 20),
            _text_field("direction_type", 20),
            _double_field("row_spacing"),
            _int_field("tapes_per_ridge"),
            _double_field("tape_spacing"),
            _int_field("ridge_count"),
            _double_field("row_direction"),
            _double_field("emitter_spacing"),
        ],
        "value_maps": {
            "planting_pattern": {"垄模式": "ridge", "按垄数": "ridge_count"},
            "direction_type": {"与田块长边平行": "long_edge", "与田块短边平行": "short_edge", "自定义角度": "custom"},
            "crop_type": {"玉米": "corn", "小麦": "wheat", "水稻": "rice", "蔬菜": "vegetable", "果树": "orchard", "其他": "other"},
        },
        "defaults": {
            "planting_pattern": "'ridge'",
            "direction_type": "'long_edge'",
            "tapes_per_ridge": "1",
            "emitter_spacing": "0.3",
        },
    },
    "aqd_laterals": {
        "name": "毛管",
        "geom": "LineString",
        "fields": [
            _text_field("pipe_type", 10),
            _text_field("status", 10),
            _double_field("diameter"),
            _double_field("roughness"),
            _text_field("material", 20),
            _double_field("emitter_spacing"),
            _double_field("lateral_spacing"),
            _int_field("zone_id"),
            _text_field("from_node", 50),
            _text_field("to_node", 50),
            _double_field("flow"),
            _double_field("velocity"),
        ],
        "value_maps": {
            "pipe_type": {"毛管": "lateral"},
            "status": {"开启": "open", "关闭": "closed"},
            "material": {"PE": "PE", "PVC": "PVC"},
        },
        "defaults": {
            "pipe_type": "'lateral'",
            "status": "'open'",
            "diameter": "16",
            "roughness": "130",
            "material": "'PE'",
            "emitter_spacing": "0.3",
        },
    },
    "aqd_submains": {
        "name": "支管",
        "geom": "LineString",
        "fields": [
            _text_field("pipe_type", 10),
            _text_field("status", 10),
            _double_field("diameter"),
            _double_field("roughness"),
            _text_field("material", 20),
            _text_field("from_node", 50),
            _text_field("to_node", 50),
            _double_field("flow"),
            _double_field("velocity"),
        ],
        "value_maps": {
            "pipe_type": {"支管": "submain"},
            "status": {"开启": "open", "关闭": "closed"},
            "material": {"PE": "PE", "PVC": "PVC"},
        },
        "defaults": {
            "pipe_type": "'submain'",
            "status": "'open'",
            "diameter": "50",
            "roughness": "130",
            "material": "'PE'",
        },
    },
    "aqd_maines": {
        "name": "干管",
        "geom": "LineString",
        "fields": [
            _text_field("pipe_type", 10),
            _text_field("device", 20),
            _text_field("valve_type", 20),
            _text_field("status", 10),
            _double_field("diameter"),
            _double_field("roughness"),
            _text_field("material", 20),
            _double_field("pump_head"),
            _double_field("pump_flow"),
            _double_field("pump_power"),
            _double_field("minor_loss"),
            _text_field("from_node", 50),
            _text_field("to_node", 50),
            _double_field("flow"),
            _double_field("velocity"),
        ],
        "value_maps": {
            "pipe_type": {"干管": "mainline"},
            "device": {"无": "none", "水泵": "pump", "阀门": "valve"},
            "valve_type": {"无": "", "减压阀 PRV": "prv", "流量控制阀 FCV": "fcv", "持压阀 PSV": "psv", "手动闸阀": "gate", "电磁阀": "solenoid"},
            "status": {"开启": "open", "关闭": "closed"},
            "material": {"PE": "PE", "PVC": "PVC", "不锈钢": "stainless", "镀锌钢": "galvanized"},
        },
        "defaults": {
            "pipe_type": "'mainline'",
            "device": "'none'",
            "status": "'open'",
            "diameter": "63",
            "roughness": "130",
            "material": "'PE'",
        },
    },
    "aqd_obs_points": {
        "name": "观测点",
        "geom": "Point",
        "fields": [
            _text_field("name"),
            _text_field("type", 20),
            _text_field("lateral_id", 50),
            _double_field("emitter_k"),
            _double_field("emitter_x"),
            _double_field("measured_pressure"),
            _double_field("measured_flow"),
            _double_field("simulated_pressure"),
            _double_field("simulated_flow"),
        ],
        "value_maps": {
            "type": {"滴头": "emitter", "管道节点": "junction", "水源": "source"},
        },
        "defaults": {"type": "'emitter'"},
    },
}


class LayerSetupAction:
    """初始化标准 GeoPackage 图层"""

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()

    def setup_layers(self, gpkg_path: str = "") -> bool:
        """一键创建所有标准图层"""
        if not gpkg_path:
            gpkg_path = self._default_path()

        dirname = os.path.dirname(gpkg_path)
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname, exist_ok=True)

        self.iface.messageBar().pushMessage("aQuaDrip", f"创建图层: {gpkg_path}", level=0, duration=3)
        self._log(f"创建 GeoPackage: {gpkg_path}")

        from qgis import processing
        memory_layers = []
        for key, defn in FIELD_DEFS.items():
            geom = defn["geom"]
            crs = self.project.crs()
            crs_str = crs.authid() if crs.isValid() else "EPSG:4326"
            uri = f"{geom}?crs={crs_str}"
            layer = QgsVectorLayer(uri, defn["name"], "memory")
            if not layer.isValid():
                self._log(f"  ❌ 无法创建内存图层: {defn['name']}")
                continue
            provider = layer.dataProvider()
            provider.addAttributes(defn["fields"])
            layer.updateFields()
            memory_layers.append(layer)
            self._log(f"  ✅ 内存: {defn['name']} ({key})")

        if not memory_layers:
            self._log("  ❌ 没有可写入的图层")
            return False

        try:
            result = processing.run("native:package", {
                'LAYERS': memory_layers,
                'OUTPUT': gpkg_path,
                'OVERWRITE': True,
                'SAVE_STYLES': False,
            })
        except Exception as e:
            self._log(f"  写入失败: {e}")
            return False

        if not result or not result.get('OUTPUT'):
            self._log("  ❌ 处理结果为空")
            return False

        # 重新打开并配置
        for key, defn in FIELD_DEFS.items():
            uri = f"{gpkg_path}|layername={key}"
            gpkg_layer = QgsVectorLayer(uri, defn["name"], "ogr")
            if not gpkg_layer.isValid():
                self._log(f"  ❌ 无法打开: {defn['name']}")
                continue
            gpkg_layer.setReadOnly(False)
            self._setup_editor_widgets(gpkg_layer, defn)
            self._add_to_project(gpkg_layer)
            self._log(f"  ✅ 添加: {defn['name']}")

        # 配置捕捉
        self._setup_snapping()

        self._log("所有图层创建完成")
        self.iface.messageBar().pushMessage("aQuaDrip", f"{len(FIELD_DEFS)} 个图层已创建", level=0, duration=5)
        return True

    def _setup_snapping(self):
        """启用跨图层捕捉（端点 + 线段）"""
        config = QgsProject.instance().snappingConfig()
        config.setEnabled(True)
        config.setMode(QgsSnappingConfig.AdvancedConfig)
        config.setTolerance(15)
        config.setToleranceType(QgsSnappingConfig.Pixels)
        config.setIntersectionSnapping(True)

        for key in ["aqd_laterals", "aqd_submains", "aqd_maines"]:
            layer = self._find_layer_by_key(key)
            if layer:
                from qgis.core import QgsSnappingConfig, QgsTolerance
                layer_config = QgsSnappingConfig.IndividualLayerSettings(
                    True, QgsSnappingConfig.VertexAndSegment, 15, QgsTolerance.Pixels
                )
                config.setIndividualLayerSettings(layer, layer_config)

        QgsProject.instance().setSnappingConfig(config)

    def _find_layer_by_key(self, key: str):
        """通过 source URI 中的图层名查找已添加的图层"""
        for layer in QgsProject.instance().mapLayers().values():
            s = layer.source() if hasattr(layer, 'source') else ""
            if key in s:
                return layer
        return None

    def _log(self, msg: str):
        """日志输出"""
        from qgis.core import QgsMessageLog
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        QgsMessageLog.logMessage(msg, "aQuaDrip", 0)
        print(f"[{ts}] {msg}")

    def _default_path(self) -> str:
        """默认路径：用户文档目录/aquadrip.gpkg"""
        home = os.path.expanduser("~")
        return os.path.join(home, "Documents", "aquadrip.gpkg")

    def _setup_editor_widgets(self, layer, defn: dict):
        """为图层配置编辑器控件（ValueMap + 默认值）"""
        value_maps = defn.get("value_maps", {})
        defaults = defn.get("defaults", {})

        for fname, options in value_maps.items():
            idx = layer.fields().lookupField(fname)
            if idx < 0:
                continue
            setup = QgsEditorWidgetSetup("ValueMap", {"map": options})
            layer.setEditorWidgetSetup(idx, setup)

        for fname, expr in defaults.items():
            idx = layer.fields().lookupField(fname)
            if idx < 0:
                continue
            layer.setDefaultValueDefinition(idx, QgsDefaultValue(expr))

    def _add_to_project(self, layer):
        """将图层添加到项目中的 aQuaDrip 分组"""
        root = QgsProject.instance().layerTreeRoot()
        aq_group = root.findGroup("aQuaDrip")
        if not aq_group:
            aq_group = root.insertGroup(0, "aQuaDrip")
        aq_group.addLayer(layer)
