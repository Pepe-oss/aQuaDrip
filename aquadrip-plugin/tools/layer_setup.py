"""LayerSetupAction — 一键创建 aQuaDrip 标准 GeoPackage 图层

创建 3 个核心图层 + 1 个辅助图层，配置字段约束和域值。
所有图层存储在同一个 .gpkg 文件中。
"""

import os
from qgis.core import (
    QgsVectorLayer, QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsField, QgsProject, QgsEditorWidgetSetup, QgsDefaultValue,
    QgsFieldConstraints, QgsLayerTreeGroup,
)
from qgis.PyQt.QtCore import QVariant
from typing import Optional

# ---- 图层字段定义 ----

def _text_field(name: str, length: int = 255) -> QgsField:
    """创建文本字段"""
    return QgsField(name, QVariant.String, "text", length)

def _double_field(name: str, precision: int = 2) -> QgsField:
    """创建双精度字段"""
    return QgsField(name, QVariant.Double, "double", 20, precision)

def _int_field(name: str) -> QgsField:
    """创建整数字段"""
    return QgsField(name, QVariant.Int, "integer")


FIELD_DEFS = {
    "aqd_fields": {
        "name": "农田地块",
        "geom": "Polygon",
        "fields": [
            _text_field("name"),
            _double_field("area", 1),
            _text_field("crop_type", 50),
            _text_field("planting_pattern", 20),  # uniform/wide_narrow/ridge_count/custom
            _double_field("row_spacing"),
            _int_field("ridge_count"),
            _double_field("row_direction"),
            _double_field("emitter_spacing"),
        ],
        "value_maps": {
            "planting_pattern": {
                "等行距": "uniform",
                "宽窄行": "wide_narrow",
                "按垄数": "ridge_count",
                "自定义": "custom",
            },
            "crop_type": {
                "玉米": "corn",
                "小麦": "wheat",
                "水稻": "rice",
                "蔬菜": "vegetable",
                "果树": "orchard",
                "其他": "other",
            },
        },
        "defaults": {
            "planting_pattern": "'uniform'",
            "emitter_spacing": "0.3",
        },
    },
    "aqd_pipes": {
        "name": "管道",
        "geom": "LineString",
        "fields": [
            _text_field("pipe_type", 20),  # mainline/submain/lateral
            _text_field("device", 20),     # none/pump/valve
            _text_field("valve_type", 20), # prv/fcv/psv/gate/solenoid/check
            _text_field("status", 10),     # open/closed
            _double_field("diameter"),
            _text_field("material", 20),
            _double_field("roughness"),
            _double_field("pump_head"),
            _double_field("pump_flow"),
            _double_field("pump_power"),
            _double_field("efficiency"),
            _double_field("speed"),
            _double_field("minor_loss"),
            _double_field("lateral_spacing"),
            _double_field("emitter_spacing"),
            _int_field("zone_id"),
            _text_field("from_node", 50),
            _text_field("to_node", 50),
        ],
        "value_maps": {
            "pipe_type": {
                "干管": "mainline",
                "支管": "submain",
                "毛管": "lateral",
            },
            "device": {
                "无": "none",
                "水泵": "pump",
                "阀门": "valve",
            },
            "valve_type": {
                "无": "",
                "减压阀 PRV": "prv",
                "流量控制阀 FCV": "fcv",
                "持压阀 PSV": "psv",
                "手动闸阀": "gate",
                "电磁阀": "solenoid",
            },
            "status": {
                "开启": "open",
                "关闭": "closed",
            },
            "material": {
                "PE": "PE",
                "PVC": "PVC",
                "不锈钢": "stainless",
                "镀锌钢": "galvanized",
            },
        },
        "defaults": {
            "pipe_type": "'mainline'",
            "device": "'none'",
            "status": "'open'",
            "material": "'PE'",
            "roughness": "130",
        },
    },
    "aqd_nodes": {
        "name": "节点",
        "geom": "Point",
        "fields": [
            _text_field("node_type", 20),  # source/fertilizer/junction
            _text_field("source_type", 20),  # well/reservoir/canal/outlet
            _double_field("head"),
            _double_field("available_flow"),
            _double_field("fertilizer_volume"),
            _double_field("fertilizer_concentration"),
            _double_field("elevation"),
        ],
        "value_maps": {
            "node_type": {
                "水源": "source",
                "施肥罐": "fertilizer",
                "普通节点": "junction",
            },
            "source_type": {
                "无": "",
                "机井": "well",
                "蓄水池": "reservoir",
                "河渠": "canal",
                "出水口": "outlet",
            },
        },
        "defaults": {
            "node_type": "'junction'",
        },
    },
    "aqd_obs_points": {
        "name": "观测点",
        "geom": "Point",
        "fields": [
            _text_field("node_id", 50),
            _double_field("measured_pressure"),
            _double_field("measured_flow"),
            _double_field("simulated_pressure"),
            _double_field("simulated_flow"),
        ],
        "defaults": {},
    },
}


