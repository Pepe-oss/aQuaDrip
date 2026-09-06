"""LayerSetupAction — 一键创建标准图层的基类

使用 sqlite3 直接创建 GeoPackage 图层，确保：
1. fid INTEGER PRIMARY KEY AUTOINCREMENT（QGIS 可编辑的必要条件）
2. gpkg_geometry_columns 元数据完整
3. gpkg_contents 注册正确
4. 所有图层存储在同一个 .gpkg 文件中
"""

import os
import sqlite3
from qgis.core import (
    QgsVectorLayer, QgsProject, QgsEditorWidgetSetup,
    QgsDefaultValue, QgsSnappingConfig, QgsMessageLog,
    QgsCoordinateReferenceSystem,
)
from qgis.PyQt.QtCore import QMetaType
from datetime import datetime
from typing import Optional
from qgis.PyQt.QtWidgets import QApplication

# ── 字段创建辅助 ──

def _text_field(name: str, length: int = 255):
    return {"name": name, "type": QMetaType.QString, "sql": "TEXT"}

def _double_field(name: str):
    return {"name": name, "type": QMetaType.Double, "sql": "REAL"}

def _int_field(name: str):
    return {"name": name, "type": QMetaType.Int, "sql": "INTEGER"}


# ── GPKG 几何类型映射 ──

GEOM_GPKG_MAP = {
    "Polygon": "POLYGON",
    "LineString": "LINESTRING",
    "Point": "POINT",
}

SQL_TYPE_MAP = {
    QMetaType.QString: "TEXT",
    QMetaType.Double: "REAL",
    QMetaType.Int: "INTEGER",
}


# ── 图层字段定义 ──

FIELD_DEFS = {
    "aqd_fields": {
        "name": "Fields",
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
            _text_field("emitter_model", 50),
            _double_field("emitter_k"),
            _double_field("emitter_x"),
            _text_field("rotation_mode", 10),
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
            "emitter_k": "0.506",
            "emitter_x": "0.5",
        },
    },
    "aqd_pipes": {
        "name": "Pipes",
        "geom": "LineString",
        "fields": [
            _text_field("pipe_type", 20),
            _text_field("status", 10),
            _double_field("diameter"),
            _text_field("material", 20),
            _double_field("roughness"),
            _double_field("minor_loss"),
            _double_field("lateral_spacing"),
            _double_field("emitter_spacing"),
            _double_field("emitter_k"),
            _double_field("emitter_x"),
            _int_field("zone_id"),
            _text_field("zone", 20),
            _text_field("from_node", 50),
            _text_field("to_node", 50),
            _double_field("flow"),
            _double_field("velocity"),
            _double_field("max_pressure"),
            _text_field("pressure_status", 12),
        ],
        "value_maps": {
            "pipe_type": {"干管": "mainline", "支管": "submain", "毛管": "lateral"},
            "status": {"开启": "open", "关闭": "closed"},
            "material": {"PE": "PE", "PVC": "PVC", "不锈钢": "stainless", "镀锌钢": "galvanized"},
        },
        "defaults": {
            "pipe_type": "'mainline'",
            "status": "'open'",
            "diameter": "63",
            "roughness": "130",
            "material": "'PE'",
            "emitter_k": "0.506",
            "emitter_x": "0.5",
        },
    },
    "aqd_pumps": {
        "name": "Pumps",
        "geom": "LineString",
        "fields": [
            _text_field("pump_type", 20),
            _text_field("status", 10),
            _double_field("pump_head"),
            _double_field("pump_flow"),
            _double_field("pump_power"),
            _double_field("diameter"),
            _double_field("minor_loss"),
            _text_field("zone", 20),
            _text_field("from_node", 50),
            _text_field("to_node", 50),
            _double_field("flow"),
            _double_field("velocity"),
        ],
        "svg_line": "pump.svg",
        "value_maps": {
            "pump_type": {"离心泵": "centrifugal", "潜水泵": "submersible"},
            "status": {"开启": "open", "关闭": "closed"},
        },
        "defaults": {
            "pump_type": "'centrifugal'",
            "status": "'open'",
            "diameter": "63",
            "pump_head": "20",
        },
    },
    "aqd_valves": {
        "name": "Valves",
        "geom": "LineString",
        "fields": [
            _text_field("valve_type", 20),
            _text_field("status", 10),
            _double_field("diameter"),
            _double_field("setting"),
            _double_field("minor_loss"),
            _text_field("zone", 20),
            _int_field("rotation_order"),
            _double_field("rotation_duration_min"),
            _text_field("from_node", 50),
            _text_field("to_node", 50),
            _double_field("flow"),
            _double_field("velocity"),
        ],
        "svg_line": "valve.svg",
        "value_maps": {
            # 滴灌水力计算中真正影响压力/流量分布的三种调节阀：
            # - PRV 减压阀：地形高差大时保护下游毛管
            # - FCV 流量控制阀：轮灌分区限流
            # - PSV 持压阀：维持上游压力
            # GATE/SOLENOID/CHECK 等无需单独阀门图层
            # （全开=普通管道，关闭=管道 status=closed）
            "valve_type": {"减压阀 PRV": "PRV", "流量控制阀 FCV": "FCV",
                          "持压阀 PSV": "PSV"},
            "status": {"开启": "open", "关闭": "closed"},
        },
        "defaults": {
            "valve_type": "'PRV'",
            "status": "'open'",
            "diameter": "63",
            "setting": "10",   # 非零默认：PRV/PSV/PBV 设 10m，0 会导致阻断
        },
    },
    "aqd_nodes": {
        "name": "Nodes",
        "geom": "Point",
        "fields": [
            _text_field("node_type", 20),
            _text_field("source_type", 20),
            _double_field("head"),
            _double_field("available_flow"),
            _double_field("fertilizer_volume"),
            _double_field("fertilizer_concentration"),
            _double_field("elevation"),
            _double_field("pressure"),
        ],
        "value_maps": {
            "node_type": {"水源": "source", "施肥罐": "fertilizer",
                          "主管节点": "main_junction", "支管节点": "sub_junction",
                          "毛管节点": "lateral_junction", "连接点": "junction"},
            "source_type": {"机井": "well", "蓄水池": "reservoir", "河渠": "canal", "出水口": "outlet"},
        },
        "defaults": {
            "node_type": "'junction'",
            "head": "20",
            "elevation": "0",
        },
    },
    "aqd_obs_points": {
        "name": "Obs Points",
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

# ── 字段中文别名（要素表单/属性表显示用）──

FIELD_ALIASES = {
    # aqd_fields
    "name": "名称", "crop_type": "作物类型", "planting_pattern": "耕作模式",
    "direction_type": "滴灌带方向", "row_spacing": "垄中心距(m)",
    "tapes_per_ridge": "每垄滴灌带数", "tape_spacing": "滴灌带间距(m)",
    "ridge_count": "垄数", "row_direction": "自定义角度(°)",
    "emitter_spacing": "滴头间距(m)", "emitter_model": "滴头型号",
    "emitter_k": "滴头流量系数 k", "emitter_x": "滴头流态指数 x",
    "rotation_mode": "轮灌模式",
    # aqd_pipes
    "pipe_type": "管道类型", "material": "材质",
    "roughness": "糙率C", "minor_loss": "局部损失系数",
    "lateral_spacing": "毛管间距(m)", "zone": "分区", "zone_id": "分区号",
    "from_node": "起点节点", "to_node": "终点节点",
    "flow": "流量(模拟)", "velocity": "流速(模拟)",
    "max_pressure": "最大承压(m)", "pressure_status": "承压状态",
    "diameter": "管径(mm)", "status": "状态",
    "emitter_spacing": "滴头间距(m)", "emitter_k": "滴头流量系数 k",
    "emitter_x": "滴头流态指数 x",
    # aqd_pumps
    "pump_type": "水泵类型", "pump_head": "额定扬程(m)",
    "pump_flow": "额定流量(m³/h)", "pump_power": "额定功率(kW)",
    # aqd_valves
    "valve_type": "阀门类型", "setting": "设定值",
    "rotation_order": "轮灌顺序", "rotation_duration_min": "轮灌时长(min)",
    # aqd_nodes
    "node_type": "节点类型", "source_type": "水源类型", "head": "水头(m)",
    "available_flow": "可用流量(m³/s)", "fertilizer_volume": "施肥罐容积(L)",
    "fertilizer_concentration": "肥液浓度(%)", "elevation": "高程(m)",
    "pressure": "压力(模拟)",
}


class LayerSetupAction:
    """初始化标准 GeoPackage 图层（sqlite3 直写，确保可编辑）"""

    # WGS 84 的完整定义（GPKG 标准要求）
    WGS84_DEF = (
        'GEOGCS["WGS 84",DATUM["WGS_1984",'
        'SPHEROID["WGS 84",6378137,298.257223563,'
        'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],'
        'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
        'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
        'AUTHORITY["EPSG","4326"]]'
    )

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()
        self.gpkg_path = ""
        self._project_crs = None  # setup_layers 中赋值

    def setup_layers(self, gpkg_path: str = "",
                     target_crs=None) -> bool:
        """一键创建所有标准图层

        Args:
            gpkg_path: GPKG 文件路径
            target_crs: 目标 CRS。优先级：target_crs > 项目 CRS > EPSG:4326。
                传入导入栅格的 CRS 可使矢量与栅格坐标系统一。
        """
        if not gpkg_path:
            gpkg_path = self._default_path()
        self.gpkg_path = gpkg_path

        # 确保目录存在
        dirname = os.path.dirname(gpkg_path)
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname, exist_ok=True)

        # 删除旧文件
        if os.path.exists(gpkg_path):
            try:
                os.remove(gpkg_path)
                self._log(QApplication.translate("LayerSetup", "  已删除旧 GPKG"))
            except OSError as e:
                self._log(QApplication.translate("LayerSetup", "  ⚠️ 无法删除: {0}").format(e))

        self._log(QApplication.translate("LayerSetup", "创建 GeoPackage: {0}").format(gpkg_path))

        # 确定 SRS：target_crs > 项目 CRS > WGS 84
        if target_crs is not None and target_crs.isValid():
            crs = target_crs
        else:
            crs = self.project.crs()
            if not crs.isValid():
                crs = QgsCoordinateReferenceSystem("EPSG:4326")

        srs_id = 4326  # WGS 84 默认
        authid = crs.authid()  # "EPSG:4326"
        if authid and ":" in authid:
            try:
                srs_id = int(authid.split(":")[1])
            except (ValueError, IndexError):
                srs_id = 4326
        # 获取 CRS 的完整 WKT 定义（写入 GPKG 元数据）
        self._project_wkt = crs.toWkt()
        self._project_srs_id = srs_id
        # 保留 CRS 对象，供 _add_to_project 使用
        self._project_crs = crs
        self._log(QApplication.translate("LayerSetup", "  目标 CRS: {0} (srs_id={1})").format(authid, srs_id))

        created_layers = []

        for idx, (key, defn) in enumerate(FIELD_DEFS.items()):
            try:
                self._create_gpkg_layer(gpkg_path, key, defn, srs_id, idx == 0)

                # 打开并添加到项目
                uri = f"{gpkg_path}|layername={key}"
                layer = QgsVectorLayer(uri, defn["name"], "ogr")

                if not layer.isValid():
                    self._log(QApplication.translate("LayerSetup", "  ❌ {0} 打开失败").format(defn['name']))
                    continue

                self._setup_editor_widgets(layer, defn)
                self._add_to_project(layer, srs_id, svg_line=defn.get("svg_line"))
                created_layers.append(key)
                self._log(f"  ✅ {defn['name']} ({key})")

            except Exception as e:
                self._log(QApplication.translate("LayerSetup", "  ❌ {0} 失败: {1}").format(defn['name'], e))

        if not created_layers:
            return False

        self._setup_snapping()
        self._log(QApplication.translate("LayerSetup", "完成: {0}/{1} 个图层").format(len(created_layers), len(FIELD_DEFS)))
        return True

    def _create_gpkg_layer(self, gpkg_path: str, key: str,
                           defn: dict, srs_id: int, is_first: bool):
        """直接使用 SQL 在 GPKG 中创建可编辑的图层表"""
        conn = sqlite3.connect(gpkg_path)
        conn.execute("PRAGMA journal_mode=WAL")
        c = conn.cursor()

        # ── 第 1 次：初始化 GPKG 标准元数据表 ──
        if is_first:
            c.execute("""
                CREATE TABLE gpkg_contents (
                    table_name TEXT NOT NULL PRIMARY KEY,
                    data_type TEXT NOT NULL,
                    identifier TEXT,
                    description TEXT DEFAULT '',
                    last_change DATETIME DEFAULT (
                        strftime('%Y-%m-%dT%H:%M:%fZ','now')
                    ),
                    min_x DOUBLE, min_y DOUBLE,
                    max_x DOUBLE, max_y DOUBLE,
                    srs_id INTEGER
                )
            """)
            c.execute("""
                CREATE TABLE gpkg_geometry_columns (
                    table_name TEXT NOT NULL,
                    column_name TEXT NOT NULL,
                    geometry_type_name TEXT NOT NULL,
                    srs_id INTEGER NOT NULL,
                    z TINYINT NOT NULL DEFAULT 0,
                    m TINYINT NOT NULL DEFAULT 0,
                    PRIMARY KEY (table_name, column_name)
                )
            """)
            c.execute("""
                CREATE TABLE gpkg_spatial_ref_sys (
                    srs_id INTEGER PRIMARY KEY,
                    organization TEXT NOT NULL,
                    organization_coordsys_id INTEGER NOT NULL,
                    definition TEXT NOT NULL,
                    description TEXT
                )
            """)
            # 插入 WGS 84 和项目 CRS（如不同）
            c.execute(
                "INSERT OR IGNORE INTO gpkg_spatial_ref_sys "
                "VALUES (?, ?, ?, ?, ?)",
                (4326, "EPSG", 4326, self.WGS84_DEF, "WGS 84"),
            )
            if self._project_srs_id != 4326:
                c.execute(
                    "INSERT OR IGNORE INTO gpkg_spatial_ref_sys "
                    "VALUES (?, ?, ?, ?, ?)",
                    (self._project_srs_id, "EPSG",
                     self._project_srs_id,
                     self._project_wkt,
                     f"EPSG:{self._project_srs_id}"),
                )

        # ── 第 2 步：构建字段 SQL ──
        gpkg_geom = GEOM_GPKG_MAP.get(defn["geom"], "GEOMETRY")
        col_defs = []
        for f in defn["fields"]:
            sql_type = SQL_TYPE_MAP.get(f["type"], "TEXT")
            col_defs.append(f'"{f["name"]}" {sql_type}')
        cols_sql = ",\n    ".join(col_defs)

        # ── 第 3 步：创建数据表 ──
        # fid INTEGER PRIMARY KEY AUTOINCREMENT 是 QGIS 可编辑的关键！
        # 注意：几何列定义为 GEOMETRY，类型约束由 gpkg_geometry_columns 管理
        c.execute(f"""
            CREATE TABLE "{key}" (
                fid INTEGER PRIMARY KEY AUTOINCREMENT,
                geom GEOMETRY,
                {cols_sql}
            )
        """)

        # ── 第 4 步：注册到 GPKG 元数据 ──
        c.execute(
            "INSERT OR IGNORE INTO gpkg_geometry_columns "
            'VALUES (?, "geom", ?, ?, 0, 0)',
            (key, gpkg_geom, srs_id),
        )
        c.execute(
            "INSERT OR IGNORE INTO gpkg_contents "
            "(table_name, data_type, identifier, srs_id) "
            "VALUES (?, 'features', ?, ?)",
            (key, key, srs_id),
        )

        # ── 第 5 步：创建空间索引（提升性能） ──
        try:
            c.execute(f'CREATE INDEX idx_{key}_geom ON "{key}" (geom)')
        except sqlite3.OperationalError:
            pass

        conn.commit()
        conn.close()

    def _setup_snapping(self):
        """启用跨图层捕捉"""
        try:
            config = QgsProject.instance().snappingConfig()
            config.setEnabled(True)
            config.setMode(QgsSnappingConfig.AllLayers)
            config.setType(QgsSnappingConfig.VertexAndSegment)
            config.setTolerance(15)
            config.setIntersectionSnapping(True)
            QgsProject.instance().setSnappingConfig(config)
        except Exception as e:
            self._log(QApplication.translate("LayerSetup", "  捕捉配置跳过: {0}").format(e))

    def _setup_editor_widgets(self, layer, defn: dict):
        """配置编辑器控件（ValueMap + 默认值 + 中文别名）"""
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

        # 中文别名（属性表/要素表单显示）
        for fname, alias in FIELD_ALIASES.items():
            idx = layer.fields().lookupField(fname)
            if idx >= 0:
                layer.setFieldAlias(idx, alias)

    def _add_to_project(self, layer, srs_id=4326, svg_line=None):
        """添加到 aQuaDrip 分组，不重复。

        Args:
            layer: QgsVectorLayer
            srs_id: EPSG 代码
            svg_line: 保留参数（后续用于 SVG 线符号，当前暂不应用）
        """
        # 0. 显式设置 CRS（确保 GPKG 元数据读取正常）
        crs = QgsCoordinateReferenceSystem.fromEpsgId(srs_id)
        if crs.isValid():
            layer.setCrs(crs)

        # 1. 注册到项目（addToLegend=False 不创建图例节点）
        QgsProject.instance().addMapLayer(layer, False)

        # 2. 添加到 aQuaDrip 分组
        root = QgsProject.instance().layerTreeRoot()
        aq_group = root.findGroup("aQuaDrip")
        if not aq_group:
            aq_group = root.insertGroup(0, "aQuaDrip")

        # 3. 手动创建图层节点（避免重复）
        from qgis.core import QgsLayerTreeLayer
        node = QgsLayerTreeLayer(layer)
        aq_group.addChildNode(node)

    def _default_path(self) -> str:
        home = os.path.expanduser("~")
        return os.path.join(home, "Documents", "aquadrip.gpkg")

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        QgsMessageLog.logMessage(msg, "aQuaDrip", 0)
        print(f"[{ts}] {msg}")