class LayerSetupAction:
    """一键创建 GeoPackage 标准图层"""

    DEFAULT_FILE = "aquadrip.gpkg"

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()
        self.gpkg_path = ""
        self._memory_layers = {}

    def setup(self, gpkg_path: str = "") -> bool:
        if not gpkg_path:
            gpkg_path = self._default_path()
        self.gpkg_path = gpkg_path
        self._log(f"创建 GeoPackage: {gpkg_path}")

        # 1. 创建所有内存图层
        self._memory_layers.clear()
        for key, defn in FIELD_DEFS.items():
            layer = self._create_memory_layer(key, defn)
            if not layer:
                self._log(f"  ❌ 创建失败: {defn['name']}")
                return False
            self._memory_layers[key] = layer
            self._log(f"  ✅ 内存图层: {defn['name']} ({key})")

        # 2. 一次性写入 GeoPackage
        if not self._write_to_gpkg():
            return False

        # 3. 重新打开并配置
        for key, defn in FIELD_DEFS.items():
            uri = f"{self.gpkg_path}|layername={key}"
            gpkg_layer = QgsVectorLayer(uri, defn["name"], "ogr")
            if not gpkg_layer.isValid():
                self._log(f"  ❌ 无法打开: {defn['name']}")
                continue
            self._setup_editor_widgets(gpkg_layer, defn)
            self._add_to_project(gpkg_layer, key)
            self._log(f"  ✅ 已添加: {defn['name']}")

        self._log("所有图层创建完成")
        return True

    def _create_memory_layer(self, key: str, defn: dict):
        """创建内存图层"""
        geom_type = defn["geom"]
        crs = self.project.crs()
        crs_str = crs.authid() if crs.isValid() else "EPSG:4326"
        uri = f"{geom_type}?crs={crs_str}"
        layer = QgsVectorLayer(uri, defn["name"], "memory")
        if not layer.isValid():
            return None
        provider = layer.dataProvider()
        provider.addAttributes(defn["fields"])
        layer.updateFields()
        layer.setReadOnly(False)
        return layer

    def _write_to_gpkg(self) -> bool:
        """将所有内存图层写入 GeoPackage"""
        try:
            import processing
            layers = list(self._memory_layers.values())
            if not layers:
                return False
            result = processing.run("native:package", {
                'LAYERS': layers,
                'OUTPUT': self.gpkg_path,
                'OVERWRITE': True,
                'SAVE_STYLES': False,
            })
            if not result or not result.get('OUTPUT'):
                self._log("  写入失败: processing.run 返回空")
                return False
            return True
        except Exception as e:
            self._log(f"  写入失败: {e}")
            return False
        geom_type = defn["geom"]
        crs = self.project.crs()
        crs_str = crs.authid() if crs.isValid() else "EPSG:4326"
        
        uri = f"{geom_type}?crs={crs_str}"
        layer = QgsVectorLayer(uri, defn["name"], "memory")
        if not layer.isValid():
            return False
        
        # 添加字段
        provider = layer.dataProvider()
        provider.addAttributes(defn["fields"])
        layer.updateFields()
        
        # 写入 GeoPackage（使用 V1 API，兼容 QGIS 3.44）
        from qgis.core import QgsVectorFileWriter
        result = QgsVectorFileWriter.writeAsVectorFormat(
            layer,
            self.gpkg_path,
            "UTF-8",
            layer.crs(),
            "GPKG",
        )
        
        if result != QgsVectorFileWriter.NoError:
            self._log(f"  写入失败: error code {result}")
            return False
            self._log(f"  写入失败: {error_msg}")
            return False
        
        # 重新打开 GeoPackage 图层
        gpkg_layer = QgsVectorLayer(uri, defn["name"], "ogr")
        if not gpkg_layer.isValid():
            return False
        
        # 配置字段编辑器控件
        self._setup_editor_widgets(gpkg_layer, defn)
        self._setup_defaults(gpkg_layer, defn)
        
        # 添加到项目
        self._add_to_project(gpkg_layer, key)
        
        return True

    def _setup_editor_widgets(self, layer: QgsVectorLayer, defn: dict):
        """配置字段编辑器控件（下拉选择、默认值等）"""
        # 值映射（下拉选择）
        for field_name, value_map in defn.get("value_maps", {}).items():
            idx = layer.fields().lookupField(field_name)
            if idx < 0:
                continue
            config = {"map": value_map}
            setup = QgsEditorWidgetSetup("ValueMap", config)
            layer.setEditorWidgetSetup(idx, setup)
        
        # 默认值
        for field_name, default_expr in defn.get("defaults", {}).items():
            idx = layer.fields().lookupField(field_name)
            if idx < 0:
                continue
            default = QgsDefaultValue(default_expr)
            layer.setDefaultValueDefinition(idx, default)

    def _setup_defaults(self, layer: QgsVectorLayer, defn: dict):
        """备用：通过约束设置默认值（已由 _setup_editor_widgets 处理）"""
        pass

    def _add_to_project(self, layer: QgsVectorLayer, key: str):
        """将图层添加到 QGIS 项目"""
        self.project.addMapLayer(layer, False)
        root = self.project.layerTreeRoot()
        
        # 找到或创建 aQuaDrip 分组
        aq_group = root.findGroup("aQuaDrip")
        if not aq_group:
            aq_group = root.insertGroup(0, "aQuaDrip")
        
        # 按类型放入子分组
        group_map = {
            "aqd_fields": "农田",
            "aqd_pipes": "管网",
            "aqd_nodes": "设备",
            "aqd_obs_points": "观测",
        }
        sub_name = group_map.get(key, "其他")
        sub_group = aq_group.findGroup(sub_name)
        if not sub_group:
            sub_group = aq_group.addGroup(sub_name)
        
        sub_group.addLayer(layer)
        
        # 设置活动图层
        self.iface.setActiveLayer(layer)

    def _default_path(self) -> str:
        """获取默认 .gpkg 文件路径"""
        project_path = self.project.fileName()
        if project_path:
            base = os.path.splitext(project_path)[0]
            return f"{base}_{self.DEFAULT_FILE}"
        return self.DEFAULT_FILE

    def _log(self, msg: str):
        """输出日志"""
        if self.iface:
            self.iface.messageBar().pushMessage("aQuaDrip", msg, level=0, duration=2)
        print(f"[aQuaDrip] {msg}")
